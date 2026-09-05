# Observatory UX — Repo-Analyse und Session-Notizen

Stand: 2026-09-05. Ausgangspunkt: lokaler `main` bei `9ee06cc`.
Arbeitsbranch: `feat/frontend-observatory-ux-20260905`.

## Einschätzung

ODIN hat bereits einen umfangreichen fachlichen Kern: Cesium-Karte, zeitliche
Ereignisnavigation, Spatial-Scope-Verträge, Graphsuche, Briefings und Incident-
Workflows. Die unmittelbar sichtbare Schwäche war die Verbindung dieser Teile:
Der Einstieg erklärte interne Subsysteme, die Kartenansicht bot viele gleichzeitig
aktive Layer, und Datenfehler waren teilweise von einem leeren Ergebnis nicht
zu unterscheiden. Das vorhandene Hlíðskjalf-Design ist eine brauchbare Grundlage;
die Überarbeitung entwickelt seine warme Palette und Typografie weiter.

Dies ist eine gezielte Analyse der Architektur, Task-Registry, Frontend-Abläufe
und ausgewählter Backend-Verträge, kein vollständiges Sicherheits- oder
Produktionsaudit. Die unten genannten offenen Punkte sind nicht erledigt, nur
weil diese UI-Überarbeitung abgeschlossen ist.

## Umgesetzt

- Neue Startseite mit lokal gerendertem Referenzglobus, geografischem Einstieg,
  verständlichen Kennzahlen, Signalbereich und drei konkreten Arbeitswegen.
- Kennzahlen zeigen ihren Snapshot-Zeitpunkt; der Feed zeigt separat seinen
  Verbindungszustand. Unbekannte Werte erscheinen als Strich, nicht als gemessene
  Null. Fehler lassen sich gezielt erneut anfragen.
- Meldungen behalten beim Sprung zur Karte sowohl ihre Quell-ID als auch den
  Titel als Suchanfrage. Auch der Kartenticker öffnet jetzt die Suche.
- Drei explizite Layer-Presets: Situation, Movement, Infrastructure. Sie setzen
  jeweils eine vollständige Auswahl; manuelle Abweichungen erscheinen als custom.
  Spatial-Policies bleiben für die tatsächliche Darstellung maßgeblich.
- Fokusmodus mit Wiederherstellung zuvor geöffneter Panels und erhaltener
  Suchanfrage; der Ticker wird dabei nicht neu verbunden. Horizontale,
  beschriftete Panel-Schalter; gemeinsame rechte Spalte für Suche und Inspector.
- Tastaturkürzel greifen nicht in editierbare Inhalte oder Browser-Kombinationen
  ein. Die Navigation erhält einen Sprunglink zum Hauptinhalt und sichtbare
  Fokusmarkierungen. Startseite und Navigation passen sich schmalen Ansichten an.
- Primäre Seitenwechsel werden synchron an den Router übergeben. Im Browser
  wechselte zuvor unter laufender Karte die URL, während die alte Ansicht stehen
  blieb. Derselbe Ablauf besteht mit der gezielten Änderung; modifizierte Klicks
  behalten ihr normales Browser-Verhalten.
- Die Suche unterscheidet Dienstfehler von einer erfolgreichen Suche ohne Treffer
  und bietet einen erneuten Versuch an.
- Ohne Karten-Token verwendet Cesium seine mitgelieferten Natural-Earth-Kacheln.
  Eine sichtbare Meldung erklärt den eingeschränkten Betrieb; fehlende
  Backend-Konfiguration kann erneut angefragt werden. Kein automatischer Wechsel
  in einen anderen Spatial-Modus.
- Die Canvas-Cleanup-Korrektur aus dem bereits vorhandenen Hotfix `d4843bc`
  wurde gezielt samt Regressionstest übernommen. Der ursprüngliche Worktree
  bleibt unverändert. Zusätzlich wird der Renderloop vor dem Abbau gestoppt,
  damit ein Fehler in einem Primitive keinen weiterlaufenden, teilweise
  zerstörten Viewer hinterlässt.

## Nächste fachliche und technische Schritte

| Priorität | Befund und Evidenz | Nächster konkreter Schritt |
| --- | --- | --- |
| Hoch | TASK-114 dokumentiert fehlendes gemeinsames LOD/Clustering. Die dazugehörige Implementierung liegt separat unter `.worktrees/task-114-declutter-p1`; sie ist nicht Teil dieses Changes. | Den vorhandenen Branch anhand seiner Tests und realer, dichter Datenbestände prüfen und gezielt integrieren. Die neuen Modi ersetzen kein Clustering. |
| Hoch | `services/frontend/src/services/api.ts` liest `VITE_ADMIN_TOKEN` und sendet ihn als `X-Admin-Token`. Im Browser-Bundle eingebettete Werte sind keine privaten Server-Credentials. TASK-119 S05 enthält diesen Punkt bereits. | Den vorgesehenen Auth-Vertrag als eigenständigen Change umsetzen und mit Negativtests prüfen. Hier wurden weder Tokens gelesen noch Zugriffsrechte verändert. |
| Hoch | Die erste UI-Prüfung lief ohne Backend. Nach der expliziten Startfreigabe wurde der reale Stack geprüft; siehe Live-Abnahme unten. | Die dort dokumentierten Feed-Ausfälle, Zählabfragen und Analyse-Latenz gezielt bearbeiten. |
| Mittel | Der Spatial-Breadcrumb bleibt bei fehlendem Katalog auf `Loading spatial scope`. Die neue Verfügbarkeitsmeldung erklärt die übergeordnete Ursache, ersetzt aber keine Recovery des Katalogzustands. | Hydration-Fehler im Spatial-State explizit sichtbar machen und Wiederherstellung nach Rückkehr des Backends testen; fehlgeschlagene Scopes weiterhin geschlossen halten. |
| Mittel | `/api/graph/search` sucht Entity-Namen mit `CONTAINS $q` (`services/backend/app/routers/graph.py`). Ein kompletter Nachrichtentitel ist nicht zwingend ein Entity-Name. | Einen serverseitigen, belegbaren Signal-zu-Entity-/Ereignis-Vertrag schaffen. Der neue Link ist eine erhaltene Suchanfrage, keine behauptete automatische Auflösung. |
| Mittel | Spatial ist im lokalen Code nur bei explizitem `VITE_SPATIAL_SCOPE_ENABLED=true` aktiv; Compose setzt einen Default von true. | Den bereits unter TASK-119 S05 erfassten Dev-/Build-Vertrag vereinheitlichen und Clean-Clone-Prüfung ergänzen. |
| Mittel | Vite meldet Hauptbundle und Splat-Renderer über 500 kB. Routen werden in `app/router.tsx` statisch importiert. | Ladezeiten messen und erst dann Routen-/Renderer-Lazy-Loading mit Navigationstests umsetzen. |
| Mittel | Task-Registry und Architekturtexte enthalten historische Status-/Modellangaben; separate Worktrees enthalten weitergehende Änderungen. | Status aus Commit-/Branch-/Runtime-Evidenz abgleichen, bevor ältere OFFEN- oder DONE-Markierungen als aktueller Zustand übernommen werden. |

## Validierung

Die neuen Verhaltensänderungen wurden mit zunächst fehlgeschlagenen Regressionstests
entwickelt. Konkrete rote Fälle: verlorener Titel im Deep-Link, falscher Feed-Status,
fehlende Wiederholungsaktionen, abgefangene Eingaben in editierbaren Bereichen,
fehlende Fokus-/Preset-Abläufe sowie beide Viewer-Cleanup-Randfälle.

- `npm ci`: erfolgreich; Lockfile unverändert.
- `npm run lint`, `npm run type-check`: erfolgreich.
- `npm test`: 641 Tests in 114 Dateien bestanden.
- `VITE_SPATIAL_SCOPE_ENABLED=true npm run build`: erfolgreich. Die bestehenden
  Größenwarnungen für Hauptbundle/Splat-Renderer bleiben sichtbar.
- Echter Chromium-Browser: Startseite bei 1440 px und 390 px geprüft, keine
  horizontale Überbreite; oberer Einstieg und unterer Signal-/Workflow-Bereich
  visuell kontrolliert. Referenzkarte rendert auch ohne Backend.
- Produktionsvorschau: Arbeitsmodus/Layer-Auswahl, Fokus/Wiederherstellung,
  Tastaturfokus der Suche und drei aufeinanderfolgende Worldview-/Briefing-Wechsel
  mit tatsächlichen Browser-Mauseingaben bestanden; keine JavaScript-Fehler.

Browserprüfungen verwenden den echten Frontend-Code mit lokaler Referenzkarte.
Mangels laufendem Backend sind Live-Ingestion, gefüllte operative Layer,
autorisierte Schreibaktionen, Spatial-Katalog-Recovery und Analysequalität hier
nicht live abgenommen. Positive Daten-/Fehlerzustände sind zusätzlich durch die
Frontend-Tests mit kontrollierten Antworten geprüft. Backend-, Intelligence-,
Ingestion- und Vision-Tests wurden bei diesem Frontend-Change nicht ausgeführt.

## Umfang und geschützte Arbeit

Geändert wurden Frontend-Einstieg, Shell-/Panel-Präsentation, Worldview-Bedienung,
Suche/Ticker, gezielte Viewer-Lifecycle-Stellen sowie zugehörige Tests. Neue
Präsentationsregeln liegen in `src/theme/observatory.css`; neue Arbeitsmodi in
`components/worldview/workspaceModes.ts`. Keine neuen Laufzeitabhängigkeiten,
keine Änderungen an Lockfiles, Datenbanken, GPU-Konfiguration oder Backend-Code.

Die vorgefundenen ungetrackten Dateien `docs/odin-stack-onepager.html` und
`docs/superpowers/plans/2026-08-25-task-114-declutter-p1-render-and-labels.md`
sowie alle anderen Worktrees wurden nicht verändert oder in den Commit aufgenommen.

## Live-Abnahme nach Startfreigabe (2026-09-05, ab 21:30 UTC)

### Laufender Stand

- Start über `odin.sh`: zunächst `interactive`, anschließend `interactive-spark`.
  Frontend, Backend, Intelligence und Spark-Ingestion wurden aus diesem Worktree
  gebaut. UI: `http://localhost:5173`; Backend: `http://localhost:8080`.
- Lokales Modellinventar: `qwen3.5` und `munin`; Spark meldet
  `Qwen/Qwen3.8-27B`. Kein zweites lokales LLM gestartet. TTS, Open WebUI und
  Splat-Dienste blieben unberührt. Alle ODIN-Hostports bleiben an Loopback gebunden.
- Qdrant startete mit 1.168.585 Punkten und Status green. Bestehende Volumes
  wurden weiterverwendet. Der freigegebene Scheduler nimmt echte Daten auf;
  der vorhandene Auto-Promoter erzeugt dabei reguläre Incidents.
- `odin.sh smoke`: 14 bestanden, 0 fehlgeschlagen, 1 übersprungen
  (absichtlich inaktiver lokaler Ingestion-27B-Modus).

### Tatsächlich geprüft

- Durch den Produktions-Nginx: Backend/Config, Spatial-Katalog, Graphsuche,
  Erdbeben, Kabel und vorhandene Reports jeweils HTTP 200. Stichprobe:
  14 Graph-Treffer für Germany, 107 Erdbeben, 728 Kabel/1.925 Landepunkte,
  zehn vorhandene Reports; Flug-Smoke mit über 9.000 Flugzeugen.
- SSE liefert echte aktuelle Empfangsereignisse, unter anderem RSS, FIRMS,
  USGS und EONET. Empfangszeit ist nicht automatisch Publikations-/Ereigniszeit.
- Erster ReAct-Aufruf: Timeout nach 120 Sekunden, als SSE-Fehler sichtbar.
  Direkter Modell-Canary danach: nichtleere Antwort. Zweiter ReAct-Aufruf:
  vollständiges `result` und `done`, drei dokumentierte Qdrant-Suchaufrufe,
  vier Quellbezeichnungen und nichtleerer Bericht, nach etwa 114 Sekunden.
  Bericht weist auf alte/dünne Evidenz hin; dies ist Funktionsnachweis, keine
  unabhängige fachliche Verifikation seiner Aussagen. Kein Report gespeichert.
- Reale Chromium-Mauseingaben: Modi/Layer, Fokus/Wiederherstellung, Suchfokus
  und drei Worldview-/Briefing-Wechsel mit echtem Backend bestanden. Frühe
  Durchläufe scheiterten unter Renderinglast bzw. an verdeckten Bedienelementen;
  der erfolgreiche Durchlauf schloss Incident-Toasts über den neuen Knopf.
  Keine JavaScript-Fehler im erfolgreichen Durchlauf. Software-WebGL ist träge;
  flüssiges Hardware-Rendering ist damit nicht abgenommen.

### Im Live-Test zusätzlich korrigiert

- Incident-Toasts waren nicht manuell schließbar und verdeckten Kartenmodi
  bzw. auf schmalen Screens die Navigation. Jetzt: expliziter zugänglicher
  Schließen-Knopf, begrenzte Breite und Position oberhalb der unteren
  Kartenleiste statt über den oberen Bedienelementen.
- Nach Katalog-Hydration belegten sämtliche Länder als Buttons einen großen
  Teil des Globus. Eine native Gebietsauswahl ersetzt diese Button-Wand;
  Breadcrumb, Parent-Navigation und `child-click`-Scope-Kommando bleiben erhalten.
- Beide Änderungen mit roten Regressionstests begonnen. Keine Änderung der
  Spatial-Policy, kein Daten-Fallback und keine Datenbankmigration.

### Offene Befunde aus echten Antworten

1. NOAA NHC: `CurrentSummaries.json` liefert 404; GDACS Eventlist liefert 400.
2. GDELT Raw: `lastupdate.txt` antwortet auf HTTP mit HTTPS-Redirect (301),
   den der vorhandene Downloader als Fehler behandelt. Andere Feeds laufen;
   Container-health bedeutet daher keine vollständige Quellenabdeckung.
3. Die Landing-Zählung aller Qdrant-Signale fällt unter laufender Ingestion
   zeitweise aus (`nuntii_source=qdrant:signals:unavailable`, Backend-Timeout).
   UI zeigt dafür einen unbekannten Wert. Ein SSE-Ereignis belegt für sich
   weder eine erfolgreiche Qdrant-Schreibung noch vollständige 24h-Zählung.
4. Analyse-Latenz liegt nahe am 120s-Limit; ein Kaltstart-Aufruf scheiterte.
5. TASK-114/LOD bleibt wichtig; das native Scope-Menü löst keine dichten
   operativen Layer. Schreibworkflows, Provider-Recovery und alle externen
   Quellen wurden nicht vollständig abgenommen.
6. **Scope-Wechsel noch nicht live freigegeben:** Der abschließende Browsertest
   wählt Germany im nativen Picker. `/api/spatial/scope` für `country:DEU`
   liefert 200 und die URL erhält `scope=country%3ADEU`, aber Breadcrumb und
   weitere Timeline-Anfragen bleiben auf World. Kein JavaScript-Fehler, kein
   erfolgreicher Scope-Commit innerhalb der Testfrist. Die Auswahl sendet das
   korrekte Kommando (Unit-Test und HTTP-Nachweis); Router-Acknowledgement und
   Controller-Commit unter laufendem Cesium müssen separat reproduziert und
   korrigiert werden. Die erfolgreiche Seitennavigation ist kein Beleg für
   einen funktionierenden Scope-Wechsel.

### Testprotokoll dieser Fortsetzung

- Frontend nach zusätzlicher UX-Korrektur: 642 Tests / 114 Dateien; Lint,
  Type-Check und Produktionsbuild bestanden. Bundle-Größenwarnungen bleiben.
- Backend: 585 Tests, Ruff und striktes Mypy bestanden; eine bestehende
  Starlette/httpx-Deprecation-Warnung.
- Intelligence: 484 Tests bestanden.
- Data-Ingestion: 1.445 bestanden, 1 übersprungen, 17 abgewählt. Die
  Standardkonfiguration schließt `live`-Tests aus; kein vollständiges Live-Testgate.
- Vision-Enrichment: 22 Tests bestanden; Vision-Service wurde nicht gestartet.
- Python-Tests nutzten die vorhandenen lokalen uv-Umgebungen. Docker-Builds
  installierten mit dem gepinnten uv und `--locked`; keine Lockfile-Änderung.
