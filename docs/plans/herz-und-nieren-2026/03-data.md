# Daten-Pakete

Gemeinsamer Vertrag: [README](README.md). Backendpfade relativ zu `services/backend`; andere Services explizit benannt. M-Pakete mit mehreren Quellen als getrennte Unterläufe ausführen.

## D01 — AIS-Messwerte unbekannt statt Sentinel

**F-02 · P1 · M.**

**Scope:** Backend `app/services/vessel_service.py`, `app/models/vessel.py`, `tests/unit/test_vessel_service.py`; Frontend Vessel-Typ in `src/types/index.ts`, `src/components/layers/ShipLayer.tsx`, Vessel-Details in `src/components/globe/EntityClickHandler.tsx` und unmittelbare Geschwindigkeits-/Kursverbraucher. Diese mit gezieltem `rg 'speed_knots|\.course' src` ermitteln und Scope vor Edit auflisten.

**Soll:** `speed_knots`/`course` nullable. SOG 102.3 und ungültige/nonfinite/negative Werte → null; COG außerhalb `[0,360)` → null. Echte 0 und gültige Obergrenzen erhalten. 102.2 ist ein AIS-Sättigungswert, nicht als „nicht verfügbar“ wegwerfen. Dieselbe Normalisierung für Digitraffic, AISStream und alte Cache-Rows. Gültige Positionen erhalten.

**RED/Abnahme:** `102.3`, `360`, fehlend, 0, 359.9, `NaN`, Infinity, normale Werte aus beiden Quellen und Cache; API-JSON enthält null. UI zeigt unbekannt, keine berechnete Bewegung ohne ausreichende Werte, neutrales Symbol bei unbekanntem Kurs. Nicht einfach `?? 0` in Details oder Dead-Reckoning einfügen. Frontend-Typcheck und Browserfall mit einem unbekannten und einem fahrenden Schiff.

## D02 — Flugmesswerte und Kontaktzeit korrekt behandeln

**F-07 · P1 · M · nach D01 integrieren.**

**Scope:** Backend `app/services/flight_service.py`, `app/models/flight.py`, `tests/unit/test_flight_service.py`; Frontend Aircraft-Typ und direkte `heading/altitude_m/velocity_ms/vertical_rate/last_contact`-Verbraucher, FlightLayer und Details.

**Soll:** fehlender Kurs/Vertikalrate/Geschwindigkeit/Kontakt nullable, keine 1970-/jetzt-Erfindung. Null-`alt_baro` → gültiges `alt_geom`; Ground-Sentinel case-insensitive nur für Strings erkennen, Bodenhöhe 0 korrekt. Fehlende Höhe bleibt unbekannt. OpenSky-Zeitquelle nach Feldvertrag wählen, keine beliebige Zeit ersetzen. FR24 ohne Vertikalrate liefert null.

**RED:** OpenSky None-Kurs/-Kontakt, echte Kurs-0; adsb Ground/ground, null/fehlendes Baro mit 35000 ft Geom, Baro=0 mit Geom ungleich 0; nichtendliche Werte; FR24. Cache- und UI-Verträge einschließen. Unbekannte Höhe darf im Renderer eine definierte technische Platzierung haben, aber niemals als gemessene 0 m angezeigt werden. Keine Rolle aus fehlender Höhe/Geschwindigkeit ableiten. Zieltests plus Typcheck/Browser-Smoke.

## D03 — Geo-Events vor Optional-Location filtern

**F-03 · P1 · M.**

**Scope:** `app/routers/graph.py`, `app/models/events.py`, vorhandene Graph-Routertests, neuer isolierter Neo4j-Fixturetest.

**RED:** mehr aktuelle Nicht-Militär-Events als LIMIT plus älteres militärisches Event, jeweils mit/ohne Location und mit/ohne Entity-Filter. Gefilterte Antwort enthält ausschließlich passende Events und verliert das ältere nicht wegen fremder Rows. Test mit realer Cypher-Auswertung, nicht nur WHERE-Substring.

**GREEN:** Event-`WHERE` unmittelbar an Event-MATCH binden, danach OPTIONAL MATCH. Kaputte Location-Koordinate macht das Koordinatenpaar null und liefert das Event ohne Geometrie; echte 0 erhalten. Paarweise finite Bereichsprüfung, keine halben Koordinaten/NaN. Parameterbindung und Limit erhalten. Semantisch weiterhin „Event mit optionalem Ort“, nicht still auf INNER JOIN ändern. Mehrfach-Locations als bestehende Kardinalitätsgrenze dokumentieren, kein ungeplantes Datenmodell-Redesign.

## ~~D04 — Cache-Rows von FIRMS/EONET/GDACS isolieren~~ — GEMERGT

**Review 2026-09-27, B02 / PR #135:** Implementierungscommit `dd8d0af`; keine offenen Findings. Gemischte Cachelisten behalten valide Nachbarn und reparieren den Cache mit bestehender TTL; falsche Roots und vollständig ungültige Listen lösen gezielte Recovery aus. Gültiges `[]` bleibt Cachetreffer, Qdrant-Ausfälle bleiben 503. Finite Messwerte und Koordinatengrenzen geprüft.
Gemeinsame B02-Abnahme: 106 fokussierte Tests; unabhängig 821 Backend-Tests mit
`NEO4J_URL=bolt://127.0.0.1:1`, Ruff, Mypy (91 Dateien) und Diff-Check grün.
Keine Livefeeds oder Produktionsdatenzugriffe; alle 13 PR-Checks grün, PR #135 gemergt als `6742481`. Kein Deployment.

**F-09 · P1 · S je Router, drei Unterläufe.**

**Scope:** `app/routers/{firms,eonet,gdacs}.py`, `tests/unit/test_{firms,eonet,gdacs}_router.py`.

**RED:** gemischte gültig/ungültig-Liste, `None`-Element, falscher Roottyp, ausschließlich ungültige Liste, gültiges `[]`. Gesunde Rows weiter HTTP 200, ungültiger Gesamtsnapshot fällt auf bestehenden Datenpfad zurück. Echter Qdrant-Ausfall wird nicht zu gesundem Leerresultat.

**GREEN:** pro Modell validieren, schmale Exceptions, Diagnose/invalid-count, kaputten Cache-Key gezielt invalidieren oder gültigen Teil nach vorhandener TTL-Policy ersetzen. Gültiges leeres Array beibehalten, damit Nulltreffer nicht dauernd Qdrant abfragen. Keine automatische Übernahme des Vessel-„empty is miss“-Sondervertrags. Kein generisches Cacheframework bauen.

## ~~D05 — Kabel-Parser und Cache-Recovery~~ — GEMERGT

**Review 2026-09-27, B02 / PR #135:** Implementierungscommit `dd8d0af`; keine offenen Findings. Cache-Recovery, gültige leere Datasets, isolierte Null-/Strukturfehler und Live-Nachbarn geprüft. Ungültige Segmente einschließlich nichtendlicher Zusatzkoordinaten und Zahlenüberläufe verlieren keine validen Nachbarsegmente. Bool-/Owner-/Einheitenregeln sowie Gbps- und nmi-Konversion geprüft.
Gemeinsame B02-Abnahme: 106 fokussierte Tests; unabhängig 821 Backend-Tests mit
`NEO4J_URL=bolt://127.0.0.1:1`, Ruff, Mypy (91 Dateien) und Diff-Check grün.
Keine Livefeeds oder Produktionsdatenzugriffe; alle 13 PR-Checks grün, PR #135 gemergt als `6742481`. Kein Deployment.

**F-08/F-37 · P1 für Ausfälle, P2 Attribute · M; Unterläufe Root/Recovery, dann Attribute.**

**Scope:** `app/services/cable_service.py`, `app/models/cable.py`, `tests/unit/test_cable_service.py`, `test_cables_router.py`.

**RED:** `[good, null, good]`, `properties=null`, `geometry=null`, falscher Cache-Root `[]`, Dict ohne `landing_points`, kaputte Cache-Zeile. Logging darf selbst nicht werfen. Valide Live-Nachbarn bleiben `source=live`, kein gesamter Fallback wegen einer Zeile.

**Attribute:** explizite Booltabelle für true/false, 1/0 und deren Strings; unbekannt → konservativer bestehender Default mit Diagnose. Ownerliste nur aus gültigen Strings joinen, unbrauchbares optionales Feld → null, Kabel behalten. Koordinaten aller Landing-Points/Leitungssegmente finite und im Bereich; ein ungültiges Segment nicht als Null-Island ersetzen. `12 Gbps → 0.012 Tbps`, `500 nmi → 926 km`, vorhandene km/Tbps-Formate erhalten; unbekannte Einheit null, keine numerische Präfix-Extraktion. Negative/nonfinite Längen/Kapazitäten zurückweisen.

**GREEN/Abnahme:** strukturvalidierter Cache, beschädigter Root ist Miss mit anschließendem Live/Fallback-Refresh und korrektem `source`. Gültige leere Datasetstruktur explizit von Korruption unterscheiden. Alle Parser-/Routertests; keine externen Kabeldaten nötig.

## D06 — Hotspot-Nulltexte bereinigen

**F-05 Textteil · P2 · S.**

**Scope:** `app/routers/hotspots.py`, `tests/unit/test_hotspots_router.py`.

**RED:** id/name None, leere/Whitespace-Identität, region/description None, echte Strings. Ungültige Pflichtidentität entfernt nur diese Row; optionale Texte werden leer statt `"None"`.

**GREEN:** Typ- und Leerheitsprüfung vor Stringifizierung. Bestehende Koordinatenvalidierung und Quellenbehandlung erhalten. **Keine** neue LOW-Stufe oder Default/Cache-Mischung: X01 entscheidet das fachlich. Taiwan-Punkt nicht ohne dokumentierte Ortsreferenz verschieben; Teil von X01.

## D07 — Satelliten-Token und TLE-Grammatik härten

**F-06/F-36 Parser, A-02 · P2 mit P1-Abdeckungsfolge X04 · M; Unterläufe Klassifikation, Backendparser, Updater.**

**Scope:** Backend `app/services/satellite_service.py`, `tests/unit/test_satellite_service.py`; Ingestion `feeds/tle_updater.py`, dazugehörige Tests (bei Bedarf neu). Propagator-Verbraucher nur lesen; GP/OMM nicht hier implementieren.

**RED:** AGPS/USES keine GPS/SES-Treffer; QZS und QZSS korrekt nach expliziter Aliasliste; AEHF/MUOS als belegte militärische Comms-Familien, DSP nicht pauschal recon. ISS/SWISSCUBE/MISSION behalten bestehende Regressionen. Name-Token und Separatoren testen.

**Parser:** Name+1+2, nacktes 1+2-Paar mit deterministischem Ersatznamen, gemischte Formate/Leerzeilen, `not updated`-Kommentar plus gültige Paare, ausschließlich Fehlertext; keine TLE-Zeile als Namen verwenden. Feste Spalten für Katalog-ID/Elemente, übereinstimmende IDs beider Zeilen, Checksumme und Zahlenbereiche. Alpha-5 nur mit geprüftem Decoder und Propagator-Kompatibilität akzeptieren; sonst ausdrücklich unsupported diagnostizieren. Buchstaben-Regex allein reicht nicht.

**Abnahme:** gleiche valid/invalid Fixturematrix in getrennten Services. Vollständig unbrauchbare erwartete Gruppe als Parsefehler behandeln; bei gesunden anderen Gruppen Teilergebnisse mit Diagnose, bei ausschließlich Fehlern Upstream-Fehler statt unkommentiertem `[]`. Legitime leere Quelle als eigenen Fall festlegen. Keine Behauptung weltweiter/neuer Katalogabdeckung vor X04.

## ~~D08 — Ingestion-Poison-Rows und unbekannte Werte~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27, B03 / PR #136:** Implementierung `f4988aa`; keine offenen Findings. RSS isoliert fehlerhafte optionale Content-Felder und behält Summary/Nachbarn. USGS bewahrt unbekannte Tiefe samt Concern-Nullwerten bis zu Qdrant-/Neo4j-Schreibparametern; echte Tiefe 0 und Millisekundenstrings bleiben gültig. UCDP unterscheidet unbekannte Werte von numerischer Null und isoliert fehlerhafte Rows. EONET wählt gültige Point-Geometrien nach UTC-Zeitpunkt und meldet beschädigte Geometrien aggregiert. Eigene RED/GREEN-Unterläufe; vorhandene Provenienzverträge grün. Gemeinsame unabhängige Abnahme: 1669 Ingestion-Tests bestanden, ein bestehender Dev-Compose-Test ausgelassen, 23 Live-Tests standardmäßig ausgeschlossen; Ruff und Diff-Check grün. Keine Livefeeds, Produktionsschreibtests oder Deployment.

**F-13/F-20/F-21 · P1, RSS P2 · vier getrennte S-Aufträge.**

**Scope:** Data-Ingestion `feeds/rss_collector.py`, `usgs_collector.py`, `ucdp_collector.py`, `eonet_collector.py` und `tests/test_*_collector.py`. Je Lauf nur eine Quelle ändern.

- **D08a RSS:** Content-Zugriff in Per-Entry-Grenze; Mapping/Listentypen prüfen, bei kaputtem optionalem Content auf gültige Summary zurückfallen. `[good,bad,good]` verarbeitet beide guten Nachbarn; `content=[42]`, null und `[]` testen.
- **D08b USGS:** Nulltiefe bleibt null, davon abhängiger Concern-Score/-Level ebenfalls null; reguläres Event bleibt erhalten. Echte Tiefe 0 bekommt unveränderte Berechnung. Pflichtzeit validieren/normalisieren: Sourcevertrag Millisekunden, numerische Strings bewusst erlauben, kaputte/fehlende Zeit verwirft nur dieses Event. Endliche Koordinaten/Magnitude, keine 1970-Substitution. Nulltiefe nahe Teststandort, string-Zeit, kaputte Zeit zwischen zwei gültigen Events und Qdrant-/Neo4j-Payload testen.
- **D08c UCDP:** `None`/leer getrennt von 0; 0, 0.0 und `"0.0"` identisch, Bereiche/finite prüfen. Ein ungültiges Element stoppt keinen Lauf.
- **D08d EONET:** vor `max` Point-Geometrien mit gültigem UTC-Datum auswählen; Null/kaputte Daten pro Geometrie ignorieren, tatsächliche Zeit statt Stringlexikografie vergleichen. Kein gültiger Point → dieses Event auslassen. Zwei Events mit einem Null-Datum im ersten dürfen zweites nicht verlieren.

**Abnahme:** vorhandene Payload-/Spatial-Provenienztests pro Quelle mitlaufen lassen. Nicht Backend-Parser mit ähnlich benannten Ingestion-Parsern verwechseln.

## D09 — Admin-Fallback nach Normalisierung

**F-11 · P2 · S.** Backend `app/routers/reports.py`, `almanac.py`, `app/admin_auth.py`; `tests/unit/test_admin_auth.py` und zugehörige Routertests.

**RED:** Reports-Token nur Whitespace + gültiges Incident-Token akzeptiert korrektes Ersatz-Token; beide leer → 503; falsches Token bleibt 401/403 nach aktuellem Vertrag; explizites gültiges Reports-Token gewinnt. Secretwerte weder in Testsnapshots noch Logs.

**GREEN:** konfigurierte Kandidaten vor Auswahl strippen; kleinen gemeinsamen Selector nutzen, wenn beide Router denselben Vertrag teilen. Vergleichs-/Fehlersemantik des bestehenden Guards erhalten. Kein neues Authsystem.

## D10 — Militärzugehörigkeit und Iconrolle nur aus tragfähigen Signalen

**F-22/F-30 Klassifikation · P1 · M; Ingestion und Frontend getrennte Unterläufe.**

**Scope:** Ingestion `feeds/military_aircraft_collector.py`, `tests/test_military_aircraft_collector.py`; Frontend `src/components/layers/icons/aircraftIcons.ts`, direkte Iconverbraucher und Tests.

**Soll:** ohne belastbaren Einzel-/Teilbereichsnachweis `identify_branch` → None; nationale Zuteilung ergibt keine Teilstreitkraft. Bestehende unabhängige militärische Upstreammarkierung darf erhalten bleiben. Keine neuen ungesicherten Bereiche raten. Ob Code/DB alte Branchwerte bei None beibehält, explizit prüfen; historische Falschlabels separat inventarisieren.

**RED:** zivile Beispieladressen aus berichteten Länderblöcken bleiben ohne Branch; verifizierte militärische Fixture bleibt korrekt. Frontend bekannte Typcodes priorisieren; VIPER/RAPTOR/HAWK/COBRA allein kein Transportnachweis; langsam/niedriges unbekanntes Militär kein automatischer Fighter. Neues neutrales `military_unknown`-Icon mit vollständigem Union/Switch/Cache-Vertrag. Callsign-Heuristiken nicht als Identitätsbeweis behandeln. Tests plus Browservergleich neutral/known/civilian.

## ~~D11 — Feed-Freshness pro Quelle fehlertolerant~~ — GEMERGT

**Review 2026-09-27, B02 / PR #135:** Implementierungscommit `dd8d0af`; keine offenen Findings. Ungültige Sekundenepochen einschließlich Bool, Millisekunden, NaN/Infinity und Überlauf bleiben quellenisoliert unknown. Benannte Zukunftstoleranz 60 Sekunden; Grenzen 60/61 Sekunden geprüft. Gesunde Nachbarquellen bleiben erhalten; Root-Infrastrukturfehler weiterhin 503.
Gemeinsame B02-Abnahme: 106 fokussierte Tests; unabhängig 821 Backend-Tests mit
`NEO4J_URL=bolt://127.0.0.1:1`, Ruff, Mypy (91 Dateien) und Diff-Check grün.
Keine Livefeeds oder Produktionsdatenzugriffe; alle 13 PR-Checks grün, PR #135 gemergt als `6742481`. Kein Deployment.

**F-38 · P1 · S.** `app/services/feed_freshness.py`, `tests/unit/test_feed_freshness.py`, `test_feed_health_router.py`.

**RED:** gültiger Sekundenepoch, Millisekundenwert, `NaN`, Infinity, bool, kaputter String, zu große Zahl, Zukunft. Fehler einer Quelle lässt alle anderen Ergebnisse bestehen. Millisekunden nicht still konvertieren: Feldvertrag `ingested_epoch` ist Sekunden.

**GREEN:** komplette Konversion einschließlich `fromtimestamp` in Fehlergrenze; finite/Typ-/Plausibilitätsprüfung. Zukunft außerhalb expliziter kleiner Clock-Skew-Toleranz (im Test fest, z.B. 60 s) → unknown mit Reason, nicht fresh; innerhalb Toleranz age 0 erlaubt. Toleranz als benannte Regel dokumentieren. Gesamtstatus degraded sobald eine Quelle nicht fresh. Root-Infrastrukturfehler bleibt bestehendes 503, sofern schon vor Einzelabfragen festgestellt.
