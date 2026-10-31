# G07 — Dichte, Aggregation und Viewer-Lifecycle

Dirty Sourcecheckpoint auf Basis `e8603c6`. TASK-114/UI-01 bleiben bis zu
repräsentativen Live-Dichten, gebautem Browser, nativer GPU und menschlicher
Sichtprüfung offen. Das vorab festgelegte Protokoll ist
`docs/plans/globe-quality-2026-10-10.md`.

Flugzeuge: harte Distanzcaps 250/600/1.500, gültige eindeutige Kontakte im
Viewport, gewählte ID vor militärisch markierten vor übrigen Kontakten.
Distanzdämpfung nutzt den gemeinsamen Cesium-Vertrag. Die Mengenanzeige
unterscheidet Viewport, Renderinglimit, ungültige und doppelte Records.
Clientabrufzeit ist keine Kontakt-/Publikationszeit und kein Quellenbeleg.
Gesunder Leerbestand, erster Ausfall und fehlgeschlagene Aktualisierung eines
vorherigen Clientstands sind sichtbar verschieden.

Graph-Events: dieselben Symbolcaps; gleichartige Events auf Globehöhe in
10-Grad-Zellen aggregiert, exakte tatsächliche Mitgliederzahl. Ausgewählte
Original-ID bleibt Einzelobjekt. Viewport-/Zeitfilter vor Aggregation;
Datumslinie und Pole explizit. Aggregate zeigen keinen erfundenen
Einzelzeitpunkt/Callout; ihr Pick zeigt Mitgliederzahl und zoomt auf Detailhöhe.
Zeitfading sucht den nächsten wirklichen Mitgliederzeitpunkt; Schweregrad
priorisiert Caps und Stacklabels. Einzelpicks behalten Originalkoordinaten.

Beide Layer aktualisieren bei `moveEnd`. Viewer-Wechsel mit unveränderten
Daten befüllt neue Collections und bindet Timer/Listener erneut. Zerstörte
Viewer werden nicht mutiert; Level 4 stoppt Flugzeuginterpolation/Trails.
Keine Entity-Massenobjekte, neuen Frame-Kameralisteners oder LLMs.

RED-Belege: Flight-Dichte/Lifecycle 10, Flight-Quelle/UI 6, Event-Dichte 6,
Event-Aggregatpick/Mengenanzeige 2. Der erste Event-Green fand eine vermeidbare
Floating-Point-Abweichung bei identischen Longituden; die identische Original-
longitude wird dort exakt erhalten. Bestehende Tests/Erwartungen nicht gelockert.
Viewerfixtures erhielten die tatsächlich verwendeten öffentlichen Kamera-
und Ellipsoid-Verträge. Final: 137 Dateien/865 Frontendtests, ESLint, Repo-
und Browser-TypeScript, Build und diff-check grün. Buildrevision null bei dirty
Quellen, kein committed finaler Head/Image-/Releasepass.

Synthetische 10.000er-Mengen mit Produktionsselektoren sind in
`evidence/G07/density-counts.json` samt Sourcehashes gesichert. GLOBE-Events
hier 2 Symbole für alle 10.000 Mitglieder einschließlich ausgewählter Einzel-ID;
REGIONAL/LOCAL repräsentieren 600/1.500 Mitglieder und weisen den Rest aus.
Die benachbarten RED/GREEN-Logs prüfen tatsächliche BillboardCollections.
Mengen oder Unitzeiten sind ausdrücklich keine FPS-/Live-/GPU-/Humanbelege.

Zwei neue Browser-Dichte/Recovery-Fälle vorbereitet und typgeprüft, nicht
ausgeführt: bekannte Preview-/TCP-EPERM-Sperre. Keine unveränderte Wiederholung
oder alternativer Browser-/Daemon-/Netzwerkpfad. Vorher-/Nachher-GPUdaten,
repräsentative Livequellen, Screenshots und menschliche Ratings fehlen.
