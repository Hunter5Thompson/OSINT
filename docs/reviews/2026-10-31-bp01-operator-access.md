# BP-01 — gemeinsamer Operatorzugriff, lokaler Prüfstand

Stand: 31.10.2026. Umsetzung ausschließlich BP-01 des Backendplans
`/data/odin-backend-plan-20261031/PLAN.md`, als Folgearbeit zu HN-B10/D09.
Isolierter Worktree: `/data/odin-worktrees/backend-bp01-20261031`, Branch
`fix/backend-bp01-operator-auth-20261031`, frisch überprüfte Main-Basis
`c003ed6b5b667c9af6a6fdc26e9cb4739945e320` (Planbasis war `7fe41b0`).

## Ergebnis und Verantwortung

`app.admin_auth.require_operator_access` besitzt die gemeinsame Auswahl- und
Prüfregel für Dossiermutationen und alle vier LLM-Routen. Die bisher duplizierten
Report-Dependencies entfallen. Der Hotspot-Alias ist separat geschützt, weil ein
Python-Funktionsaufruf keine FastAPI-Dependencies ausführt. Fehlerantworten und
öffentliche Lesewege behalten ihren bestehenden Vertrag.

Das Frontendimage enthält nun versionierte nginx-Templates und einen
Start-Hook. Das Releaseflag `--operator-gateway` aktiviert sie ausdrücklich
und stellt ein Runtime-Secret bereit; der Frontendport bleibt Loopback.
Die Regeln ergänzen ausschließlich die benötigten Modell-POSTs und bestehenden
Dossiermutationen. Falsche mitgesendete Tokens bleiben falsch. Cross-Site,
fremde/null Origins und abweichende Origin-Schemata werden vor dem Backend
abgewiesen. Fehlender Origin ohne Cross-Site-Marker bleibt für lokale Werkzeuge
erlaubt. [API-, Aktivierungs- und Rollbackvertrag](../operations/operator-gateway.md).

## Nachweise

| Prüfung | Ergebnis |
|---|---|
| Bestehende berührte Regressionen vor Umsetzung | 73 bestanden |
| Neue Operatorfälle gegen unveränderte Main-Router | 15 erwartete Negativtestfehler, 11 positive Fälle bestanden |
| Gateway-Releaseverträge vor Umsetzung | 3 erwartete Fehler |
| Vollständiges Backend-pytest | 1.126 bestanden |
| Ruff, Backend-App und Tests einschließlich neuem Integrationstest | bestanden |
| Striktes Mypy auf `app/` | 95 Quelldateien ohne Befund |
| Vollständige Betriebsprüfungen `tests/ops` | 119 bestanden |
| Frontend ESLint, Typecheck und Produktionsbuild | bestanden |
| Vollständige Frontendtests | 877 bestanden, 139 Testdateien |
| Echter nginx / echte Backendrouten / isolierte Fakes | 5 Integrationsfälle bestanden, einschließlich gebautem Browserchat |
| Shellsyntax, `git diff --check`, manueller Scope-/Diff-Review | bestanden |

Die negativen HTTP-Fälle prüfen neben 401/503 die Abwesenheit von SSE-Erzeugung,
Spatial-Auflösung, Almanac-/Reportzugriffen, Nachrichten, Berichtupdates und
Intelligence-HTTP. Positive Fälle prüfen globale/berichtbezogene Analyse,
Hotspot und beide Briefings, einschließlich normalisiertem Incident-Fallback.
Bestehende Funktionstests authentisieren sich ausdrücklich statt die Dependency
zu umgehen. Redundante Tests der früher duplizierten Report-Dependency wurden
auf das gemeinsame Interface umgestellt.

Der nginx-Test verwendet das im Frontend-Dockerfile gepinnte Image mit den neuen
Templates und dem ausführbaren Hook. Der gebaute Dossierchat schickt keinen
Browser-Token, erhält eine SSE-Antwort und liest nach Reload die Fake-Persistenz.
Alle ausgelieferten statischen Dateien enthalten den Runtime-Testtoken nicht.
Die neue CI-Aufgabe wiederholt Gateway- und Browserprüfung; Remote-CI wurde
hier noch nicht ausgeführt.

Rohbelege und Browser-Screenshot:
`/data/odin-backend-bp01-20261031/evidence/`. Die Backend-Red-Regression wurde
gegen die ursprünglichen Main-Router wiederholt; die Implementierungsdateien
wurden dabei anschließend unverändert wiederhergestellt. Ein früher
Browserlauf scheiterte an fehlendem Chromium, bevor der Browser startete;
nach Installation unter `/data` bestand der vollständige Integrationslauf.

## Grenzen und nächster Schritt

Es wurden keine echten Modellaufrufe oder produktiven Datenbankzugriffe
ausgeführt. Echte Neo4j-Konkurrenzgates sind durch diese reine Zugriffsänderung
nicht betroffen; Cypher, Storesemantik und Datenzustände sind unverändert.
Der aktuelle Hauptcheckout behält seine bestehenden Änderungen, und die
laufenden Dienste verwenden weiterhin dessen Code. Kein Push, Merge,
Imagebuild oder Deployment wurde ausgeführt. Es existiert keine Live-Abnahme
dieser Änderung.

Bestehende Werkzeugmeldungen: Starlette warnt vor dem httpx-TestClient;
Vitest meldet fehlende Canvas-Funktionen in jsdom; der Vitebuild meldet große
Chunks. `npm ci` meldete zehn moderate Advisories im unveränderten Lockfile.
Diese Meldungen sind keine BP-01-Regressionen und wurden hier nicht durch
Dependencywechsel bearbeitet.

Für einen später gesondert freigegebenen Rollout Backend und Frontend derselben
geprüften Revision gemeinsam bauen und bereitstellen, passenden Runtime-Token
und Origin-/Dossierchatpfad am konkreten Ziel prüfen, altes Imagepaar mit
Gatewaykonfiguration für Rollback erhalten. Danach kann BP-02 mit eigenem
Zulassungs- und Abbruchnachweis beauftragt werden.
