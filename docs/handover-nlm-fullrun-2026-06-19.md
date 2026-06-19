# Arbeitsübergabe — NLM 81-NB Voll-Lauf + data-ingestion Ingest-Guard

**Für:** eine frische Claude-Instanz, die (A) den data-ingestion-Ingest-Guard aktiviert und
(B) den NotebookLM-Voll-Lauf (81 Notebooks) fährt.
**Stand:** 2026-06-19, nach Merge von PR #63 (NLM-Härtung) + #64 (Corpus-Content-Gate).
**Vorgeschichte:** `docs/nlm-smoke-2026-06-19.md` (Smoke-Test, der Runbook), `docs/corpus-cleanup-2026-06-19.md`.
Memory: `project_nlm_triage`, `reference_notebooklm_access`, `project_rag_corpus_quality`.

---

## 0. TL;DR
- Beide Features sind in `origin/main` (`a270c8c`) und CI-grün gemerged. **intelligence ist deployed** (Read-Path-Content-Gate live). **data-ingestion-Guard ist NOCH NICHT aktiv** — er läuft host-seitig und greift erst, wenn der Host-Repo-Checkout auf `main` steht (Operator-Schritt, s. Task A).
- Der 81-NB-Lauf ist **vorbereitet, nicht gefahren**: die Auswahl steht (`ingest_now.json`, 81 IDs), die Pipeline ist im 5-NB-Smoke E2E bewiesen. Der Voll-Lauf ist GPU-swap-schwer (Voxtral-Transkription ~Stunden) → bewusst der neuen Instanz übergeben.

## 1. Wo wir stehen
| Komponente | Status |
|---|---|
| PR #63 NLM-Härtung | MERGED `9278143` (audioop-lts, Spark-Timeout-Split, strict response_format, lenient skip, max_tokens=8000, v3-Prompt-Fix) |
| PR #64 Corpus-Gate | MERGED `38c6f43` (content_quality-Predicate, Read-Path-validate_lane-Gate, fulltext-Ingest-Guard) |
| intelligence Deploy | ✅ LIVE — `osint-intelligence` neu gebaut+recreated; `corpus_content_dropped base64_heavy` feuert in Prod (verifiziert) |
| Essay-Re-Test | ✅ clean-E hebt 9B 73→81 / Opus 83→89 Punkte; Junk-Citation eliminiert |
| Smoke-State-DB | 5 NB voll ingested (Energy/Pentagon/Drone/F127/Hybrid) — sie sind Teil der 81 und werden im Voll-Lauf als `completed` übersprungen |

---

## 2. Task A — Ingest-Guard aktivieren (Operator-Schritt, kein Container-Rebuild)

**Wie es läuft:** Fulltext-Enrichment ist KEIN Container-Job. Ein Host-systemd-Timer
(`ops/fulltext-enrich/odin-fulltext-enrich.timer` → `fulltext_enrich.sh`) ruft stündlich
`uv run python -c "...FulltextCollector().collect()"` **aus dem Host-Working-Tree**
`/home/deadpool-ultra/ODIN/OSINT/services/data-ingestion` + Host-venv. Der Guard (#64) liegt
in `feeds/fulltext_collector.py` + `feeds/content_quality.py`.

**Aktivierung:** der Guard greift, sobald **der Host-Repo-Checkout auf `main`** (oder einem
Branch mit #64) steht, wenn der Timer feuert. Aktuell wechselt der Owner ständig den Branch
(zuletzt `fix/frontend-quality-cleanups`) → Guard inaktiv.

**Optionen (Owner-Entscheidung, kein systemctl-Zugriff in dieser Umgebung):**
1. Host-Repo auf `main` halten/mergen für Ingestion-Phasen — simpel, aber koppelt an Dev-Branch.
2. **Sauber (empfohlen):** Timer auf einen **dedizierten `main`-Worktree** mit eigenem venv
   zeigen lassen (ExecStart-Pfad ändern, `systemctl daemon-reload`). Entkoppelt Ops vom Dev-Checkout.
   Das ist auch der TASKS.md-Follow-up „container-native fulltext scheduler".

**Verify nach Aktivierung:** `journalctl -u odin-fulltext-enrich --since '1h ago'` →
beim nächsten Lauf erscheinen `fulltext_chunk_skipped`/`fulltext_all_chunks_junk`-Logs bei
base64/Junk-Seiten (z.B. swp-WebMonitor). Kein Container-Restart nötig.

---

## 3. Task B — 81-NB Voll-Lauf (Hauptaufgabe)

### 3.1 Prereqs
- **Code+venv aus `main`, NICHT aus dem Owner-Checkout** (der ist volatil). Sauber:
  ```bash
  git -C /home/deadpool-ultra/ODIN/OSINT worktree add /tmp/odin-nlm-run origin/main
  cd /tmp/odin-nlm-run/services/data-ingestion
  uv sync --extra notebooklm        # installiert notebooklm-py + audioop-lts (jetzt in pyproject!)
  uv run playwright install chromium # Chromium ist gecacht (~/.cache/ms-playwright)
  ```
  `nlm_data_dir` ist absolut (`/home/deadpool-ultra/ODIN/odin-data/notebooklm`) → State-DB +
  Exporte werden geteilt, egal aus welchem Worktree. Worktree liefert nur Code+venv.
- **Code-Provenienz festhalten (PFLICHT, VOR dem Lauf)** — damit später eindeutig ist, welche
  Codeversion den Voll-Lauf gefahren hat, beides ins Run-Log/journald schreiben:
  ```bash
  cd /tmp/odin-nlm-run && git rev-parse HEAD                    # exakte Commit-SHA (sollte origin/main sein)
  cd services/data-ingestion && uv run odin-ingest-nlm --help   # CLI erreichbar + verfügbare Subcommands
  ```
- **NotebookLM-Session:** `~/.notebooklm/storage_state.json` (vom 18.06.). Google-Sessions
  laufen ab → falls `notebooks.list()` `AuthError` wirft: **`python -m notebooklm login` im
  ECHTEN Terminal** (braucht TTY; `!`-Prefix scheitert — s. `reference_notebooklm_access`).
- **GPU:** transcribe braucht Voxtral auf der 5090 (Modus E). extract läuft auf dem **Spark**
  (`ingestion_vllm_url=192.168.178.39:8000`, kein 5090-Swap). Voxtral ist 5090-only (kein Spark-Offload).

### 3.2 Die Auswahl
`/home/deadpool-ultra/ODIN/odin-data/notebooklm/ingest_now.json` = **81 NB** (77 Run1 + 4 Run2P1),
je `{idx,id,title,run}`. 5 davon (Energy/Pentagon/Drone/F127/Hybrid) sind schon `completed` →
Pipeline überspringt sie automatisch.

### 3.3 Batch-Export-Mechanik
Es gibt KEIN Subset-„export alle". Zwei Wege:
- **Bewährt (Smoke):** loop `uv run odin-ingest-nlm export --id <ID>` über die 81 IDs aus
  ingest_now.json. ~81 Browser-Sessions (~20+ min), aber robust + idempotent (atomic download).
- **Optional/sauberer (TDD-Task, NICHT gebaut):** `export_all(data_dir, notebook_ids: list|None)`
  generalisieren (aktuell nur `notebook_id: str|None`, filtert `[nb for nb in notebooks if nb.id==id]`)
  + CLI-Flag `--ids-file ingest_now.json` → eine Browser-Session für alle 81. Mit Test
  (`tests/test_nlm_export.py`-Muster). Empfehlung: nur bauen, wenn der Loop zu fragil ist.

### 3.4 Ausführungs-Sequenz (Runbook aus dem Smoke, bewährt)
> Interaktiver Stack ist NUR im Transkriptions-Fenster offline. extract/ingest brauchen die 5090 nicht.
```bash
cd /tmp/odin-nlm-run/services/data-ingestion   # main-worktree venv

# Phase 1 — export (GPU-frei): loop über die 81 IDs
python3 -c "import json;[print(x['id']) for x in json.load(open('/home/deadpool-ultra/ODIN/odin-data/notebooklm/ingest_now.json'))]" \
  | while read id; do uv run odin-ingest-nlm export --id "$id"; done

# Phase 2 — transcribe (Voxtral, 5090-Swap):
#   Vorab: keine laufende ReAct/Intelligence-Query (curl :8000/metrics → num_requests_running==0)
docker compose -f /home/deadpool-ultra/ODIN/OSINT/docker-compose.yml stop vllm-9b
cd /home/deadpool-ultra/ODIN/OSINT && ./odin.sh nlm up        # Voxtral hoch (~21GB), warte :8010/v1/models==200
cd /tmp/odin-nlm-run/services/data-ingestion && uv run odin-ingest-nlm transcribe   # STUNDEN (~76 Podcasts)
cd /home/deadpool-ultra/ODIN/OSINT && ./odin.sh nlm down && docker compose start vllm-9b  # interaktiv zurück

# Phase 3 — extract (Spark, kein Swap; 600s-Timeout + structured output + lenient skip greifen)
cd /tmp/odin-nlm-run/services/data-ingestion && uv run odin-ingest-nlm extract

# Phase 4 — ingest (Neo4j + Qdrant, TEI-embed nötig)
uv run odin-ingest-nlm ingest
uv run odin-ingest-nlm status   # alle 81 sollten export/transcribe/extract/ingest = completed
```
**Spark-Contention:** der Spark teilt sich mit der live RSS-Pipeline → extract dauert ~160s/NB.
Der 600s-Timeout (PR #63) deckt das ab. RSS NICHT stoppen (Owner-Entscheidung; der Safety-Classifier
blockiert `docker compose stop data-ingestion-spark` ohnehin).

### 3.5 Verifikation (wie im Smoke)
Qdrant-Points + Neo4j-Document/EXTRACTED_FROM je notebook_id zählen
(`scripts_verify_ingest.py` als Muster; Collection `odin_intel`). Erwartung: pro NB
1 Document-Node + N EXTRACTED_FROM-Kanten + N Qdrant-Points (N = #Claims).

### 3.6 Gotchas
- **audioop-lts** muss im venv sein (py3.13) — `uv sync --extra notebooklm` zieht es jetzt aus pyproject.
- **GPU-Swap nimmt ReAct/Intelligence offline** (Transkriptions-Fenster). Vorher idle prüfen.
- **`extract` schreibt nach `odin_intel`** (nicht odin_methods — das ist Slice „Run 3", separat, braucht erst die konfigurierbare Ziel-Collection; NICHT Teil dieses Laufs).
- **temperature=0.1** in der Extraktion → Out-of-Enum-Relations werden lenient geskippt+geloggt
  (`nlm_extract_skipped_summary`) — das ist das Signal für die spätere Relation-Enum-Erweiterung.
- Backup vor Prod-Writes erwägen (Neo4j-Dump), wie beim SUV-Track2-Lauf.

---

## 4. Offene Follow-ups (kein Blocker)
- **Tier-2 Corpus-Delete:** Dry-Run liegt bereit — `cleanup_candidates.json` (404 IDs:
  base64_heavy 40, too_few_words 335 = meist Google-News-`<a href>`-Stubs, too_short 24, low_prose 5).
  Read-Path schließt sie schon aus → Löschen ist nur Speicher-Hygiene, **backup-first**. Script:
  `scripts_corpus_cleanup_dryrun.py` (löscht nichts; ein echtes Delete-Script fehlt noch).
- **Tier-3 Collection-Split:** ADR in `docs/corpus-cleanup-2026-06-19.md` (odin_intel / odin_events /
  odin_geo_signals) — 621k GDELT/FIRMS-Bloat raus aus odin_intel. Geparkt.
- **SUV Track 2 Slice 2** + **Relation-Enum-Erweiterung** (nach Sammeln realer skipped types).

## 5. Key Learnings / Fallstricke (teuer gelernt)
- **content vs summary:** bare `rss` legt Prosa unter `summary` ab, NICHT `content`. Wer nur
  `content` liest, hält 14k valide Punkte für „leer" (mein erster Survey-Fehler) UND ein Read-Gate,
  das nur `content` prüft, droppt ~24 Wire/Gov-Feeds (B1-Bug im Review gefangen). Immer den
  `content→summary→description→title`-Fallback nutzen (= `rag.evidence._excerpt`).
- **„funktioniert nur für ein Subset / nur in incognito"** → Browser-Cache von bare-URL-JSON prüfen
  (`project_frontend_cache_headers`).
- **Branch-Isolation:** Feature-Commits mit expliziten Pfaden stagen; nie `git add -A` bei fremdem
  WIP im Tree. Deploy isoliert via `git worktree` (Owner-Checkout nie anfassen).
- **Smoke zuerst:** der 5-NB-Smoke fand audioop, Timeout, EVENT-Enum, max_tokens-Truncation —
  alle vor dem Voll-Lauf. NICHT die 81 ohne Smoke fahren.

## 6. Artefakt- & Befehls-Referenz
- **Auswahl/Triage:** `odin-data/notebooklm/{ingest_now.json, notebook_runs.json, notebook_triage.json, notebook_index.json}`
- **Eval:** `odin-data/notebooklm/eval_*.{json,md}` (Essays, Evidenz, clean vs junk)
- **Cleanup:** `odin-data/notebooklm/cleanup_candidates.json`
- **Docs:** `docs/nlm-smoke-2026-06-19.md` (Runbook), `docs/corpus-cleanup-2026-06-19.md`, dieses Doc
- **Wegwerf-Scripts** (services/data-ingestion, untracked, als Muster): `scripts_list_notebooks.py`,
  `scripts_verify_ingest.py`, `scripts_corpus_survey.py`, `scripts_corpus_cleanup_dryrun.py`,
  `scripts_build_eval_evidence*.py`, `scripts_essay_9b*.py`, `scripts_diag_*.py`
- **CLI:** `odin-ingest-nlm {status|export --id|transcribe|extract|ingest}` (aus main-venv)
- **GPU:** `./odin.sh nlm up|down` (Voxtral), `docker compose stop/start vllm-9b`, `./odin.sh smoke`
