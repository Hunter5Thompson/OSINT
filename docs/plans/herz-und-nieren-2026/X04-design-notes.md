# X04 — frühe Entscheidungsvorlage für GP-JSON/OMM

**Stand 2026-09-27: untersucht, Entscheidung und Umsetzung offen.** Read-only
Vorarbeit durch GPT-6-Luna, durch Senior gegen Lockfile, Verbraucher und primäre
Release Notes geprüft. Diese Notiz wird mit B01 mitgeführt; sie autorisiert weder
Abhängigkeitsupgrade noch Format-Cutover. D07 und U05 schließen X04 nicht ab.

## Bestätigter Ausgangspunkt

- Backend `app/models/satellite.py` verlangt `tle_line1` und `tle_line2`;
  `app/services/satellite_service.py` ruft `FORMAT=tle` ab und verwendet
  `satellites:tle` (7200 Sekunden). Die Satellitenroute liefert dieses TLE-Modell.
- Ingestion `feeds/tle_updater.py` ist ein separater TLE-Abrufpfad und schreibt
  `tle:group:{group}` sowie `tle:norad:{id}`. Das ist nicht derselbe Cache wie
  der Backend-API-Cache. Eine Zusammenlegung ist keine Voraussetzung dieses Fixplans.
- Frontend `src/types/index.ts` verlangt ebenfalls TLE-Zeilen;
  `SatelliteLayer.tsx` erstellt `SatRec` mit `twoline2satrec` und verwendet diesen
  für Position und Orbit. Ein Formatadapter kann vor dieser gemeinsamen Propagation sitzen.
- `services/frontend/package-lock.json` fixiert `satellite.js` auf **5.0.0**.
  Laut [Release Notes 6.0.0](https://github.com/shashwatak/satellite-js/releases/tag/6.0.0)
  kam `json2satrec` für OMM-JSON erst mit 6.0.0 hinzu. Dabei änderte sich der
  Fehlervertrag von `propagate` auf `null` statt falscher einzelner Positionsfelder.
  Der bestehende Verbraucher muss bei einem Upgrade gezielt angepasst werden.

## Empfehlung zur Entscheidung

Ein diskriminiertes Orbitmodell (`format: tle | omm`) bei gemeinsamen Metadaten
wie NORAD-ID und Name; TLE-Zeilen verlustfrei beibehalten, keine künstlichen
fünfstelligen IDs oder synthetischen TLE-Zeilen für OMM. Der Frontendadapter
übersetzt beide Varianten nach `SatRec`. Das konkrete OMM-Feldschema gegen
[CelesTraks GP-Formatvertrag](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
und die dann qualifizierte Bibliotheksversion prüfen.

Reader und API zuerst kompatibel erweitern, alte TLE-Clients weiter bedienen;
Frontendadapter und beide Propagationsfälle prüfen, bevor OMM-only Datensätze
für diese Verbraucher veröffentlicht werden. Neue Cachegeneration explizit
versionieren und von alten TLE-Einträgen unterscheiden. Produzenten/Cutover erst
nach erfolgreicher Ende-zu-Ende-Abnahme umstellen. Kein globales Cache-Löschen.
Die zwei vorhandenen Abrufpfade zunächst erhalten; gemeinsame Semantik über
Fixtures nachweisen. Ablauf in X04a–d und nötige PR-Grenzen vor Implementierung
festlegen; kompatible Zwischenstände und Rückfallweg sind Abnahmekriterien.

Offen bleiben: Freigabe des GP-JSON/OMM-Zielformats, konkrete qualifizierte
Bibliotheksversion, API-Übergangsvertrag, Cacheversion/TTL/Fallback sowie
Cutover-/Rollback-Bedingungen. B13 richtet U05 an dem vorher festgelegten
Formatadapter aus; diese Notiz allein ist keine Formatfreigabe.

## Erforderliche Nachweise vor Cutover

Sechsstellige NORAD-ID vom Feed bis zur sichtbaren berechenbaren Position;
bisheriger ISS-TLE bleibt korrekt. Referenzepoche/-position mit benannten
Einheiten, UTC und Toleranzen; beide Decoder und Propagationsfehler; ungültige
Einzelzeile neben gültigen, ungültiger Root, Transportausfall und Teilgruppen;
alte/neue Cachegeneration sowie alte API-Clients. HTTP 200 oder eine erfolgreich
geparste JSON-Datei beweisen weder Propagation noch vollständige Abdeckung.
