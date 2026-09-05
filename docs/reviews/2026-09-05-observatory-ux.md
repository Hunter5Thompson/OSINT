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
| Hoch | Kein ODIN-Backend-Listener auf 8080 und keine laufenden ODIN-Container während der Prüfung. Die UI erreicht entsprechend keine Live-Daten. | Den freigegebenen ODIN-Betriebsmodus separat starten und Datenalter, Feed-Zustand, Spatial-Recovery und Analyseweg im laufenden Stack abnehmen. Kein GPU-/Provider-Wechsel erfolgte in dieser Session. |
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
