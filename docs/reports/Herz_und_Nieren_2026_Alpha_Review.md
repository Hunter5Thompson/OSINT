# Senior-Review und Fixentscheidung

Stand: 2026-09-27. Geprüfter Checkout: `374c5cc460ebea44ad27f0ddfe09a11fd2d57e83`, Branch `fix/live-feed-parser-resilience`.

Ausgangsdokument: [Herz_und_Nieren_2026_Alpha.md](Herz_und_Nieren_2026_Alpha.md). Umsetzung: [Arbeitsplan für ein kleineres LLM](../plans/herz-und-nieren-2026/README.md).

## Urteil

Der Bericht ist als Fehlerinventar gut brauchbar. Besonders wertvoll sind die konkreten Eingaben und die Trennung zwischen lokalen Proben und nicht ausgeführten Integrationstests. Die vorgeschlagene Reihenfolge unterschätzt allerdings Sicherheitsgrenzen und persistente Zustandsfehler. Außerdem bündeln mehrere Finding-IDs unabhängige Probleme; sie sind keine geeigneten Implementierungstickets.

Empfehlung: zuerst freien Cypher-Fallback absichern, Vision-Eingänge begrenzen, FIRMS-Koordinaten und Create-Recovery reparieren sowie Incident-Status und Rehydration stabilisieren. Danach analytische Fehlinterpretationen, Datenverluste und Frontend-Races. Ein kleines Modell kann die meisten lokalen Änderungen übernehmen, sofern Sollvertrag, Dateien und Negativtests vorher feststehen. DNS-Pinning, Datenbank-Nebenläufigkeit und die Umstellung des Orbitformats benötigen zusätzlich Senior-Review.

Es wurde ausschließlich analysiert und dieser Dokumentationssatz erstellt. Keine Produktivdaten, Dienste, Konfigurationen, Dependencies oder Implementierungen wurden geändert.

## Belegniveau und Baseline

- Der Berichtsstand `b619ad7` liegt hinter HEAD. Der Service-Diff betrifft nur `data-ingestion/graph_integrity/spatial_batch.py` und dessen Aircraft-Lane-Integrationstest; die hier behandelten Fehlerstellen sind dadurch nicht repariert.
- **P** in der Matrix: lokale, isolierte Probe in diesem Review zusätzlich ausgeführt. **C**: aktuelle Fehlerstelle und relevante Aufrufer im Code nachgelesen. **D**: fachliche/vertragliche Aussage muss separat entschieden oder belegt werden. Das sind keine Aussagen über vollständige Serviceabnahme.
- Proben liefen mit den vorhandenen Service-Python-Umgebungen und `PYTHONDONTWRITEBYTECODE=1`; keine Installation. F-01 wurde ausdrücklich als Produzent→Konsument-Roundtrip geprüft.
- Nicht ausgeführt: vollständige Test-Suiten, Browser, Live-Feed-Neuabzug, tatsächlicher Neo4j-Angriff, konkurrierende DB-Transaktionen, GPU-/LLM-Aufrufe. Live-Häufigkeiten aus dem Ausgangsbericht wurden nicht erneut gemessen.
- `git diff --check` war zu Beginn sauber. Vorhandene ungetrackte Dateien einschließlich Ausgangsbericht, `Handoff.md`, Onepager und TASK-114-Plan bleiben unberührt.

Lokale Ergebnisse:

| Probe | Ergebnis am Review-HEAD |
|---|---|
| `_build_map_url('2026-04-11', 48.1, 37.8)` → `_parse_firms_coords` | `(37.8, 48.1)` statt `(48.1, 37.8)` |
| Cypher mit Schreibklausel zwischen Quote-Kommentaren | Validator liefert `True` |
| Vision `.../images/../../outside.png` | URL-/Pfadvalidator akzeptiert |
| `_is_private_ip('100.64.0.1')` | `False` |
| Cypher mit String `'NO LIMIT'` | kein Limit ergänzt |
| Kabel-Feature `None` | `AttributeError` aus dem Fehlerhandler |
| Landing-Point mit `NaN` | Modell behält `nan` |
| Hotspot `name/region/description=None`, `LOW` | Textwerte `"None"`, Stufe `MODERATE` |
| `incident_key` mit −0 und +0 | unterschiedliche Strings; numerisch ist `-0.0 == 0.0` wahr |

## Wesentliche Korrekturen an Diagnose und Lösung

### F-15: READ_ACCESS ist keine Sicherheitsgrenze

Der Kommentar in `graph/client.py` und die vorsichtige Entwarnung im Bericht sind als Schutzannahme ungeeignet. Neo4j garantiert für den Routingmodus keine Schreibverweigerung. Compose verwendet `neo4j:5-community` und für Intelligence standardmäßig denselben `neo4j`-Account. Daraus folgt ein **P0-Sicherheitsrisiko**, kein bewiesener Live-Exploit. [Neo4j-Treiber: Request routing](https://neo4j.com/docs/python-manual/current/transactions/#request-routing)

Ein weiterer Regex oder nur zusätzliche verbotene Wörter sind keine robuste Lösung. Kurzfristig freien Cypher-Ausführungspfad standardmäßig abschalten, Template-Pfade weiter betreiben. Wiedereinschalten erst nach geprüfter Lexer/Parser-Strategie und echter DB-/Netzwerkbegrenzung. Eine `reader`-Rolle darf für Community nicht einfach vorausgesetzt werden; Edition und verfügbare Rechte sind Teil der Designprüfung. [Neo4j-Rechte und Editionen](https://neo4j.com/docs/operations-manual/current/authentication-authorization/)

### F-04/F-12: Pfadprüfung und Netzwerkausgang getrennt lösen

`resolve()` plus Verzeichniszugehörigkeit korrigiert Traversal und statische Symlink-Ausbrüche. Das reicht nicht als pauschale Aussage über race-sicheres Öffnen in von Dritten beschreibbaren Verzeichnissen. Öffnen muss auf dem validierten Ziel erfolgen, mit Größenlimit und klarer Symlink-Policy. Lokale Pfade gehören nicht in den öffentlichen Query-Vertrag; der Queue-Worker braucht eine eigene gebundene Wurzel.

Für Remote-Bilder reicht „CGNAT hinzufügen“ nicht. `is_global` zusammen mit Ausschluss von Multicast/Sonderadressen und Prüfung aller A-/AAAA-Adressen ist eine bessere Positivregel. Validierte IP und tatsächliche Verbindung müssen identisch bleiben; erneute DNS-Auflösung beim Download, Redirects und Umgebungs-Proxys dürfen das nicht umgehen. TLS-Hostname/SNI müssen dabei korrekt bleiben. [Python-IP-Semantik](https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_private)

Die Compose-Voreinstellung bindet Intelligence an Loopback; tatsächliche externe Erreichbarkeit wurde nicht geprüft. Das reduziert nicht die Notwendigkeit, den direkt erreichbaren Request-Typ und Toolpfad zu validieren.

### F-01: Zwei Fehler, und bestehende Daten bleiben falsch

URL-Koordinaten müssen als `(lon, lat)` gelesen und intern als `(lat, lon)` geliefert werden. Ein Roundtrip mit echter `_build_map_url` verhindert den bisherigen falsch-grünen Test.

Zusätzlich steht `IncidentCreateRequest(...)` in `cluster_store.handle` **vor** dem Create-`try`. Nach einer Validierungs-Exception bleibt `_reserving` gesetzt. Ein späterer Hit wird dann als Race verworfen. Nur `ignited` zurückzusetzen löst das nicht. Umgekehrt entscheidet der Store bei fehlendem Cluster selbst über Create: ein gewöhnlicher Persistenzfehler bedeutet nicht allein wegen `ignited=True` einen dauerhaft verlorenen Cluster. Recovery muss anhand der gesamten Kette getestet werden.

Ein Codefix repariert bereits vertauschte Incidents/Location-Kanten nicht. Historische Korrektur benötigt einen separaten, quellbelegten Dry-run; keine globale Lat/Lon-Tauschmigration.

### F-33: Transaktionale Mutation statt Ganzrecord-Upsert

Den Status aus einem Signal-Update zu entfernen ist notwendig, aber allein unzureichend: auch Timeline, Severity und Quellen können bei konkurrierenden Updates verloren gehen. Die Lösung braucht eine DB-seitig serialisierte Mutation mit Statusprüfung unter derselben Sperre und ein eindeutiges Ergebnis „angewendet / unverändert / nicht gefunden“. Ein Python-Lock schützt nicht gegen andere Prozesse. Status-SSE und Promoter-Zustand dürfen nur auf tatsächlich erfolgte Übergänge reagieren.

### F-02/F-07: Unbekannt ist kein Messwert

Sentinels einfach auf 0 oder 359 zu klemmen erzeugt weiterhin falsche Aussagen. Backendmodelle verlangen aktuell Zahlen; korrektes `null` braucht deshalb Parser-, Cache-, JSON-, TypeScript- und Anzeigeänderungen gemeinsam. Das Schiff/Flugzeug mit gültiger Position sollte erhalten bleiben. Keine Fortschreibung ohne die benötigten Messwerte; Anzeige „unbekannt“. Echte Nullen müssen erhalten bleiben. AISStream und Digitraffic sind beide betroffen.

### F-05/F-31: Produktregeln nicht als Parserfix verkleiden

Hotspot-`LOW → MODERATE` ist aktuell explizit gemappt, weil das öffentliche Modell `LOW` nicht kennt. Das ist eine fachlich diskutierbare Kompression, kein isolierter Tippfehler. Auch ein vollständiger Cache-Snapshot darf Defaults grundsätzlich ersetzen. Defaults und Updater haben unterschiedliche IDs; blindes Zusammenführen erzeugt Doppelungen und möglicherweise veraltete Hotspots. Separat entscheiden: Snapshot versus Patch, kanonische IDs, Stufenmodell und Fallback-Kennzeichnung.

Mehrere `scope`-Parameter werden im Code bewusst als ungültig behandelt. Der Rückfall auf Welt kann UX-seitig schlecht sein; „ersten/letzten Wert wählen“ wäre jedoch eine neue Mehrdeutigkeitsregel. Bestehende Scope-/Revisionsverträge erhalten, erst Sichtbarkeit des Fehlers entscheiden. Der SSE-Verlust während Reset ist dagegen ein klarer Fehler.

### F-20/F-22/F-30: Aussagekraft nicht überziehen

USGS-Nulltiefe erhöht eine Komponente des heuristischen Concern-Scores. Der Code beweist damit keine Oberflächenexplosion. Bei unbekannter Tiefe den davon abhängigen Concern-Score als unbekannt führen, reguläres seismisches Event erhalten; echte Tiefe 0 bleibt gültig.

ICAO-Länderzuweisung ist kein Nachweis einer Teilstreitkraft. Auch ein Callsign liefert allein keine sichere Flugzeugrolle. Unsichere Zuordnung muss unbekannt/generisch bleiben. Nicht durch andere unbelegte Präfixtabellen ersetzen; konkrete Zuteilungen nur mit überprüfbarer Primärquelle übernehmen. Die Detailbehauptungen über einzelne nationale Bereichsgrenzen wurden hier nicht unabhängig anhand eines Registers verifiziert.

### F-36: Alpha-5 ist nur Kompatibilität, keine CelesTrak-Lösung

Der Parser verliert Alpha-5-Eingaben tatsächlich anhand seiner Regex. Daraus folgt aber nicht, dass der aktuelle CelesTrak-TLE-Feed diese liefert. CelesTrak meldet explizit, dass neue sechsstellige Katalognummern nicht als TLE angeboten werden. Für diese Abdeckung ist GP-JSON/OMM nötig, einschließlich Backendmodell, Ingestion, Cache und Frontend-Propagation. Regex auf Buchstaben zu erweitern reicht nicht: auch Inklination, ID-Gleichheit und der Propagator müssen das Format verstehen. [CelesTrak-Formatvertrag](https://celestrak.org/NORAD/documentation/gp-data-formats.php)

## Vollständige Triage

P0 = zuerst beseitigen/eingrenzen; P1 = nächste Korrekturwelle; P2 = danach; P3 = belegte Härtung oder Produktentscheidung. Priorität beschreibt die Reihenfolge, nicht eine CVSS-Zahl. Geteilte Prioritäten gelten für Teilbefunde.

| ID | Beleg | Priorität | Bewertung / Fixentscheidung | Paket |
|---|---|---|---|---|
| F-01 | P/C | P0 | bestätigt; URL-Roundtrip plus getrennte Create-Recovery | I01, I02 |
| F-02 | C | P1 | bestätigt; Nullable-Vertrag statt Sentinel-Clamping | D01 |
| F-03 | C | P1 | WHERE an Event-MATCH; kaputte Koordinaten pro Row behandeln, echte DB-Probe | D03 |
| F-04 | P/C | P0 | bestätigt; zwei Trust Boundaries, DNS-Rebinding mitlösen | S02, S03 |
| F-05 | P/C/D | P2/P3 | Nulltexte falsch; Threat-/Snapshot-Policy separat | D06, X01 |
| F-06 | C/D | P2 | Token-/Fehlertext-Kanten bestätigt; DSP-Rolle nicht erfinden | D07 |
| F-07 | C | P1 | Herkunftsmesswerte nullable; Baro/Geom-Fallback, Kontaktzeit nicht erfinden | D02 |
| F-08 | P/C | P2 | Bool/NaN/Owner robust; Einheiten nur explizit umrechnen | D05 |
| F-09 | C | P1 | ein schlechtes Cache-Element darf gesamte Route nicht brechen | D04 |
| F-10 | P/C | P1/P2 | Limits sind Ressourcenvertrag; Intent getrennte Wortgrenzen | S01, L01 |
| F-11 | C | P2 | strip vor Fallback, Fail-closed bei beiden leer; kein Auth-Bypass | D09 |
| F-12 | C | P1/P0 | Schema-Fehler nicht als Erfolg merken; Workerpfad separat | S04, S02 |
| F-13 | C | P2 | höher als kosmetisch: eine Zeile unterdrückt weitere Feed-Events | D08 |
| F-14 | C/D | P2/P3 | Abdeckung ehrlich benennen; weltweiten Abruf nicht beiläufig einbauen | X02 |
| F-15 | P/C | P0 | Sicherheitsgrenze unterschätzt, freie Queries zunächst schließen | S01 |
| F-16 | C | P1 | explizite Assessment-Felder parsen; Wortgrenzen allein genügen nicht | L02 |
| F-17 | C | P1 | reservierte, gestartete, abgeschlossene Aufrufe unterscheiden | L03 |
| F-18 | C | P1 | Poison-Row isolieren; nichtendliche Scores vor Sortieren verwerfen | L04 |
| F-19 | C | P2 | echter Fortschrittsfehler, Defaults sicher; günstiger isolierter Fix | L05 |
| F-20 | C | P1 | Batchfehler und unbekannte Tiefe getrennt testen; Concern ≠ Explosion | D08 |
| F-21 | C | P1 | Zahl 0 erhalten; EONET-Geometriezeiten typisiert pro Event | D08 |
| F-22 | C/D | P1 | Zweigzugehörigkeit nur belegt; Zahlenblöcke nicht neu raten | D10 |
| F-23 | C | P1 | kürzester Longitude-Bogen, Endpunkte unverändert | U01 |
| F-24 | C | P1 | keine Breitengrad-Verlagerung durch Clamp; Anzeigeoffset statt Geofälschung | U02 |
| F-25 | C | P1 | Schritt aus angefordertem Zeitraster, nicht belegten Bins | U03 |
| F-26 | C | P1 | explizite interaktive Picks; Legacy-Datenfelder weiter erkennen | U04 |
| F-27 | C | P2 | vorhandene Datumsgrenzenlogik wiederverwenden; Grad/Radiant beachten | U01 |
| F-28 | C | P2 | Tick aus Cesium-Uhr, begrenzte Frequenz, sauberes Destroy | U05 |
| F-29 | C | P1 | Request-Generation plus Abort für alle genannten Hooks | U06 |
| F-30 | C/D | P1/P2 | alter Detailtitel P1; Rolle/Titelvertrag separat | U07, D10 |
| F-31 | C/D | P1/P3 | SSE-Reset-Race bestätigt; Scope-Mehrdeutigkeit Produktregel | U08, X03 |
| F-32 | C | P1 | last_seen vor Eviction initialisieren, Kapazitätsgrenze testen | I03 |
| F-33 | C | P0 | persistenter Statusverlust; Serialisierung und Übergangsergebnis | I04 |
| F-34 | C | P0 | Poison-Row tötet Auto-Promoter; Isolation plus sichtbarer Degraded-Zustand | I05 |
| F-35 | C | P1/P2 | Zeitparser getrennt von Markdownparser; kein now() auf Lesefehler | I06, L06 |
| F-36 | C/D | P1 | Parserhärtung jetzt, GP/OMM-Migration als eigenes Designpaket | D07, X04 |
| F-37 | P/C | P1 | sicherer Fehlerhandler und Cache-Miss bei kaputtem Root | D05 |
| F-38 | C | P1 | auch Timestamp-Konversion schützen; Zukunft nicht fresh | D11 |

F-03s WHERE-Auslegung entspricht dem [Neo4j-OPTIONAL-MATCH-Vertrag](https://neo4j.com/docs/cypher-manual/current/clauses/optional-match/). Es fehlt weiterhin eine ausgeführte DB-Regression; ein Stringvergleich im Mock ist keine semantische Abnahme.

## Acht unnummerierte Hinweise

Diese erhalten eigene IDs **A-01 bis A-08** und gehen nicht in „Restliches“ verloren. Codehinweise sind bestätigt; Persistenzwirkung/Livehäufigkeit noch nicht vollständig geprüft.

| ID | Hinweis | Entscheidung |
|---|---|---|
| A-01 | HAPI Nullzahlen / gemeinsame Document-URL | P1: Zeilenisolierung; Identitätskollision bis in `process_item` prüfen, dann stabile Record-Identität |
| A-02 | TLE-Updater ohne Checksumme/ID-Paarprüfung | P2: D07, gemeinsame Fixtures für beide Servicegrenzen |
| A-03 | Hotspot-Qdrantfehler wird 0 Erwähnungen | P1: Fehler ≠ Nulltreffer, keine automatische Absenkung bei Fehler |
| A-04 | NLM Claim-Entity-Link nur per Name | P1: Homonyme getrennt halten, Typ im Caller und Template; Historie separat prüfen |
| A-05 | GDACS falscher erster Severity-Wert | P2: nächste unterstützte Quelle versuchen, finite Werte verlangen |
| A-06 | GDELT unbekannter CAMEO-Root | P2: `map_cameo_root` gibt `None`; erst `filter.py` macht daraus `""`. Defekt bei ungemapptem erlaubtem Root; Standard-Allowlist prüfen |
| A-07 | FIRMS-Zeitstrings erzeugen verschiedene Hashes | P2: kanonische Zeit vor Hash; ID-Änderung braucht Alt-ID-/Dedupe-Strategie |
| A-08 | −0/+0 in `loc_key` | P2: unterschiedliche Formatstrings bestätigt. Behaupteter Bypass von `== 0.0` durch exaktes signed zero ist falsch; nahe-null Koordinaten separat testen |

A-01 und A-04 können dauerhafte Provenienz-/Identitätsfehler verursachen. Ihre Untersuchung gehört in die erste Datenwelle. Die konkreten Aufträge stehen in [06-followups.md](../plans/herz-und-nieren-2026/06-followups.md).

## Bewertung der vorgeschlagenen Arbeitsweise

Die elf Schritte am Ende des Ausgangsberichts sind eine Triage-Liste, kein ausführbarer Fixplan. Übernehmen: FIRMS früh, Regressionen an tatsächlichen Grenzen, getrennte Behandlung von Parser und Transport. Ändern: Security und Incident-Persistenz nach vorne; Null-/Schemaänderungen mit allen Verbrauchern; Live-Cypher-Semantik und DB-Races mit Integrationstests; Browserpflicht für sichtbare Cesium-/Interaktionsfehler. Nicht übernehmen: ein pauschales „Restliche Kanten“-Ticket, stilles Zurücksetzen auf 0/jetzt, globales Catch-and-ignore, oder Tests, die nur den neuen Implementierungstext bestätigen.

Tokenkosten sinken durch kleine Kontextpakete, feste Entscheidungen und reproduzierbare Tests. Ein großes Modell soll nur die drei schwierigen Grenzen S03/I04/X04 sowie strittige Produktverträge prüfen. Keine konkreten Kosteneinsparungen werden behauptet; dafür fehlen Laufmessungen. Der Plan benötigt keine zusätzlichen Agent-Frameworks und keine laufenden LLM-/GPU-Dienste für normale Regressionstests.
