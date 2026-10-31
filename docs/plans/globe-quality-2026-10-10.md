# G07 — Vorab festgelegte Globe-Prüfung

Dieses Protokoll wird vor den folgenden Dichteänderungen festgelegt. TASK-114
und UI-01 bleiben bis zu Browser-, Live-, nativer GPU- und menschlicher Abnahme
offen. Synthetische Koordinaten beweisen keine reale Quellenabdeckung.

Der erste Slice begrenzt Flugzeug-Billboards nach den bestehenden gemeinsamen
Distanzstufen: GLOBE höchstens 250, REGIONAL 600, LOCAL 1.500. Zuerst werden
gültige, eindeutige Kontakte im aktuellen Viewport berücksichtigt. Eine aktive
Flugzeugauswahl und militärisch markierte Kontakte haben Vorrang; die übrigen
Kontakte behalten eine deterministische Reihenfolge. Auswahlpriorität bestätigt
weder Klassifizierung noch Vollständigkeit. Unterdrückte Kontakte und ungültige
Datensätze müssen als Mengen sichtbar bleiben. Ein Renderinglimit darf kein
Quellenausfall oder Nullbestand sein.

Kameraänderungen aktualisieren die Auswahl bei `moveEnd`; kein neuer
`camera.changed`- oder Frame-Listener. Viewer-Wechsel mit unveränderten Daten
muss neue Collections befüllen, alte Timer/Listener entfernen und die Animation
neu anbinden. Ein zerstörter Viewer darf keine Mutation auslösen. Der bestehende
PerformanceGuard-Level 4 zeigt statische Punkte; Trails und Dead Reckoning sind
dann ausgeschaltet. Bestehende Einheiten-, Datumsgrenzen- und Nullmesswertverträge
bleiben erhalten.

Technische Source-Gates mit tatsächlichen Collections, ohne WebGL-Renderloop:

- Fixtures mit 1.500 und 10.000 Kontakten; harte Caps je Distanzstufe.
- Gewrappter Datumsgrenzen-Viewport, Pol, fehlendes Viewrectangle, ungültige
  Koordinaten und doppelte IDs; exakte Mengenbilanz.
- Picking auf ursprüngliche ID/Koordinaten, Auswahlpriorität, Quelle/Fehler/
  leerer Bestand getrennt. Billboard-Distanzdämpfung bleibt Cesium-seitig.
- Viewer-Wechsel, Layer aus/an, verspätete Antwort, Listener-/Timer-Cleanup.
- Bestehende Eventstacks/Labelprioritäten, Satelliten-Clock und Scope-Verträge
  erhalten; weitere Aggregationsänderungen brauchen eigene RED-Belege.

Gebauter Browser: WorldView → Briefing → WorldView, Scope-/Layerwechsel,
Zeitwahl, Datumsgrenze/Pol, tatsächliches Canvas-Picking und Fehler/Recovery.
Kein Testzugriff auf einen geheimen Viewer oder injizierte Pickereignisse.
API-Fixtures und SwiftShader sind als solche zu kennzeichnen. Dichtefixtures
und Live-Dichte laufen getrennt; Live-Abdeckung muss aus tatsächlichen
Quellständen und Render-/Filtermengen nachvollziehbar sein.

Native GPU vor/nach auf derselben RTX 5090, Browser-/Treiberrevision,
Viewport 1920×1080, identischem Quell-Snapshot und identischem Kamerapfad:
10 Sekunden Warmup, anschließend drei Durchgänge à 30 Sekunden. RAF-Abstände
und Cesium-Frames getrennt erfassen. Ziel: p95 Frameabstand höchstens 33,3 ms,
Median mindestens 30 FPS; keine Verschlechterung um mehr als 10 % gegenüber
dem Vorherlauf. Fehlender Vorherlauf, fremde Last oder Software-Renderer macht
die Vergleichsaussage UNKNOWN. Keine FPS-Ableitung aus Symbolzahlen/Unitzeiten.

Menschliche Sichtprüfung mit Reviewer, Datum, Snapshot und Bildschirmbelegen:
Kontakte lesbar und auswählbar; Auswahl bleibt sichtbar; Aggregate sind als
Aggregate erkennbar; Labelüberlagerungen behindern keine Kernbedienung; Scope,
Zeit und veraltete/fehlende Daten werden richtig verstanden. Keine AI-Ratings.

Aktuelle Ausführungsgrenze: Preview-Listen und TCP sind durch EPERM blockiert.
Kein Browser-/Docker-/Netzwerkbypass. Keine produktiven Dienste oder lokalen
LLMs für diese Sourceprüfung ändern. Release-/GPU-/Human-Gates bleiben offen.

Der nächste Source-Slice begrenzt Graph-Events auf 250/600/1.500 Symbole in
GLOBE/REGIONAL/LOCAL. Auf Globehöhe werden gleichartige Events in 10-Grad-Zellen
mit exakter Mitgliederzahl aggregiert; Datumsgrenze und Pole werden explizit
behandelt. Die gewählte Einzel-ID bleibt Einzelobjekt. Aggregate tragen keine
Einzelereignis-ID, keinen erfundenen Zeitpunkt und keine versetzte Original-
koordinate als Faktenbeleg. Auswahl eines Aggregats führt zur Detailhöhe;
Einzel-Picking und Callout bleiben erst bei aufgelösten Einzelereignissen.
Zeitfensterfilterung erfolgt vor Aggregation. Zeitfading nutzt die stärkste
tatsächliche Mitgliederalpha, kein repräsentativer erfundener Zeitpunkt.
Schweregrad priorisiert die Menge und den ersten Stack-Labelvertreter.
Render-/Mitglieds-/Limit-/Viewport-/Zeit-/Fehlermengen müssen aufgehen.
