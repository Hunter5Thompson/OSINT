# ODIN/WorldView — Task Registry

Stand: 10.10.2026. Dieses Registry ist die maßgebliche Status- und Stackübersicht.
Die [technischen Briefings](docs/tasks/specifications.md) bewahren alle TASK-001–123-
Aufträge; [historische Ergebnisse](docs/tasks/history-2026-10-10.md) und einzelne
Reviews enthalten die Prüfbelege. Neue Sourcechecks schließen Merge, Release,
Datenverifikation oder menschliche Abnahme nicht automatisch.

## Repo-Goal und HN

Gesamtmatrix: [Finding-/Abnahmegates](docs/reviews/2026-10-10-goal-gates.md).
Menschliche Prüfung: [unbewertete Abnahmeunterlagen](docs/operations/goal-acceptance-2026-10-10.md).

G01–G08 bleiben vollständig verbindlich. Eigener Sourceworktree:
`feat/odin-release-provenance-20261009`, Übernahmebasis `e8603c6`.
Writer01a12412-a9fe-7052-93e0-ba88db75c740 hat alle212 übernommenen Sourcepfade
scoped committet und führt die tatsächlichen Integrationsgates aus.
Die früheren Policyfehler gehören zum beendeten Vorgänger; aktueller Index-,
Remote-, Docker- und Browserzugriff funktionieren im regulären Profil.
GitHub frisch bestätigt B05/PR138MERGED und Main `a47da45`, keinen GoalPR.
Produktivrelease bleibt offen. Die [Gate-Matrix](docs/reviews/2026-10-10-goal-gates.md)
trennt aktuelle lokale Ergebnisse, finale Prüfungen und den dokumentierten
unbeabsichtigten Redis-Testzugriff; keine produktive Rücksetzung ohne Freigabe.

| Bündel | Source-/Entscheidungsstand | Prüfbeleg / verbleibende Grenze |
|---|---|---|
| S01–S03, I01/I02/I04, B01–B04 | historisch gemergt | [HN-Vertrag](docs/plans/herz-und-nieren-2026/README.md); aktuelle Liveprovenienz offen |
| B05 D01/D02/D10 | historisch gemergt PR #138 | [Abnahme](docs/reviews/2026-10-06-hn-b05-acceptance.md); heutiger Live-/Remoteabgleich offen |
| B06 A03/D06, X01/X02 | Source vorbereitet; X01 Entscheidung offen, X02 Abdeckung sichtbar | [Review](docs/reviews/2026-10-10-b06-source-checkpoint.md) |
| B07 A07/A08 | Source und Legacykonzept committet;15 echte A08-Fälle PASS | [Review](docs/reviews/2026-10-10-b07-identity-checkpoint.md); finaler Head/PR/historische Migration separat |
| B08 L01/L02/L03 | Source committet; echter LangGraph-Fünfturnvertrag und732 Fulltests PASS | [Review](docs/reviews/2026-10-10-b08-intelligence-checkpoint.md); Modell-/finalHead-/PR-Abnahme separat |
| B09 S04/L04/L05 | Source vorbereitet | [Review](docs/reviews/2026-10-10-b09-source-checkpoint.md); echte Store-/Modellabnahme offen |
| B10 L06/D09 | Source vorbereitet | [Review](docs/reviews/2026-10-10-b10-report-admin-checkpoint.md); Servicegesamtgate offen |
| B11 U01–U04 | Source vorbereitet | [Review](docs/reviews/2026-10-10-b11-ui-checkpoint.md); Browser/native GPU/Human offen |
| B12 U06–U08, X03 | Source vorbereitet; X03 Entscheidung offen | [Review](docs/reviews/2026-10-10-b12-async-ui-checkpoint.md); Browser/Human offen |
| B13 D07/A02/U05, X04/GP | Sourcekette100651 committet; echter Built-Canvaspick/Orbit/Abdeckung/Remount PASS; DEC-005 | [Parser](docs/reviews/2026-10-10-d07-text-reader-checkpoint.md), [Clock/GP](docs/reviews/2026-10-10-gp-clock-producer-checkpoint.md); finale Gesamtlauf-/Image-/Livegates separat |
| G06 ANA-01/R01 | Korpus, Metadaten und Dry-run-Vertrag vorbereitet | [Review](docs/reviews/2026-10-10-g06-analysis-checkpoint.md); Modell/Originale/Human offen, keine Voll-Faktenfreigabe |
| G07 TASK-114/UI-01 | Dichte/LOD/Aggregation/Lifecycle lokal geprüft | [Review](docs/reviews/2026-10-10-g07-density-checkpoint.md); Live-/Browser-/native GPU-/Human-Abnahme offen |
| G08 Wartbarkeit/Hygiene | Module zerlegt,18 Worktrees/Live-Mounts geschützt inventarisiert; gezielter Lockfix/Audit0 | [Review](docs/reviews/2026-10-10-g08-maintainability-checkpoint.md); finaler Head/CI und fremde Eigentümerschaft separat |

## TECH STACK — CANONICAL VALUES

Versionsquelle sind die fünf tracked Deployment-Lockfiles und die gewählten
Compose-/Releaseinputs. Diese Tabelle beschreibt Sourceverträge, keinen heute
gemessenen laufenden Stack. [AGENTS.md](AGENTS.md), [Betriebsstatus](docs/CONTAINER-STATUS.md)
und [Releasevertrag](docs/operations/release.md) bestimmen die Start-/Rolloutregeln.

| Bereich | Sourcevertrag |
|---|---|
| Python / Frontend | uv 0.10.0, `uv sync --locked`; Tests `--all-extras`; Node 22, `npm ci` |
| Interactive | lokale Qwen3.5-9B über OpenAI-kompatible API; Host8000 |
| Ingestion lokal | ein lokales LLM; Compose-vLLM27B ist laut Betriebsdokument gebrochen; dokumentierter llama.cpp/Qwen3.5-27B-GGUF-Q6_K-Pfad |
| Interactive-Spark | 9B lokal plus Ingestion auf separater DGX Spark; kein zweites lokales LLM |
| Embedding / Rerank | TEI-kompatibel 8001/8002,1024 Dimensionen; Blackwell-TEI `120-1.9.3`; Modelle/Inputs im gewählten Manifest prüfen |
| Qdrant / Neo4j / Redis |6333/6334;7474/7687;6379; Collectiongeneration und Schema separat prüfen |
| Backend / Intelligence / Frontend | Backend Host 8080→Container8000; Intelligence8003; Vite5173 |
| Frontend | React 19/Cesium 1.142.0; satellite.js 7.1.0 exact; aktuelle Semverauflösung im package-lock |
| Satelliten | LegacyTLE plus additive GP/OMM-v1; Ingestiondefault `tle`, [DEC-005](decisions.md#dec-005-2026-10-10--versionierte-gp-orbitdaten-mit-tle-kompatibilität) |
| Release | digest-gepinnte Appimages, baked Revision; keine veränderlichen Source-Mounts; Daten außerhalb Checkout |
| Architektur / Entscheidungen | [architecture.md](architecture.md) / [decisions.md](decisions.md); docs/-Pfade sind Verweise |

## Task-Verzeichnis

TASK-001–015 bleiben als MVP-Referenz in den [Briefings](docs/tasks/specifications.md).
Die folgenden Statusangaben stammen aus den bestehenden Briefings; sie sind
keine neu ausgeführte vollständige Abnahme. Insbesondere Fusion Core ist TASK-112,
Submarine Cables TASK-108. TASK-114 bleibt in diesem Goal offen.

| Task | Titel | Bisheriger Registry-Status |
|---|---|---|
| TASK-100 | vLLM Migration + Embedding Upgrade | DONE ✅ |
| TASK-101 | Neo4j + Two-Loop Graph Architecture | DONE ✅ (committed 2026-03-30, 69 tests) |
| TASK-102 | Event Codebook + LLM Classifier + Entity Extractor | DONE ✅ (committed 2026-03-30, 81 tests) |
| TASK-103 | Ingestion Pipeline — Extract → Graph Write | DONE ✅ (committed 2026-03-30, 43 tests) |
| TASK-104 | Hybrid Search + Docling + Reranker | DONE ✅ Phase 1 (committed 2026-03-30, 99 tests). Phase 2 (hybrid sparse) offen. |
| TASK-105 | Agent Tools + Graph Explorer + Vision | DONE ✅ (committed 2026-03-30, 155 intelligence + 17 backend tests) |
| TASK-106 | Demo-Szenario + Polish | DONE ✅ (committed 2026-03-30, scope C+ demo UI integration) |
| TASK-107 | Hybrid Vision — YOLOv8 Detector + Qwen3.5 Reasoner | OFFEN |
| TASK-108 | Submarine Cable Layer | OFFEN |
| TASK-109 | Flights Performance — Redis Caching + Smooth Rendering | PARTIAL ✅ (Update 2026-03-31, Commit: f73a19b) |
| TASK-110 | Dual-Model Architecture — 9B Interactive + 27B Ingestion | PARTIAL ✅ (Update 2026-03-31, Commit: f73a19b) |
| TASK-111 | Voxtral TTS — Audio-Briefings aus Intelligence Pipeline | OFFEN ❌ |
| TASK-112 | Fusion Core — Observations, WorldObjects, Lineage, Review | SPEC ✅ (Design: docs/superpowers/specs/2026-05-03-fusion-core-design.md) |
| TASK-113 | Container-native Think-Tank Full-Text Scheduler (Host-Bridge ablösen) | ERLEDIGT (2026-09-27) |
| TASK-114 | WorldView Globe Declutter — Lesbarkeit & Performance (LOD/Clustering/Density/Color) | OFFEN |
| TASK-115 | Local Sovereign Agent Sidecar (ds4 + DeepSeek V4 neben Claude Code) | IDEE / Exploration (kein Code) |
| TASK-116 | Country Indicators Enrichment Layer (World Bank / OWID / SIPRI / V-Dem / Comtrade) | OFFEN |
| TASK-117 | Tree-Aware Longform Retrieval | DESIGN REVISED / IMPLEMENTIERUNGSPLAN OFFEN |
| TASK-118 | Verified Bug-Hunt Follow-ups | OFFEN / LOW |
| TASK-119 | Operational Trust Chain Hardening | IN PROGRESS — S01-S02 DONE ✅; S03 REVIEW-FIXES VERIFIED, |
| TASK-120 | Versionierter Spatial-Attribution-Release-Vertrag | DONE ✅ (2026-08-06) |
| TASK-121 | Gebundene HttpSpatialCatalog-Metadaten-Caches | DONE ✅ (2026-08-07) |
| TASK-122 | Expliziter Spatial-409-Rehydrate-Vertrag | DONE ✅ (2026-08-06) |
| TASK-123 | Spatial Plan-03 Review-Follow-ups vor Legacy-Cleanup | DONE ✅ (2026-08-10) |
