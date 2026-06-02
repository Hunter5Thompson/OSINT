# RAG Corpus Read-Path Scoping + Tier-Rerank (Design Spec)

**Datum:** 2026-06-02
**Status:** Proposed
**Slice:** P1 (Read-Path-Scoping) + P4 (Source-Tier-Rerank) der RAG-Korpus-Qualitäts-Arbeit
**Ziel:** Briefing-Recherche (Munin) so scopen und reranken, dass Prosa-Analyse
(Think-Tanks, NotebookLM-Extraktionen) sichtbar nach oben kommt und GDELT-/Sensor-/
ungeprüfter-Telegram-Rauschen das finale Evidence-Set **nie** erreicht — ohne
Re-Extraktion oder Re-Embedding der bestehenden Punkte.

---

## 1. Motivation

Beim ersten echten Munin-Briefing (nach Merge PR #36) kamen als Quellen
ausschließlich GDELT-GKG-Müll (`drudge.com`, `iraqsun.com`, ein Sonnencreme-
Artikel) statt der konfigurierten Think-Tanks. Live-Diagnose der Collection
`odin_intel` (292.776 Punkte, Stand 2026-06-02):

| Befund | Evidenz |
|---|---|
| **Kein Source-Filter im Read-Path** | `agents/tools/qdrant_search.py` ruft `enhanced_search(query, limit=5, region=…)` ohne `source` auf. Der Parameter existiert in `retriever.py` bereits, wird aber nicht genutzt → die Suche durchläuft den gesamten Korpus inkl. ~79 % GDELT-GKG. |
| **GDELT-GKG hat keinen lesbaren Body** | `source=gdelt_gkg`: `title == doc_id` (`gdelt:gkg:20260505133000-218`), nur `organizations`/`persons`/`linked_event_ids`. Discovery-/Graph-Artefakt, kein Lese-Korpus. |
| **NLM-Analyse ist als `source="unknown"` gespeichert** | Die wertvollsten kuratierten Extraktionen (Feld `content` = Claim, `notebook_id`, `entities`) tragen `source="unknown"` (Legacy-Punkte vor dem Provenance-Contract). Ein naiver Whitelist `{rss, nlm}` würde **null** NLM-Content liefern; `credibility.py` mappt `"unknown"` → 0.30 (niedrigster Tier). |
| **Think-Tanks ranken nicht über Lokalquellen** | `credibility.PROVIDER_OVERRIDES` kennt nur `reuters.com`/`bbc.co.uk` (Domain-Keys). RSS-`provider` wird aber aus `feed_name` (Label) abgeleitet → CSIS/RUSI/RAND erhalten die generische rss-Baseline 0.60, identisch zu jedem Lokal-Feed. Der vorhandene Tier-Mechanismus annotiert nur, er **rankt nicht**. |
| **Reranker ignoriert RSS-Teaser** | `reranker.py` nutzt `content or title`. RSS-Payloads haben **kein** `content`, nur `summary` → RSS wird allein auf dem **Titel** gerankt. |

Korpus-Komposition (Live, gerundet): GDELT-GKG ~79 %, FIRMS ~16 %, RSS ~3,7 %,
davon echte Think-Tank-Analyse ≈ 0,4 %. Die 36 RSS-Feeds sind gut konfiguriert
(Atlantic Council, War on the Rocks, Brookings, Crisis Group, RAND, RUSI, SIPRI,
SWP, CSIS, Bellingcat …) — das Problem ist **Korpus-Komposition + Retrieval**, nicht
die Feed-Auswahl.

**Wichtig:** `qdrant_search` ist der **einzige** Produktiv-Caller von
`enhanced_search`. Der Briefing/Munin-Pfad hat keine eigene Retrieval-Funktion —
er fährt über den ReAct-Agenten, der dieses eine Tool nutzt. Eine Scoping-Policy
im Tool wirkt damit auf Briefings **und** Ad-hoc-Intel-Queries. Für `gdelt_gkg`/
`firms` ist das gewollt: beide haben nirgends Prosatext; ihr Wert liegt im Neo4j-
Graph (`graph_query`), nicht im semantischen Evidence-Tool.

## 2. Engineering Lens

| Frage | Antwort |
|---|---|
| Welcher fachliche Invariant wird geschützt? | Das finale Briefing-Evidence-Set enthält nur geprüfte Analyse-Prosa (rss/NLM) plus höchstens eine klar markierte Realtime-Evidence (vetted Telegram). `gdelt_gkg`, `firms` und ungeprüftes Telegram erscheinen nie. |
| Welcher Context besitzt ihn? | Eine neue Read-Corpus-Policy (`rag/corpus_policy.py`) besitzt *welche Quellen lesbar sind* und *wie Reputation Relevanz nudged*. `credibility.py` bleibt die Reliability-Registry. `qdrant_search` ist der einzige Konsument. |
| Was ist der kleinste explizite Vertrag? | Pre-retrieval Whitelist-Filter (Qdrant) + post-rerank Tier-Boost (read-side) + defensiver Output-Guard, alle aus *einer* prüfbaren Stelle. Generische `search()`/`enhanced_search()` bleiben Primitives mit optionalem `query_filter` und optionalem `post_rerank`-Callback (Defaults neutral). |
| Welcher Test ist vor der Änderung rot? | Ein `qdrant_search`-Test, der bei gemischtem Korpus `gdelt_gkg`/`firms` im Output sieht; ein Tier-Boost-Test, der erwartet, dass CSIS eine knapp relevantere Lokalquelle überholt; die sechs Messungs-Queries. |
| Was verschwindet? | Der ungescopte Vollkorpus-Read; die stille GKG-Kontamination der Briefings; der titel-only RSS-Rerank. |

Leitlinie: **Parnas** für die Policy-Grenze (eine Stelle kennt die Korpus-Regeln,
das Retriever-Primitive bleibt neutral), **Beck/Feathers** für den abgesicherten
Verhaltenswechsel (Red zuerst, Messung vorher/nachher), **YAGNI** für den bewusst
engen Slice (keine Structured-Evidence-Lane, kein Volltext, keine Migration der
bestehenden Punkte in diesem Schritt).

## 3. Scope / Non-Goals

**In Scope**
- Zwei-Lane-Read-Corpus-Policy (Analyse-Lane + Realtime-Lane), angewandt im `qdrant_search`-Tool.
- Pre-retrieval Qdrant-Whitelist-Filter pro Lane.
- Defensiver Output-Guard (zweite Schranke) vor dem Merge.
- Kandidatenpool 40 → bge-Rerank → Tier-Boost → finale Top-5.
- Think-Tank- **und** Wire-Provider-Overrides in `credibility.py` (an echte `feed_name`-Keys gekoppelt).
- Reranker-Textfix `content or summary or title`.
- Qdrant-Payload-Indizes (`source`, `telegram_channel`, `notebook_id`) als idempotentes Migrationsskript; Startup validiert nur.
- Mess-Harness mit sechs festen Queries (vorher/nachher).

**Non-Goals (dokumentierte Follow-ups, Abschnitt 12)**
- Structured-Evidence-Lane (`ucdp`, `ofac`, `portwatch`, `hapi`) — wertvoll, aber strukturiert; gehört in eigene Lane oder Graph-Abfrage.
- Relabel `source="unknown"`→`"nlm"` + Writer-Default-Fix.
- Wire-Aliase Al Jazeera / France24 (separate Reliability-Einschätzung).
- P2: Think-Tank-Volltext (crawl4ai/docling) + Podcast-Transkripte (Sicherheitshalber, Streitkräfte & Strategien).
- GKG physisch in eigene Collection (P5).

## 4. Architektur

Eine Policy-Stelle, drei Wirkungen (Filter / Tier-Boost / Output-Guard), zwei Lanes:

```
qdrant_search(query)
   │
   ├── Analyse-Lane:  enhanced_search(query, query_filter=ANALYSIS_FILTER, pool=40,
   │                                  post_rerank=apply_tier_boost)
   │       → dense (gefiltert) → bge-rerank(top_k=pool) → tier_boost → sortiert
   │
   ├── Realtime-Lane: enhanced_search(query, query_filter=REALTIME_FILTER, pool=20,
   │                                  score_threshold=RT_SCORE_THRESHOLD,
   │                                  post_rerank=apply_tier_boost)
   │       → dense (gefiltert, vetted Telegram) → bge-rerank → tier_boost → sortiert
   │
   ├── defensiver Guard: validate_lane(analysis, "analysis"), validate_lane(realtime, "realtime")
   │       → Treffer, die die Lane-Invariante verletzen, werden verworfen + geloggt
   │
   └── merge: final = analyse[:4] + [bestes Realtime] (falls qualifiziert), sonst analyse[:5]
              telegram_count ≤ 1, Realtime-Item am Ende, als source_class="realtime" markiert
```

- **Policy lebt im Tool** (`qdrant_search`), nicht im generischen `search()`. So bleibt der Retriever ein wiederverwendbares Primitive; die Korpus-Regeln sind an einer Stelle (`corpus_policy.py`).
- **Zwei getrennte Qdrant-Queries** (nicht ein gemischter `should`-Pool): nur so lässt sich „Realtime verdrängt Analyse nicht" deterministisch über einen Slot-Cap garantieren, und nur so ist die Realtime-Lane separat mit höherem Threshold abfragbar.

## 5. Komponenten

### 5.1 `rag/corpus_policy.py` (neu) — die einzige Policy-Stelle

```python
# Analyse-Lane: Prosa-Analyse. NLM via notebook_id (raw source="unknown"!).
ANALYSIS_SOURCES: frozenset[str] = frozenset({"rss"})

# Realtime-Lane: vetted Telegram. Realtime-LEADS, keine verifizierten
# Primärquellen. rybar (staatsnah) bewusst ausgeschlossen.
TELEGRAM_ALLOWLIST: frozenset[str] = frozenset({
    "wartranslated", "OSINTdefender", "liveuamap", "AuroraIntel", "DeepStateEN",
})

def analysis_filter() -> dict:
    """Qdrant-Filter: source==rss ODER notebook_id vorhanden (NLM)."""
    return {"should": [
        {"key": "source", "match": {"value": "rss"}},
        {"must_not": [{"is_empty": {"key": "notebook_id"}}]},   # NLM-Punkte
    ]}  # min_should=1 (Default)

def realtime_filter() -> dict:
    """Qdrant-Filter: vetted Telegram-Kanäle."""
    return {"must": [
        {"key": "source", "match": {"value": "telegram"}},
        {"key": "telegram_channel", "match": {"any": sorted(TELEGRAM_ALLOWLIST)}},
    ]}

def validate_lane(results: list[dict], lane: str) -> list[dict]:
    """Zweite Schranke am Output (AC-2). Behält nur Treffer, die die
    Lane-Invariante erfüllen; verworfene werden strukturiert geloggt.
      analysis: source=="rss" ODER notebook_id vorhanden+nicht-leer
      realtime: source=="telegram" UND telegram_channel ∈ TELEGRAM_ALLOWLIST
    Begründung: Qdrant-Filter ist die erste Schranke; Index-Lag oder ein
    Filter-Bug darf AC-2 nicht brechen."""
```

- Whitelist = **sicher by default**: jeder nicht genannte Source-Typ (`gdelt`, `gdelt_gkg`, `firms`, `eonet`, `usgs`, `gdacs`, `noaa_nhc`, `adsb.fi`, `hapi`, `ofac`, `ucdp`, `portwatch`) ist automatisch draußen, bis explizit freigegeben.
- NLM-Diskriminator ist `notebook_id`-Präsenz via `must_not IsEmpty`, **nicht** `source=="unknown"` (genuin unbekannter Legacy-Müll trägt ebenfalls `"unknown"`, hat aber kein `notebook_id`). Qdrant: `IsEmpty` trifft fehlende, `null`- und leere Werte; `must_not IsEmpty` ⇒ Feld vorhanden und nicht-leer.

Außerdem in diesem Modul:

```python
TIER_BOOST_LAMBDA: float = 0.2     # konfigurierbar (settings)
ANALYSIS_POOL: int = 40            # Overfetch Analyse-Lane
REALTIME_POOL: int = 20            # Overfetch Realtime-Lane
RT_SCORE_THRESHOLD: float = 0.45   # messbarer Default, nicht dauerhaft kalibriert
FINAL_K: int = 5
TELEGRAM_MAX: int = 1

def credibility_of(payload: dict) -> float:
    """Reliability für ein rohes Result-Payload. Wiederverwendet die
    Provenance-Ableitung aus evidence.py + credibility.credibility_score.
    NLM(notebook_id)→notebooklm(0.60); rss→feed_name-Override oder 0.60; …"""

def apply_tier_boost(results: list[dict]) -> list[dict]:
    """final = (1-λ)·rerank_norm + λ·credibility, stabil sortiert. Siehe §6.
    Geeignet als post_rerank-Callback für enhanced_search."""

def merge_lanes(analysis: list[dict], realtime: list[dict]) -> list[dict]:
    """≤1 Realtime-Item, am Ende, markiert. Siehe §5.3."""
```

### 5.2 `rag/retriever.py` — `query_filter` durchreichen, Overfetch, neutraler `post_rerank`-Hook

- `search(..., query_filter: dict | None = None)`: wenn gesetzt, wird `query_filter` mit etwaigen `region`/`source`-`must`-Bedingungen zu **einem** Qdrant-`filter` gemerged (kombinierte `must`/`should`). Default `None` ⇒ Verhalten unverändert (bestehende Tests bleiben grün).
- `enhanced_search(..., query_filter=None, pool=None, post_rerank: Callable[[list[dict]], list[dict]] | None = None)`:
  - Overfetch = `pool or (limit*2)`; reicht `query_filter` an `search()` durch.
  - Nach dem Rerank wird **nur falls `post_rerank` gesetzt ist** `results = post_rerank(results)` angewandt, dann auf `limit` geschnitten.
  - **Default `post_rerank=None` ⇒ das Primitive bleibt neutral** (kein Tier-Boost). Nur `qdrant_search` übergibt `apply_tier_boost`. Damit leckt keine Korpus-Policy in den generischen Retriever (Parnas).
- Reranker liefert weiterhin `rerank_score` je Doc; der Boost greift im Callback **nach** dem Rerank auf dem Pool, dann Top-`limit`.

### 5.3 `agents/tools/qdrant_search.py` — Zwei-Lane-Merge mit Output-Guard

```
analysis = enhanced_search(query, query_filter=analysis_filter(),
                           limit=FINAL_K, pool=ANALYSIS_POOL,
                           post_rerank=apply_tier_boost)
realtime = enhanced_search(query, query_filter=realtime_filter(),
                           limit=1, pool=REALTIME_POOL,
                           score_threshold=RT_SCORE_THRESHOLD,
                           post_rerank=apply_tier_boost)

analysis = validate_lane(analysis, "analysis")   # zweite Schranke (AC-2)
realtime = validate_lane(realtime, "realtime")
final = merge_lanes(analysis, realtime)
```

`merge_lanes`:
- `final = analysis[:FINAL_K]` (Analyse dominiert, oben).
- Falls `realtime` non-empty (das Top-Item hat bereits `RT_SCORE_THRESHOLD` im Dense-Schritt passiert): nimm `realtime[0]`, markiere `source_class="realtime"`, setze `final = analysis[:FINAL_K-1] + [realtime[0]]` (Realtime an Position 5, verdrängt höchstens **einen** Analyse-Slot).
- Andernfalls bleiben 5 Analyse-Resultate.
- Evidence-Items: Analyse → `source_class="analysis"`, Realtime → `source_class="realtime"`. Die `[EVIDENCE]`-Zeile eines Realtime-Items kennzeichnet es als **Realtime-Lead, keine verifizierte Primärquelle**, damit Synthesis es entsprechend gewichtet.

### 5.4 `rag/reranker.py` — RSS-Teaser nutzen (verpflichtend in diesem Slice)

`texts = [d.get("content") or d.get("summary") or d.get("title", "") for d in documents]`
(statt `content or title`). NLM hat `content`, RSS hat `summary`, GKG hätte nur `title` — letzteres ist durch den Filter ohnehin draußen.

### 5.5 `rag/credibility.py` — Provider-Overrides (an echte `feed_name`-Keys)

RSS-`provider` = `normalize_provider(feed_name.lower())`. Daher müssen Overrides
auf die **Label-Keys** der Live-Feeds zielen, nicht auf Domains. Die Registry
bildet **Reliability** ab, nicht Dokumentgattung — Wire-Services werden daher
ebenfalls geboostet. Vorgeschlagene Tiers (konfigurierbar, Reviewer darf tunen):

| Score | `provider`-Key (aus `feed_name`) | Begründung |
|---|---|---|
| 0.85 | `bellingcat` | OSINT-Verifikation, methodisch belegt |
| 0.85 | `reuters (google)`, `ap news (google)` | internationale Wire, starke redaktionelle Standards |
| 0.82 | `rand corporation`, `csis`, `rusi commentary`, `rusi publications`, `sipri`, `swp publications (de)`, `swp publications (en)`, `atlantic council`, `brookings`, `crisis group`, `war on the rocks`, `arms control association` | etablierte Think-Tanks / Fach-Analyse |
| 0.80 | `bbc world`, `eu parliament security and defence`, `euvsdisinfo` | öffentl.-rechtl. Wire / institutionelle Primärquelle / EEAS-Disinfo |

- `al jazeera`, `france24` (RSS) sind ein separates Reliability-Urteil und bleiben **Follow-up** (nicht in diesem Slice geboostet → rss-Baseline 0.60).
- Jeder neue Override braucht (wie im Modul-Kontrakt) einen Test. `credibility_score` bleibt fail-fast bei unbekanntem `source_type`.

### 5.6 Qdrant-Payload-Indizes — explizites idempotentes Migrationsskript

- **Migrationsskript** `services/intelligence/scripts/ensure_payload_indexes.py` (idempotent, `wait=true`) legt Keyword-Indizes auf `source`, `telegram_channel`, `notebook_id` an. Bereits vorhandene Indizes werden ignoriert.
- **Service-Startup mutiert NICHT.** Die bestehende `validate_collection_schema`-Preflight wird erweitert: sie **prüft** nur, ob die drei Indizes existieren, und **warnt** strukturiert, falls nicht (kein stiller Index-Build im Read-Pfad).
- **HNSW-Rebuild-Hinweis:** Qdrant dokumentiert, dass nachträglich (nach Befüllung) angelegte Payload-Indizes einen HNSW-Rebuild brauchen, damit filter-aware Links vollständig genutzt werden. Das Migrationsskript ist daher **einmalig vor** dem Verlassen auf gefilterte Suche auszuführen; bis dahin funktioniert der Filter korrekt, nur langsamer (Full-Scan).

## 6. Scoring

Pro Lane, **nach** dem Rerank, über den Kandidatenpool:

1. `r_raw = rerank_score` je Doc. Fehlt der Key (Rerank deaktiviert/Fallback), nutze ersatzweise das Dense-`score`-Feld als `r_raw`.
2. Min-Max-Normalisierung auf [0,1]: `r_norm = (r_raw - min) / (max - min)`.
   **Sonderfall `max == min`** (alle Scores gleich / Pool=1): `r_norm = 1.0` für alle (Relevanz indifferent ⇒ Reputation entscheidet allein; kein ZeroDivision).
3. `final = (1 - λ)·r_norm + λ·credibility_of(payload)`, `λ = TIER_BOOST_LAMBDA = 0.2`.
4. Stabil absteigend nach `final` sortieren, Top-`limit`.
5. **Logging** (für Messung & Debug): je Doc `rerank_score` (raw), `r_norm`, `credibility`, `final`, `provider`, `source` strukturiert loggen.

Effekt: Ein Think-Tank (cred 0.82) überholt eine **knapp** relevantere Lokalquelle
(cred 0.60), aber ein großer Relevanz-Gap wird nicht gekippt (λ klein).

## 7. Datenfluss

```
ReAct/Munin → qdrant_search(query)
  ├─ embed(query) [TEI]
  ├─ Analyse-Lane:  Qdrant search (analysis_filter, pool=40, thr=0.3) → bge-rerank → tier_boost
  ├─ Realtime-Lane: Qdrant search (realtime_filter, pool=20, thr=0.45) → bge-rerank → tier_boost
  ├─ validate_lane(analysis) / validate_lane(realtime)   # Output-Guard
  ├─ merge_lanes → ≤5 Items (≤1 realtime, markiert)
  ├─ to_evidence_item(...) je Item (+ source_class)
  └─ Graph-Context (Neo4j) unverändert angehängt
```

## 8. Fehlerbehandlung / Degradation

- **Realtime-Lane leer / Fehler:** Briefing nutzt 5 Analyse-Resultate; kein harter Fehler.
- **Reranker-Ausfall:** Der `rerank`-Fallback liefert die Dense-Reihenfolge ohne `rerank_score`. `apply_tier_boost` normalisiert dann die **Dense-`score`-Werte** (§6 Schritt 1) und blendet sie mit der Reputation. Reputation entscheidet **allein** nur im `max==min`-Fall (Score-Gleichstand) oder bei Poolgröße 1. Geloggt.
- **Output-Guard verwirft alles:** sollte `validate_lane` eine Lane leeren (Filter-/Index-Anomalie), verhält sich das wie eine leere Lane; AC-2 bleibt gewahrt (lieber kein Treffer als ein ungeprüfter).
- **Index fehlt:** Filter funktioniert weiterhin (langsamer Full-Scan); Startup warnt, Migrationsskript legt nach.
- **Leerer Analyse-Treffer:** unverändertes „No relevant documents found".

## 9. Tests (TDD — Red zuerst)

`services/intelligence/tests/`:
1. `test_corpus_policy.py`
   - `analysis_filter()`/`realtime_filter()` Shape (source==rss ODER `must_not IsEmpty(notebook_id)`; telegram + allowlist; rybar **nicht** in Allowlist).
   - `validate_lane`: verwirft Cross-Lane-Verletzer (z.B. ein `gdelt_gkg`- oder ungeprüftes-Telegram-Payload, das fälschlich durchrutscht) und **loggt** das Verwerfen; behält valide Treffer.
   - `apply_tier_boost`: (a) Near-Tie kippt zugunsten höherer credibility; (b) großer Relevanz-Gap kippt **nicht**; (c) `max==min`-Sonderfall sortiert rein nach credibility, kein ZeroDivision; (d) raw+norm Scores werden geloggt; (e) ohne `rerank_score` werden Dense-`score` normalisiert.
   - `merge_lanes`: ≤1 Realtime, am Ende, `source_class`-Markierung; leeres Realtime ⇒ 5 Analyse; Realtime verdrängt genau einen Analyse-Slot.
   - `credibility_of`: NLM(notebook_id)→0.60; `feed_name="CSIS"`→0.82; `feed_name="Reuters (Google)"`→0.85; Lokal-rss→0.60.
2. `test_credibility.py` (erweitert): je neuer Override (Think-Tanks + Wire-Aliase) ein Assert; unbekannter `source_type` weiterhin fail-fast.
3. `test_qdrant_search_tool.py` (erweitert): gemockter `enhanced_search` mit gemischten Quellen ⇒ Tool-Output enthält **nie** `gdelt_gkg`/`firms`/ungeprüftes Telegram; ≤1 Realtime-Item; Realtime als Lead markiert.
4. `test_hybrid_retriever.py` (erweitert): `query_filter` wird an Qdrant-Body durchgereicht; `pool` steuert Overfetch; **`post_rerank=None` ⇒ kein Boost (neutrales Primitive)**; `post_rerank` gesetzt ⇒ angewandt.
5. `test_reranker.py`: Textauswahl `content > summary > title`.
6. `test_ensure_payload_indexes.py`: Skript ist idempotent (zweiter Lauf no-op) und nutzt `wait=true`; Startup-Validierung warnt bei fehlendem Index, mutiert nicht.

## 10. Messung (Acceptance-relevant)

Mess-Harness (`services/intelligence/scripts/measure_corpus_scoping.py`, read-only,
gegen Live-Qdrant) mit **sechs festen Queries**:
`"Bundeswehr Beschaffung"`, `"Russia shadow fleet"`, `"Taiwan strait tensions"`,
`"NATO eastern flank posture"`, `"Iran proxy escalation"`, `"Sahel coup instability"`.

Pro Query: Top-5 **vorher** (ungescopt) vs. **nachher** (Policy aktiv), je
`source`/`provider`/`final`-Score (raw+norm). Ergebnis als Tabelle in die PR-
Beschreibung. Kein automatisches Pass/Fail im CI (Live-Daten-abhängig) — die
Tabelle belegt die Acceptance Criteria manuell.

## 11. Acceptance Criteria

- **AC-1:** Die sechs festen Queries holen RSS/NLM-Analyse **sichtbar nach oben** (Top-5 vorher/nachher dokumentiert; Think-Tanks/NLM ersetzen GDELT-/Sensor-Einträge).
- **AC-2:** Im finalen Briefing-Evidence-Set erscheint **kein** `gdelt_gkg`, **kein** `firms` und **kein** ungeprüftes Telegram (nur Allowlist-Kanäle, rybar nie) — durchgesetzt von **zwei** Schranken (Qdrant-Filter + `validate_lane`-Output-Guard).
- **AC-3:** Höchstens **ein** Realtime-Telegram-Item im finalen Top-5, klar als Realtime-Lead (keine verifizierte Primärquelle) markiert.
- **AC-4:** Innerhalb der Analyse-Lane überholt ein Think-Tank-/Wire-Provider eine knapp relevantere Lokalquelle; ein großer Relevanz-Gap bleibt erhalten (λ=0.2).
- **AC-5:** Alle bestehenden Intelligence-Tests bleiben grün; neue Tests decken §9 ab.

## 12. Out of Scope / Follow-ups

- **NLM-Hygiene:** `source="unknown"`→`"nlm"` via idempotentem `set_payload` (kein Re-Embed) + Writer-Default `source_name="nlm"` fixen. Danach kann der Analyse-Filter `notebook_id`-OR durch `source∈{rss,nlm}` ersetzen.
- **Structured-Evidence-Lane:** `ucdp`, `ofac`, `portwatch`, `hapi` als eigene Lane mit dataset-Tiering (braucht Erweiterung von `evidence._legacy_provenance`, das diese aktuell als `gdelt` bucket­et) oder Graph-Abfrage.
- **Wire-Aliase Al Jazeera / France24:** separate Reliability-Einschätzung, danach ggf. Override.
- **P2:** Think-Tank-Volltext (crawl4ai/docling) statt RSS-Teaser; Podcast-Transkripte (Sicherheitshalber, Streitkräfte & Strategien — Feeds im Memory `reference_security_podcasts`).
- **P5:** GKG physisch in eigene Collection.

## 13. Referenzen

- Qdrant Filtering (IsEmpty trifft fehlende/null/leere Werte): https://qdrant.tech/documentation/concepts/filtering/
- Qdrant Indexing (gefilterte Felder indexieren; HNSW-Rebuild bei nachträglichem Payload-Index): https://qdrant.tech/documentation/manage-data/indexing/
- Memory: `project_rag_corpus_quality` (Tracker #1), `reference_security_podcasts` (P2-Feeds), `reference_gdelt_payload_schema`.
- Betroffene Dateien: `agents/tools/qdrant_search.py`, `rag/retriever.py`, `rag/reranker.py`, `rag/credibility.py`, `rag/evidence.py`, neu `rag/corpus_policy.py`, neu `scripts/ensure_payload_indexes.py`, neu `scripts/measure_corpus_scoping.py`.
