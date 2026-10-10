# GP-Orbitreader — lokaler Zwischenstand vom 10.10.2026

Der additive Backendreader und der Frontendadapter sind implementiert. Dies ist
die Reader-/Propagatorstufe von DEC-005, noch kein G05-/B13-/D07-/U05-Abschluss
und kein produktiver Release. Die bestehende WorldView-Seite ruft weiterhin den
Legacy-Endpunkt ab; der Anschluss an die Cesium-Uhr und die Produzenten folgt.

## Vertrag und Verantwortlichkeit

- `/api/satellites` und seine Antwortform bleiben erhalten. Der neue Endpunkt
  `/api/satellites/orbits` liefert `schema_version: 1`, UTC-Abrufzeit, volle
  numerische Katalog-ID, diskriminierte TLE-/OMM-Elemente und Gruppenabdeckung.
- `complete` beschreibt ausschließlich die konfigurierten Abrufgruppen. Eine
  gesunde Nachbargruppe bleibt bei Teilfehlern erhalten. Defekte Einzelzeilen
  werden nach Index und `invalid`/`unsupported` gezählt; ausschließlich defekte
  Gruppen ergeben 502. Ein gültiges `[]` ist separat cachebar.
- Neuer Redis-Key `satellites:orbits:v1`, TTL 7200 Sekunden. Cachelesen erhält
  den tatsächlichen Abrufzeitpunkt; Version, Katalog-/Orbitkonsistenz, UTC,
  Checksummen und widersprüchliche Zähler werden geprüft. Keine Migration oder
  Löschung alter Keys. Duplikate behalten den neuesten Elementzeitpunkt.
- `CELESTRAK_GP_URL` konfiguriert den neuen HTTP-Quellpfad; `FORMAT=JSON` ist
  ausdrücklich gesetzt. Der bisherige TLE-Vertrag wird dadurch nicht umgestellt.
- `shared/orbit_elements.py` besitzt die GP-/TLE-Paargrammatik. Zwei bytegleiche
  Kopien halten Python-Services eigenständig paketierbar. Ops prüft Gleichheit
  und Docker-/Wheelkontexte. Beide Servicegrenzen nutzen dieselbe Fixturematrix.
- GP unterstützt EARTH/TEME/UTC/SGP4. Nur die ausdrücklich redundanten CelesTrak-
  Metadaten werden ergänzt. Werte bleiben endlich, Winkel in Grad, Mean Motion
  in Umdrehungen/Tag. Zeitpräzision bis Mikrosekunden wird erhalten; fehlende
  Stunden-/Minuten-/Sekunden und still abgeschnittene Präzision werden abgelehnt.
- Alpha-5 bleibt ausdrücklich unqualifiziert. Der TLE-Paarreader prüft feste
  Spalten, Prüfziffern, gleiche positive IDs, Kalender/Epoche, Exponenten und
  physikalische Elementbereiche. Die bisherigen TLE-Textproduzenten verwenden
  ihn noch nicht; Namen/bare pairs, Diagnosefluss und D07-Klassifikation folgen.
- Der Frontendreader nimmt `unknown` entgegen und hält eigene Zeilenfehler
  getrennt von serverseitiger Quellenabdeckung. Er verwirft komplett beschädigte
  Antworten. `SatelliteRecordCache` initialisiert pro Elementdatensatz; der
  Zeitadapter isoliert `null`, ungültige Zeit und nicht endliche Lösungen.

## Unabhängige Zahlenprüfung

Referenz: getrennte Umgebung mit `sgp4==2.27`, tatsächlich aktiviertem C++-Pfad,
WGS72 und TEME km/km/s. Herkunft und Originalzeilen liegen in
`tests/fixtures/satellites/sources.json`. Der gültige ISS-Input stammt exakt aus
der veröffentlichten Paketbeschreibung; beide Prüfziffern sind verifiziert.
Das CelesTrak-Original für 100651 stammt aus dem eingefrorenen 227-Zeilen-Feed
vom 09.10.2026 23:06 UTC. Bestehende synthetische Parserfixtures wurden nicht
als authentische Originale repariert oder ersetzt.

Zehn feste UTC-Zeitpunkte (ISS und 100651, Start/-1h/+1h/+24h/+7d) gegen den
unveränderten Paketkandidaten 7.1.0: maximal 0.002938344364852349 km und
0.0000032364853625413865 km/s Abweichung. Vorab festgelegte Grenzen:
0.01 km / 0.00001 km/s. UTC-/Berlin-Ergebnisse sind identisch. Die beobachtete
Abweichung ist mit der bekannten Date-Millisekundenauflösung vereinbar; daraus
wird keine physische Positionsgenauigkeit oder aktuelle ISS-Verifikation.
Separat wird die Geodätik→Cesium-Meter-Umrechnung gegen den rotierenden ECF-
Vektor auf unter 0.01 m Rundungsdifferenz geprüft. Dies ist kein EOP-/ITRF-Beleg.

`satellite.js` ist exakt 7.1.0 gepinnt. Nur dessen Locknode und Rootmetadaten
wurden geändert, alle anderen bestehenden Nodes sind bytegleich. Ein echter
Baseline-Lauf gegen das separat gesicherte 5.0.0-Paket besteht die fünf ISS-
Vektoren und scheitert an allen fünf GP-Vektoren wegen fehlendem JSON-Decoder.

## Buildgrenze statt optionaler WASM-Runtime

Der reguläre Vite-Build scheiterte nach dem Upgrade am vom Haupteinstieg
mitexportierten optionalen pthreads-WASM-Loader (IIFE/top-level await). Das
Problem des gemeinsamen Haupteinstiegs ist auch beim
[Upstream-Repository dokumentiert](https://github.com/shashwatak/satellite-js/issues/191).
Ein kleiner Vite-Loader entfernt ausschließlich dessen einzelne optionale
WASM-Barrelzeile aus dem geladenen 7.1.0-Einstieg. Er ändert keine Dateien in
`node_modules` und keine Mathematik. Pin/unerwartete Exportform brechen den Build
ab. Dev/Test/Build verwenden denselben JavaScript-Einstieg; der reguläre Build
ist damit grün. Nach qualifiziertem öffentlichen Upstream-JS-Einstieg entfernen.

## Nachweise und Grenzen

Artefakte: `/data/odin-goals/2026-10-09-repo-hardening/evidence/G05`. RED/GREEN-
Logs, Quellenhashes, eingefrorene Pakete, Referenzskripte, Lockdelta und sämtliche
Probeversuche bleiben erhalten. Falscher erster Fixture-Importpfad, ESM-Spy-
Konfiguration, Test-URL-Schema und ein fehlendes Host-`python` sind Harness-/
Aufruffehler; sie zählen nicht als fachliche REDs. Korrigierte Verhaltens-REDs
stehen in eigenen Logs. Kein Testskip oder gelockerter Sollwert dafür.

Quelltests: Backend 987; Frontend 735 in 124 Dateien; Ingestion 1720 plus ein
bestehender Skip/23 opt-in Deselections; Ops 100. Backend-Ruff/Mypy (95 Dateien),
betroffene Ingestion-/Ops-/Shareddateien, ESLint/App-/Browser-TypeScript und
regulärer Frontendbuild grün. Ein zusätzlicher sauberer Commit-/Image-/Browser-
Nachweis wird außerhalb dieses versionierten Quellenberichts als eigener
Checkpoint gespeichert; vorherige Probe-Builds mit alter SHA sind kein Release.

Offen: D07-Textparser/Klassifikation, GP-Produzenten und Cachegenerationen beider
Fetchpfade, U05-Cesium-Uhr/Lifecycle/LOD, Hook-/UI-Diagnosen, tatsächliche sichtbare
API→Globe-Kette für 100651, fachliche/physische und menschliche Abnahme,
freigegebener produktiver Release. Kein Main-Merge/Push/PR/Deployment oder
Produktivdatenwrite aus diesem lokalen Zwischenstand ableiten.
