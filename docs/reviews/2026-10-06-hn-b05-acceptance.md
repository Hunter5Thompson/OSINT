# B05: Abnahme von Schiffs- und Flugmesswerten

Stand: 06.10.2026. Implementierungsbasis: Main `1359d14`; geprüfter Code:
`b371757` auf `fix/hn-b05-vessel-flight-measurements`.

**B05 ist auf Code-, Test- und Browser-Ebene abgenommen.** Merge und Deployment
sind eigene Schritte. Die laufenden Dienste verwenden diesen B05-Stand noch nicht.
Es gibt keine menschliche Produktabnahme durch diesen Bericht.

## Was sich für Nutzer ändert

- **D01:** Fehlende Schiffsbewegung, AIS-SOG 102.3 und ungültiger Kurs werden
  als unbekannt behandelt. Echte Nullwerte und SOG 102.2 bleiben erhalten.
  Das gilt für AISStream, Digitraffic und alte Cache-Rows. Ohne Geschwindigkeit
  und Kurs entsteht kein Bewegungsvektor; ohne Kurs zeigt das Symbol keine Richtung.
- **D02:** Fehlende Flugmesswerte und Kontaktzeiten bleiben `null`. Fehlende
  Barohöhe kann durch gemessene geometrische Höhe ersetzt werden; echte Barohöhe
  null Meter bleibt erhalten. Unbekannte Höhe wird nur technisch am Boden platziert
  und im Detail als „unknown“ angezeigt. Bewegung benötigt gemessene Werte.
- **D10:** Nationale ICAO-Blöcke begründen keine Teilstreitkraft. Ohne belegten
  Teilbereich bleibt die neue Zuordnung unbekannt; bestehende historische Labels
  werden erhalten und gehören in das separate Dateninventar R01. Die Anzeige
  unterscheidet unbekannte Militärrolle, bekannte Typcodes und zivilen Verkehr.
  Die verbleibenden Callsign-/Bewegungsheuristiken sind keine Identitätsbeweise.

## Review und Korrektur

Im bestehenden D10-Code konnten Callsigns „FORTE“, „SIGINT“ oder „REAPER“ einen
bekannten C17-, F16- oder B52-Typ als Drohne darstellen. Drei neue Regressionen
waren vor der Korrektur fachlich rot. Nach der minimalen Prioritätskorrektur sind
die vier neuen Fälle und die benachbarten Tests grün: **26 Tests**.
Bekannte Typcodes werden vor Callsign-Hinweisen ausgewertet.

Zusätzlich wurden die 70 D01/D02-Regressionen gegen eine exportierte Main-Basis
ausgeführt: **55 fachliche Fehler, 15 bestanden**. Dieselben Tests auf B05:
**70 bestanden**. Das ist ein nachträglicher Regressionsnachweis; es beweist nicht
die historische Test-first-Reihenfolge der drei ursprünglichen Commits.

## Ausgeführte Abschlusschecks

| Prüfung | Ergebnis |
|---|---|
| Backend, vollständiges `pytest -q` | 891 bestanden |
| Backend Ruff `app/` und striktes Mypy `app/` | grün; Mypy 91 Dateien |
| Ingestion, vollständiges `pytest -q` | 1.685 bestanden, 1 bestehender Dev-Compose-Fall ausgelassen, 23 Live-Fälle ausgeschlossen |
| Ingestion Ruff `.` | grün |
| Frontend Vitest, nach Reviewkorrektur | 121 Dateien, 684 Tests bestanden |
| Frontend ESLint, TypeScript und Build | grün; bestehender Hinweis auf große Build-Chunks |
| `git diff --check` | grün |

Python lief mit uv 0.10.0 und `uv run --locked --all-extras`, Frontend mit Node
22.23.1 und vorhandenen vollständigen Abhängigkeiten (`npm ls --depth=0` grün).
Produktive Neo4j-/Qdrant-Ziele waren für Python-Tests durch unerreichbare lokale
Ziele ersetzt. Der bestehende Ingestion-Dev-Compose-Test blieb deaktiviert;
keine produktiven Mutationsproben und keine Datenmigration wurden ausgeführt.

## Ausgeführte Browserabnahme

Echter Playwright/Chromium mit WebGL über SwiftShader; B05-Vite auf einem
eigenen Loopback-Testport, `VITE_SPATIAL_SCOPE_ENABLED=true`. API-Messwerte
waren kontrollierte Fixtures; der Spatial-Katalog wurde lesend vom laufenden
Backend geladen. Die Testinstrumentierung machte nur Viewer und Cesium für
Messungen zugänglich. Auswahl lief über tatsächliche Maus-Klicks auf Billboards.

- Unbekanntes und fahrendes Schiff sowie unbekanntes Militärflugzeug, C17 und
  ziviles A320 geöffnet: erwartete Details einschließlich „unknown“ sichtbar.
- Unbekannte Kontakte bleiben über das Beobachtungsfenster positionsgleich;
  der gemessene C17-Kontakt bewegt sich. Kursloses Symbol als Ring geprüft.
- Flug- und Schiffslayer aus-/eingeschaltet; WorldView → Briefing → WorldView:
  kein Globe-Canvas in Briefing, danach genau ein Canvas, keine JS-Ausnahme.
- Screenshots in 1440×1000, 1280×800 und 1920×1080 erstellt und visuell geprüft.
- Ergänzende Datumsgrenzen-/Polfälle sowie neutrale Militärrolle und Zeitbereich-
  Bedienelemente sind im separaten Browserprotokoll dokumentiert.

Die Fixture-Histogramme tragen keinen vollständigen Spatial-Application-Vertrag;
„scope unavailable“ in diesen Testbildern ist deshalb kein Live-Finding.
Der zusätzliche ungefixturete Live-Browserlauf zeigt „global · complete“.
Keine Aussage über native GPU-Leistung, alle Browser, Dauertest oder die Qualität
historischer Rollenlabels.

## Nachweise und Fortsetzung

Lokale Protokolle, Reproskripte und Screenshots:
`/data/odin-b05-acceptance-20261006/`. Insbesondere:
`backend-pytest.log`, `ingestion-pytest.log`, `frontend-vitest-final.log`,
`d10-review-red.log`, `d10-review-green.log`, `d01-d02-main-red.log`,
`browser-result.json`, `browser-supplement-result.json` und `browser_probe.py`.
Diese Artefakte bleiben auf der Datenplatte und werden nicht als Build-Cache
oder private Live-Daten ins Repository aufgenommen.

Der nächste Nutzerauftrag ist die Betriebsprüfung von Datenfrische,
Analysequalität, Browser-Verhalten und deploytem Code. Der
[Live-Bericht](../reports/2026-10-06-odin-live-status.md) enthält erste ausgeführte
Nachweise und offene Findings. B06 wird dadurch nicht automatisch begonnen.
