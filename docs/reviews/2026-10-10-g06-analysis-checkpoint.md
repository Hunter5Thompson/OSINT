# G06 — Analysevertrag und Originalquellenstatus

Lokaler dirty Sourcecheckpoint auf Basis `e8603c6`, einziger Servicewriter.
ANA-01, reale Retrieval-/Modell-/Latenzprüfung und menschliche Abnahme sind offen.

Assessment-Felder tragen jetzt einzeln `declared` oder `default`. API, SSE,
Historymodell und gespeicherter Report erhalten diese Metadaten; Almanac,
WarRoom und Briefing zeigen Defaultwerte als unbekannt. Historische Records
ohne Metadaten bleiben unbekannt. `unverified` ist der einzige neue
Verifikationsstatus; gültig gelesen bedeutet keine Faktenbestätigung.
Report-Writes bleiben deterministisch und parametergebunden. Keine reale
Neo4j-/Qdrant-/historische Änderung wurde ausgeführt.

Publication, observation und ingestion bleiben getrennte explizite UTC-Achsen.
FIRMS schreibt künftig die validierte Beobachtungszeit; der unabhängige
RSS-Indexer schreibt den tatsächlichen Ingestzeitpunkt. Der Reader erkennt
beide vorhandenen RSS-Publikationsfelder, ohne Ingest oder Ereigniszeit als
Publikation umzudeuten. Defekte Daten und UTC-Überläufe bleiben unbekannt.

Zwölf synthetische Fälle sind vor Modellläufen eingefroren; Corpus-SHA:
`b1963dafbb622a1590561f5da7d1d677abe3145d225870a0f216903c1c80dd3f`.
Der Evaluator prüft 36 Case/Repetition-Paare, tatsächlich konsumierte
strukturelle Referenzen, Assessmentwerte/-status, fünf Entscheidungen und
acht Toolstarts. Latenz ohne nachgewiesene Revision/vergleichbare Last bleibt
UNKNOWN; menschliche Ratings bleiben PENDING. `factual_release=false` und
`release_gate=OPEN` werden nicht aus technischen Passes überschrieben.

Der vorbereitete Runner verwendet die Produktionsgraphfactory mit expliziten
read-only synthetischen Toolfixtures. Seamtests nutzen Graphprobe/FakeLLM;
sie sind kein voller LangGraph- oder Modellpass. Nur `--prepare` wurde hier
ausgeführt. Kein neuer Modell-/Live-Retrievallauf und kein weiterer lokaler LLM.

Gezielte Prüfungen: Status/Zeit/Poison 78; nachfolgend Producer/Legacyzeit 35,
FIRMS/Provenienz 44, Evaluator/Harness/Status/Zeit 28; Backend-Report/Status 22
und später Report-Clear 4; UI-Status/Briefing 20. Die Mengen überlappen und
werden nicht zu einer Gesamtsuite addiert. Ruff und Backend-Mypy (95 Dateien)
grün. Neue Regressionen wurden fachlich rot reproduziert; Import-, Fixture-
und Mockisolationsfehler sind getrennt dokumentiert. Finaler Serviceabschluss
nach weiteren Änderungen bleibt nötig. Unveränderte Fullsuite-Threadblocker
werden nicht erneut gestartet, gepatcht oder durch Skip verborgen.

Originalintake: drei deterministisch ausgewählte offene FIRMS-IDs aus dem
eingefrorenen Ledger; sechs bestehende Referenzdateien stimmen im SHA überein.
Neue Originale: 0; geschlossene IDs: 0. Keine vorhandene Beobachtungsprüfung
oder Reparatur wiederholt. Die übrigen IDs behalten ihren eingefrorenen
Einzelstatus. NASA-Archivzugang verlangt Authentifizierung; ersetzte Standard-
Produkte sind kein Original-NRT. Keine Zugangsdaten gesucht oder Login/Email
ausgelöst. Die kleine Stichprobe beweist keine weltweite Nichtverfügbarkeit.

R01-Dry-run-Vertrag beschreibt Version/Hashes, Vorher-/Nachher, Konfliktsperre,
Idempotenz, Journal, Backup und unabhängige Datenrücknahme. Ein realer Apply-
oder Rollbackpass wird nicht behauptet. Datenumsetzung braucht eigene Freigabe.

Belege: `/data/odin-goals/2026-10-09-repo-hardening/evidence/G06/` sowie
`docs/plans/analysis-quality-2026-10-10.md`, `R01-dry-run-contract.md` und
`services/intelligence/evaluation/README.md`.

## G06 Quellen-Zeitachsen und Abnahmevertrag — 10.10.2026
Die minimale evidence_summary entsteht aus tatsächlich konsumierten strukturellen Artefakten am Synthesis-Budgetsink. Sie enthält ausschließlich Beleg-ID, Provider/Typ, die drei getrennten UTC-Zeitachsen und unverified; keine Titel, Texte, URLs, privaten SourceRefs oder Faktensiegel. API, Shared-SSE, gespeicherter Report und Reportnachricht sowie Almanac/WarRoom/Briefing erhalten sie. Nachträgliche Chatantworten tragen ihre eigene Evidenz, ohne dem alten Reportkörper neue Quellen zuzuordnen. Legacy bleibt unbekannt; Sources zählt konsumierte Beleg-IDs statt Provider. Numerische Zeitwerte werden abgelehnt.
Der Evaluator verlangt vorab festgelegte echte Lastbeobachtungsbindungen für alle36 Paare, genaue öffentliche Zeitsummaries und unabhängige Reviewer-Metadaten; Fehlertexte und fehlende Beobachtungen qualifizieren keine Antwort/Latenz. Diese Prüfung authentifiziert keine behaupteten Messdateien oder Menschen. Kein realer Graph-/Modell-/Retrievallauf, Latenz UNKNOWN, Human PENDING, Faktenfreigabe false.
Abschluss nach den letzten Änderungen: Frontend137Dateien/870Tests, ESLint/Repo-/Browsertypen/Build; Intelligencefokus72/Ruff; Backendfokus28/Ruff/Mypy95 grün. Vier neue isolierte Neo4j-Reportfälle collect-only; zwei vorhandene CI-Jobs um eindeutig markierte disposable A08/Reportfixtures ergänzt und YAML/Python/Paths statisch geprüft, nicht remote ausgeführt. Fullservice-/DB-/Browser-/Image-/finalHEAD-/Livegates unverändert offen.
Ein zusätzlicher Reporttest hatte zunächst get_report nicht gemockt und hing im realen Readpfad; eigener59324exit130 beendet, Fixture korrigiert, danach fachliche REDs/GREENs. Keine Datenmutation daraus. Alle eigenen zuletzt gestarteten Prüfprozesse beendet.
Nächster begrenzter Schritt: Gray-Flag-Original gezielt mit altem lokalen Export verbinden, menschliches Reviewpaket und G01–G08 Finding-/Gatematrix fertigstellen, vollständiges dirty Sourcebundle sichern. Kein wiederholter Vollscan/Repair/Preview-/Index-/Dockerprobe. Gesamtgoal/Servicewriter aktiv; kein echter weiterer Hook oder zweiter Writer.
