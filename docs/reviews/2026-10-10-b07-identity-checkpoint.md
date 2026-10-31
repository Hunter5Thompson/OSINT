# B07 — lokaler Sourcecheckpoint, Datenbank- und Releasegates offen

A07: Baseline31 Nachbarn; 16 fachliche REDs für Zeit/Hash, danach drei REDs
für Legacy-Dedup, Batchidentität und ungültige CSV-Nachbarn sowie ein RED für
kaputtes Dedup-Ergebnis. Erstes Legacyfixture ließ Collection-I/O ungemockt und
wurde beendet; kein fachlicher RED daraus. Standardvierstelliger Hash bleibt,
930/0930/integer führen zu derselben UTC-Minute. Begrenzte Legacy-IDs vor neuer
Verarbeitung lesen; DB-Fehler bleiben Fehler. Rawzeit und Sensor erhalten,
Producerkennung firms-location-hhmm-v2; keine historische Reingestion.

A08: signed-zero REDs in beiden Kopien, Minimal-Kanonisierung bei drei Stellen;
Rawkoordinaten und exakte Null-Island-Regel erhalten. Ein Backendparameter- und
zwei Backfill-REDs belegen fehlende Kandidaten und fälschlich gezählten Write.
Deterministische parametrisierte Templates prüfen Aliasnodes vor Mutation,
nutzen genau einen alten Key weiter und geben bei mehreren Treffern keine Row
zurück. Promoter-Replay darf bereits vorhandenen Zustand ohne Ortswrite lesen.
Der alte manuelle Rekey-Executor verwendet explizit den unveränderten Legacykey;
keine Ausführung/Migration. [Konzept](../plans/herz-und-nieren-2026/B07-identity-transition.md).

GREEN: Ingestion86 (FIRMS/Quellzeit/Keys/Rekey/Geo-Caller); Backend42
(Key/Params/IncidentStore). Ruff und Backend-Mypy95 grün. Ein falscher Dateiname
beim gezielten Testaufruf war kein Testlauf; korrigierter Lauf86 ist der Beleg.
12 Backend- und3 Ingestionfälle für echte Neo4j vorbereitet/collect-only geprüft,
keine DB-RED/GREEN-, Cypher-Ausführungs- oder Concurrencyqualifikation behauptet.
Opt-in: aus jeweiligem Service `uv run pytest integration_tests/test_location_identity.py`;
explizite HN_TEST_NEO4J_URI/PASSWORD, Marker hn-b07-isolated-20261010 und bestehende
Uniqueness-Constraints erforderlich. Keine Defaults/produktive Mutationsprobe.
Fehlende Quelloriginale bleiben ungeprüft. R01 separat mit Journal/Backup/
Konfliktsperre/Idempotenz und Datenrücknahme. Gemischte alte/neue Writer vor
Rollout ausschließen. Full-Python-/TCP-/Docker-/Gitindex-/Remotegates blockiert;
kein Commit/Image/Deployment/Live-/Faktenpass. Belege evidence/G04/B07.
