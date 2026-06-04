# Think-Tank Full-Text Ingestion (Slice A) — Design Spec

**Datum:** 2026-06-03
**Status:** Proposed
**Slice:** A (Think-Tank-Volltext). Teil von **P2** der RAG-Korpus-Qualität ([[project-rag-corpus-quality]]).
**Depends on:** **PR #37** (`feat/rag-corpus-read-path-scoping`) — dieser Slice modifiziert `rag/corpus_policy.py` + `rag/credibility.py` aus #37. Branch ist auf #37 gestackt.
**Ziel:** Den RSS-**Teaser** (`summary[:1000]`) der ~10 Think-Tank-Feeds durch den **Artikel-Volltext** ersetzen — via die bereits laufenden crawl4ai (HTML) + docling (PDF) REST-Services — gechunkt, embedded, als eigene `source="rss_fulltext"` in Qdrant, mit Supersede des Teasers. **Kein** neuer LLM-Extract (Graph = Slice B).

---

## 1. Motivation

Der tiefste verbleibende Korpus-Hebel nach #37: der Lesekorpus enthält von Think-Tanks nur **Titel + Teaser** (`rss_collector.py` speichert `summary[:1000]`, embed `[:2000]`), nicht die argumentative Substanz (Einschätzungen, Ursachenketten, Akteurslogik, Policy-Implikationen). Ein Artikel = **1** semantisch dünner Punkt statt vieler treffender Chunks.

**Spike (2026-06-03, live verifiziert):** crawl4ai `/md` (v0.8.6, :11235) auf einen echten War-on-the-Rocks-Artikel (URL aus Live-Qdrant) → `success:true`, **18.831 Zeichen** sauberes Markdown vs. der 1.000-Zeichen-Teaser → **~19× mehr Substanz**. **Erkenntnis:** das rohe `markdown`-Feld enthält Subscription-/Nav-Boilerplate oben — wir müssen die **content-gefilterte (`fit`) Variante** nehmen, plus ein **Quality-Gate** (paywalled Artikel liefern sonst nur den Marketing-Header).

Beide Dienste laufen bereits als eigene Container: **crawl4ai** `:11235` (HTML→Markdown, JS-Rendering) und **docling-serve** `:5001` (PDF/Report→Text). Slice A ist damit eine **Integration zweier REST-Services**, kein Crawler-Bau.

## 2. Engineering Lens

| Frage | Antwort |
|---|---|
| Welcher Invariant wird geschützt? | Für jeden erfolgreich gecrawlten Think-Tank-Artikel enthält der Lesekorpus den **Volltext als Chunks** (statt Teaser), mit erhaltener Provenance + Credibility; der Teaser wird auditierbar superseded (nicht gelöscht); ein Artikel wird **nie doppelt** retrieved. |
| Welcher Context besitzt ihn? | Ein **entkoppelter Enrichment-Collector** (data-ingestion) besitzt Fetch→Chunk→Write→Supersede. Die Read-Corpus-Policy (#37 `corpus_policy.py`) besitzt *welche Quellen lesbar sind* (jetzt + `rss_fulltext`, − superseded). `credibility.py` besitzt Reliability (jetzt + Domain-Overrides). |
| Kleinster Vertrag? | `rss_fulltext`-Punkte tragen **kanonische** Provenance (`source_type="rss"`, `provider`=Feed-Domain), geerbte `feed_name`/`url`/`title`/`published_at`/`entities`, deterministische IDs. Supersede = Payload-Flag auf dem Teaser. Read-Path: `ANALYSIS_SOURCES += rss_fulltext` + `must_not superseded_by_fulltext`. |
| Welcher Test ist rot? | Read-Path-Filter ohne `rss_fulltext`/`must_not superseded`; ein Collector-Test, der erwartet dass ein gecrawlter Artikel N Chunks + 1 superseded Teaser erzeugt; das 6-Query-Harness, in dem Volltext-Chunks die Teaser schlagen. |
| Was verschwindet? | Der teaser-only Lesekorpus für Think-Tanks; ein Artikel als ein dünner Vektor. |

Leitlinie: **Parnas** (Collector entkoppelt von RSS; Policy an einer Stelle), **Beck/Feathers** (Red-first, Vorher/Nachher-Messung), **YAGNI** (kein LLM-Extract, kein Wire/Gov, kein Hard-Delete — alles Folge-Slices).

## 3. Scope / Non-Goals

**In Scope**
- Entkoppelter `fulltext_collector` (Scheduler-Job): scrollt Think-Tank-Teaser, crawlt, chunked, schreibt `rss_fulltext`, supersedet Teaser.
- crawl4ai (HTML, `fit`-Markdown) + docling (PDF) Clients mit Routing + Quality-Gate.
- Struktur-bewusstes Chunking (~650 Token, 80–120 Overlap).
- Read-Path (#37): `ANALYSIS_SOURCES += rss_fulltext`, `analysis_filter` `must_not superseded`, `validate_lane` Belt-and-Suspenders.
- credibility.py: Domain-Overrides für die 10 Think-Tank-Domains.
- Qdrant-Payload-Indizes (feed_name, url, superseded_by_fulltext, fulltext_article_id).
- Mess-Harness re-run (AC).

**Non-Goals (Folge-Slices)**
- **Slice B:** LLM-Graph-Extract aus Volltext → Neo4j (Spark/vLLM-Batch, Rate-Limits, Qualitätsschwellen).
- **Slice B′:** Gov/Mil-Primary-Volltext (eigene Source-Klasse / Tier).
- **Slice C:** Podcast-Transkripte ([[reference-security-podcasts]]).
- Wire/Defense-Media-Volltext.
- **Kein** Hard-Delete (Supersede via Flag). **Kein** neuer LLM-Extract in Slice A (Entities werden vom Teaser geerbt).

## 4. Architektur — entkoppelter Scroll-Enrichment-Job

```
Scheduler (eigener Job, eigenes Intervall)
  → fulltext_collector.run()
      1. SELECT: Qdrant scroll (record.id BEHALTEN)
           source="rss" ∧ feed_name ∈ THINKTANK_FEEDS ∧ ¬superseded_by_fulltext
           ∧ status ∉ {done, failed_permanent, skipped_paywall}
           → in-memory: status=retry ∧ fulltext_retry_epoch > now überspringen
           → batch (config fulltext_batch_size)
      2. pro Teaser (record.id, url, feed_name, provider, entities, title, published_at):
           fetch = route(url): .pdf → docling | sonst → crawl4ai fit-md
           quality_gate(fetch): cleaned_chars<min ∨ paragraphs<min → SKIP
           ok:  chunks = chunk(markdown); embed each (TEI)
                → (1) upsert rss_fulltext points (uint64-IDs, geerbte Meta)
                → (2) set_payload(points=[record.id]): superseded_by_fulltext=true,
                                     status="done", fulltext_article_id, chunk_count, ingested_at
           transient fail: set_payload(points=[record.id]): status="retry"(+retry_epoch,attempts++)
                           | attempts≥MAX → status="failed_permanent"
           paywall/short : set_payload(points=[record.id]): status="skipped_paywall"
                         → Teaser bleibt im Lesepfad (Fallback)
```

**Entkoppelt** (nicht RSS-getriggert): backfillt den **Bestand** sofort (CSIS=10, RUSI… Teaser) und zieht später neue Teaser nach. Idempotent: `superseded=true` = Done-Marker; `fulltext_retry_epoch` = Backoff für Fehlversuche. Crawl/docling-Latenz/Ausfall berührt den RSS-Pfad nie.

## 5. Komponenten (kleine, testbare Units)

### 5.1 `feeds/_fulltext_fetch.py` (neu) — Fetch-Clients + Routing + Quality-Gate
- `async fetch_fulltext(url) -> str | None`: Routing — `url` endet `.pdf` oder Content-Type PDF → `docling`, sonst `crawl4ai`.
- **crawl4ai:** `POST {CRAWL4AI_URL}/md` mit `{"url": url, "f": "fit"}` → `fit`-Markdown (boilerplate-arm). *Impl-Hinweis:* Spike sah raw `markdown` mit Boilerplate; den exakten `fit`-Param/Response-Key (`markdown` vs `fit_markdown`) gegen die laufende v0.8.6-API verifizieren; Fallback: raw + Boilerplate-Strip.
- **docling:** `POST {DOCLING_URL}/…convert…` mit der Artikel-URL → Markdown/Text. *Impl-Hinweis:* exakten docling-serve-Endpoint (`/v1…/convert`) gegen :5001 verifizieren.
- **Quality-Gate (testbar):** zuerst Nav-/Link-only-Zeilen filtern (Zeilen fast nur aus Markdown-Links `[…](…)`/Menü-Tokens). Dann verlangen: bereinigte Zeichen ≥ `fulltext_min_body_chars` (~1500) **und** Prosa-Absätze ≥ `fulltext_min_paragraphs` (~3). Sonst → `None`. Die Metrik (`cleaned_chars`, `paragraph_count`) ist deterministisch + unit-testbar (paywalled Marketing-Header fällt durch → `skipped_paywall`).
- Timeouts, ein Retry, strukturierte Logs.
- **Plan-Task 1 (verpflichtend zuerst):** crawl4ai-`/md`-(`fit`)- und docling-`/convert`-Endpoint-Shape gegen die **laufenden** Services (`:11235`/`:5001`) pinnen und Test-Fixtures (echte Response-JSONs) daraus bauen, BEVOR die Clients gebaut werden. Erst dann sind die `fit`-Param-/Response-Key-Annahmen Fakt statt Vermutung.

### 5.2 `feeds/fulltext_chunker.py` (neu) — Struktur-bewusstes Chunking
- `chunk_markdown(md) -> list[str]`: Split an **Markdown-Heading → Absatz → Satz**-Grenzen (kein blindes Fixed-Window — sonst landen Nav/Footnotes quer in Chunks). Akkumuliere bis ~**650 Token** (Approx ~4 Zeichen/Token ⇒ ~2600 Zeichen), **80–120 Token Overlap** (1–2 Sätze in den nächsten Chunk übertragen). Verwirf Chunks, die fast nur Links/sehr kurz sind.
- Token-Zählung: char-Approx (kein tiktoken-Dep nötig; Qwen3-Embedding-Kontext ≫ 650).

### 5.3 `feeds/fulltext_collector.py` (neu) — Orchestrierung
- `async run()`: SELECT (5.4) → pro Teaser fetch (5.1) → chunk (5.2) → embed (TEI, wie RSS-Collector) → write (5.5) → supersede/mark (5.6).
- Per-Domain-Rate-Limit (~10 Domains, niedrig); BATCH_SIZE; graceful bei crawl4ai/docling-Down (loggen, sauber enden, kein RSS-Impact).

### 5.4 SELECT (Qdrant scroll) — status-aware
**Status-Modell** `fulltext_status` (Payload, keyword-indexiert): absent/`pending` (nie versucht), `done` (Erfolg, superseded), `retry` (transienter Fehler, + `fulltext_retry_epoch`), `failed_permanent` (Attempts erschöpft), `skipped_paywall` (Quality-Gate). **`record.id` wird beim Scroll behalten** (Supersede-Selektor, §5.6).
Filter: `must: source=rss`, `must: feed_name match any THINKTANK_FEED_NAMES`, `must_not: superseded_by_fulltext=true`, **`must_not: fulltext_status match any [done, failed_permanent, skipped_paywall]`**. Danach in-memory: `status=retry ∧ fulltext_retry_epoch > now` überspringen (Backoff). So fasst der Job fertige/dauerhaft kaputte Artikel **nicht erneut** an.

### 5.5 Writer — `rss_fulltext`-PointStruct (pro Chunk)
**Point-ID = uint64** (Qdrant akzeptiert uint64 ODER UUID-String, KEINEN beliebigen 64-char SHA-Hex — bestehende Collector schreiben Integer-IDs aus Hash-Präfixen, gleiches Muster):
```
chunk_uid = sha256(f"rss_fulltext|{normalized_url}|{chunk_index}").hexdigest()
point_id  = int(chunk_uid[:16], 16)                 # uint64, deterministisch → Re-Run upsertet
vector    = TEI.embed(chunk_text)
payload   = {
  "source": "rss_fulltext",
  "source_type": "rss",                    # kanonisch → Credibility/Tiering/Guard
  "provider": feed_provider_domain,        # z.B. "csis.org" → Domain-Override (5.7)
  "feed_name": feed_name,                  # Label, für Display/Messung
  "url": normalized_url, "title": title,
  "published_at": published_at, "published": published,   # geerbt (kanonisch + legacy)
  "entities": teaser_entities,             # GEERBT → Graph-Context-Reuse, kein LLM
  "content": chunk_text,
  "content_hash": sha256(chunk_text).hexdigest()[:16],
  "chunk_uid": chunk_uid,                  # voller Hash als Audit-Feld (ID selbst ist uint64)
  "fulltext_article_id": sha256(normalized_url).hexdigest()[:16],   # Article-Link
  "chunk_index": i, "chunk_count": n,
  "ingested_at": now_iso,
}
```

### 5.6 Supersede / Failure-Tracking (`set_payload` auf den gescrollten Teaser-`record.id`)
Selektor ist die beim Scroll behaltene **`record.id`** — **nicht** ein URL-Filter (vermeidet URL-Normalisierungs-/Dup-Fehler): `client.set_payload(payload={…}, points=[record.id], wait=True)`. `url` bleibt Audit-/Dedup-Feld, aber nicht Supersede-Selektor.
- **Erfolg:** `superseded_by_fulltext=true, fulltext_status="done", fulltext_article_id, fulltext_chunk_count, fulltext_ingested_at`.
- **Transienter Fehler:** `fulltext_status="retry", fulltext_attempts+=1, fulltext_attempted_at, fulltext_error, fulltext_retry_epoch = now + backoff(attempts)`. Bei `attempts ≥ FULLTEXT_MAX_ATTEMPTS` → `fulltext_status="failed_permanent"`.
- **Paywall/zu-kurz (Quality-Gate):** `fulltext_status="skipped_paywall", fulltext_attempted_at, fulltext_error`.
Teaser bleibt in allen Fehlerfällen lesbar (Fallback).

### 5.7 `rag/credibility.py` (#37) — Domain-Overrides ergänzen
Write-side schreibt `provider`=Domain (kanonisch). Die #37-Overrides sind **Label**-Keys (für Legacy-Teaser ohne canonical provider). Für `rss_fulltext` (provider=Domain) **zusätzlich Domain-Keys**:
```
"csis.org": 0.82, "rusi.org": 0.82, "rand.org": 0.82, "sipri.org": 0.82,
"swp-berlin.org": 0.82, "atlanticcouncil.org": 0.82, "brookings.edu": 0.82,
"crisisgroup.org": 0.82, "warontherocks.com": 0.82, "bellingcat.com": 0.85,
```
`normalize_provider("csis.org")` → `"csis.org"` (matcht). Schließt nebenbei die latente Lücke für kanonisch geschriebene normale rss-Punkte.

### 5.8 `rag/corpus_policy.py` (#37) — Read-Path
- `ANALYSIS_SOURCES = frozenset({"rss", "rss_fulltext"})`.
- `analysis_filter()`:
  ```
  {"should": [
     {"key":"source","match":{"any": sorted(ANALYSIS_SOURCES)}},
     {"must_not":[{"is_empty":{"key":"notebook_id"}}]},
   ],
   "must_not": [{"key":"superseded_by_fulltext","match":{"value": True}}]}
  ```
  (Qdrant: `(≥1 should) AND (kein must_not)` → superseded Teaser nie retrieved.)
- `validate_lane(..., "analysis")` **Belt-and-Suspenders:** zusätzlich `if r.get("superseded_by_fulltext") is True: drop`. (`rss_fulltext` ist via ANALYSIS_SOURCES identity-ok; `source_type="rss"` ∈ `_ANALYSIS_TYPES` type-ok.)
- **Keine** `evidence.py`-Änderung nötig (kanonische Felder greifen direkt).

### 5.9 Config (`config.py` data-ingestion + intelligence) — Pydantic
Pydantic-Felder **lower_snake**, ENV-Namen **UPPER** (automatisch): `fulltext_enabled` ↔ `FULLTEXT_ENABLED`, `crawl4ai_url` ↔ `CRAWL4AI_URL` usw.
- **`fulltext_enabled: bool = False`** — **Opt-in-Schalter (Default AUS).** Wegen externer Crawls + Qdrant-Mutation no-opt der Collector, bis explizit `FULLTEXT_ENABLED=true`. Der Scheduler-Job returnt sofort (loggt „disabled"), wenn aus. Operator-Guard.
- `thinktank_feeds`: Map `feed_name → provider_domain` (siehe §6).
- `crawl4ai_url` (`http://localhost:11235`), `docling_url` (`http://localhost:5001`).
- `fulltext_batch_size`, `fulltext_min_body_chars` (1500), `fulltext_min_paragraphs` (3), `fulltext_chunk_tokens` (650), `fulltext_chunk_overlap` (100), `fulltext_max_attempts`, `fulltext_rate_limit_per_domain`. Alle env-overridable.

## 6. Think-Tank-Subset (exakt aus `rss_collector.py` verifiziert)

| feed_name | provider domain |
|---|---|
| CSIS | csis.org |
| RUSI Commentary / RUSI Publications | rusi.org |
| RAND Corporation | rand.org |
| SIPRI | sipri.org |
| SWP Publications (DE) / (EN) | swp-berlin.org |
| Atlantic Council | atlanticcouncil.org |
| Brookings | brookings.edu |
| Crisis Group | crisisgroup.org |
| War on the Rocks | warontherocks.com |
| Bellingcat | bellingcat.com |

12 Feeds → 10 Domains. (Arms Control Association bewusst **nicht** in Slice A — Folge-Slice.)

## 7. Qdrant-Payload-Indizes (typisiert)

Der Scroll-SELECT + der Read-Path-Filter brauchen Indizes. **#37-Refactor nötig:** dort ist `REQUIRED_PAYLOAD_INDEXES` ein Namens-Tuple und `ensure_payload_indexes.py` legt **alles als `keyword`** an. Auf eine **typisierte** Form umstellen — Dict `field → field_schema`:
```python
PAYLOAD_INDEXES: dict[str, str] = {
    "source": "keyword", "telegram_channel": "keyword", "notebook_id": "keyword",  # #37
    "feed_name": "keyword", "url": "keyword",
    "fulltext_article_id": "keyword", "fulltext_status": "keyword",
    "superseded_by_fulltext": "bool",   # Bool-Index für must_not-Read-Filter + SELECT
}
```
`ensure_indexes` iteriert `field, schema` → `create_payload_index(field_name=field, field_schema=schema, wait=True)`. `missing_payload_indexes` prüft gegen `PAYLOAD_INDEXES.keys()`. **Test (verpflichtend):** Migration setzt `superseded_by_fulltext` wirklich als **`bool`** (nicht keyword); idempotent.
Startup validiert (warnt), mutiert nicht (#37-Pattern). HNSW-Rebuild bei nachträglichem Index → **Snapshot vorher** (Operator).

## 8. Fehlerbehandlung / Degradation
- crawl4ai/docling down → Job loggt + endet sauber; Teaser unverändert (Read-Path nutzt Teaser weiter).
- Crawl-Fail/Paywall/zu-kurz → `fulltext_status` + Backoff; Teaser bleibt lesbar; harte Attempt-Obergrenze.
- Embed-Fail eines Chunks → Artikel abbrechen, `status="retry"`, **keine** Teil-Chunks schreiben (erst alle Chunks embedden, dann gesammelt upserten).
- **Zweiphasig, NICHT atomar** (Qdrant hat keine Multi-Op-Transaktion): Reihenfolge = (1) alle Chunks upserten, (2) Teaser superseden + `status="done"`. Scheitert Schritt 2, existieren **transient** Teaser + Chunks gleichzeitig (Teaser kurz mit-retrieved, da noch nicht superseded). **Akzeptiert** — der nächste Run heilt: deterministische uint64-Chunk-IDs ⇒ Upsert-No-Op, der noch nicht `done`-Teaser wird re-selektiert ⇒ erneutes Supersede. Eventual consistency, idempotent.
- Re-Run: deterministische uint64-IDs ⇒ Upsert (keine Duplikate); `done`/`failed_permanent`/`skipped_paywall` ⇒ skip; `retry` ⇒ erst nach `retry_epoch`.

## 9. Tests (TDD — Red zuerst)
`services/data-ingestion/tests/`:
1. `test_fulltext_fetch.py`: Routing (.pdf→docling, sonst crawl4ai); crawl4ai-Aufruf nutzt `f="fit"` (gemockt); Quality-Gate verwirft zu-kurz/boilerplate; Fehler→None.
2. `test_fulltext_chunker.py`: Split an Heading/Absatz/Satz; ~650-Token-Ziel + 80–120 Overlap; Nav/Link-only-Chunk verworfen; kein Mitten-im-Wort-Split.
3. `test_fulltext_writer.py`: PointStruct-Shape — `source="rss_fulltext"`, kanonisch `source_type="rss"`+`provider=domain`, geerbte `feed_name/url/title/published_at/published/entities`, **`point_id = int(sha256("rss_fulltext|url|idx").hexdigest()[:16],16)` (uint64)** + `chunk_uid` (voller Hash) im Payload, `fulltext_article_id`/`chunk_index`/`chunk_count`.
4. `test_fulltext_collector.py` (gemockte Qdrant/fetch/embed): erfolgreicher Artikel ⇒ N Chunk-Upserts **dann** `set_payload(points=[record.id], payload={superseded=true, status="done", …}, wait=True)` (Selektor = **record.id**, nicht URL); transienter Fehler ⇒ kein Chunk, `status="retry"`+`retry_epoch`, **nicht** superseded; `attempts ≥ MAX` ⇒ `status="failed_permanent"`; Quality-Gate-Skip ⇒ `status="skipped_paywall"`; SELECT excludet `done/failed_permanent/skipped_paywall` + skippt `retry_epoch>now`; Re-Run idempotent (uint64-Upsert).
`services/intelligence/tests/`:
5. `test_corpus_policy.py` (erweitert): `analysis_filter` enthält `rss_fulltext` in source-any **und** `must_not superseded_by_fulltext`; `validate_lane` droppt ein superseded rss-Payload; behält `rss_fulltext`-Chunk (source_type=rss).
6. `test_credibility.py` (erweitert): `credibility_score("rss","csis.org")==0.82`, `…("rss","bellingcat.com")==0.85`, etc. (Domain-Keys).
7. `test_ensure_payload_indexes.py` (erweitert): neue typisierte Indizes (superseded_by_fulltext=bool, feed_name/url/article_id=keyword) werden angelegt; idempotent.

## 10. Messung + Acceptance Criteria
Nach einem Backfill-Lauf über das Think-Tank-Subset (live, crawl4ai/docling erreichbar): `scripts/measure_corpus_scoping.py` (#37) erneut über die 6 festen Queries.
- **AC-1:** In den 6 Queries gewinnen `rss_fulltext`-Chunks aus **≥ CSIS, RUSI, RAND, SWP, Bellingcat** sichtbar über die alten Teaser (und über GDELT) — Vorher/Nachher-Tabelle in der PR.
- **AC-2:** Kein Artikel doppelt (Teaser superseded ⇒ nicht retrieved); zwei Schranken (Filter `must_not` + `validate_lane`).
- **AC-3:** Volltext-Chunks tragen die Think-Tank-Credibility (Domain-Override) → Tier-Boost greift; `feed_name` im EVIDENCE für Messbarkeit.
- **AC-4:** Re-Run idempotent (keine Duplikate, superseded geskippt); Fehlversuche backen off statt Endlos-Crawl.
- **AC-5:** Alle bestehenden Tests grün; neue Tests decken §9 ab; data-ingestion + intelligence Suites grün; ruff clean.

## 11. Deployment-Hinweis (Operator)
data-ingestion läuft im Container → `localhost:11235`/`:5001` erreichen crawl4ai/docling **nicht** von dort. `CRAWL4AI_URL`/`DOCLING_URL` müssen auf erreichbare Adressen zeigen (`host.docker.internal` oder gemeinsames Docker-Netz / Compose-`extra_hosts`). Lokaler Backfill-Lauf via `uv run` vom Host funktioniert mit `localhost`. Vor dem ersten Lauf: **Qdrant-Snapshot** (HNSW-Rebuild durch neue Indizes). Read-Path-Änderungen brauchen Rebuild des intelligence-Images (nach #37+Slice-A-Merge).

## 12. Referenzen
- crawl4ai (lokal, `/home/deadpool-ultra/crawl4ai`, :11235, v0.8.6) `/md`-Endpoint; docling-serve :5001.
- `rss_collector.py` (feed config, `provider`=Domain, `summary[:1000]`).
- #37-Spec `2026-06-02-rag-corpus-read-path-scoping-design.md` (corpus_policy/credibility/ensure_payload_indexes Basis).
- Memory: [[project-rag-corpus-quality]], [[reference-security-podcasts]], [[reference-dgx-spark]] (Slice B Spark-Offload).
- Betroffene Dateien: neu `feeds/_fulltext_fetch.py`, `feeds/fulltext_chunker.py`, `feeds/fulltext_collector.py`; mod `scheduler.py`, `config.py` (data-ingestion); mod `rag/corpus_policy.py`, `rag/credibility.py`, `rag/qdrant_schema.py`, `scripts/ensure_payload_indexes.py` (intelligence).
