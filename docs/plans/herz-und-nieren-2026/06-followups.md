# Zusätzliche Hinweise, Designentscheidungen und Datenreparatur

Gemeinsamer Vertrag: [README](README.md). A-Pakete enthalten konkrete Repro-Gates: zuerst reproduzieren, dann minimal korrigieren. X-Pakete sind **Designaufträge**, keine bereits freigegebenen Produktänderungen. Das kleine Modell soll hier eine knappe Entscheidungsvorlage liefern und keine Architektur erfinden.

## ~~A01 — HAPI-Zahlen und Identität~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27, B03 / PR #136:** Implementierung `f4988aa`; keine offenen Findings. Nullwerte bleiben unbekannt; kaputte Zahlen und Identitätsfelder werden pro Record isoliert. Kanonischer vorhandener Record-Hash wird bis zur Event-Identität durchgereicht; separate namespaced Document-ID bei MERGE, MENTIONS und DESCRIBES. Pipeline-Cypher-Capture belegt verschiedene Länder/Monate/Eventtypen bei gleicher URL und gleichem Eventtitel sowie stabiles Retry. Legacy-URL-Vertrag und ID-Guard geprüft. Constraint ausschließlich deklarativ vorbereitet; keine ausgeführte Datenbankmigration oder historische Reparatur.
Gemeinsame unabhängige Abnahme: 1669 Ingestion-Tests bestanden, ein bestehender Dev-Compose-Test ausgelassen, 23 Live-Tests standardmäßig ausgeschlossen; Ruff und Diff-Check grün. PR-CI und Merge separat prüfen; kein Deployment.

**Unnummerierter Hinweis 1 · P1 · M, zwei Unterläufe.** Data-Ingestion `feeds/hapi_collector.py`, `pipeline.py` nur Identitäts-/Dedup-Aufrufer lesen, zugehörige Tests neu/erweitern.

**RED:** `events=null`, `fatalities=null`, fehlerhafte Zahlen zwischen gesunden Records/Ländern. Fehlend ist nicht nachweislich null Todesfälle; je Feldvertrag null erhalten oder diesen Aggregate-Record diagnostiziert auslassen. Kein kompletter Länderabbruch.

**Identitäts-Repro:** zwei Länder, Perioden und Eventtypen durch gemocktes `process_item`/Document-Upsert bis Identität verfolgen. Gemeinsame API-URL darf als Provenienzlink bleiben, aber darf unabhängige Reports nicht zusammen deduplizieren/überschreiben. Fix erst nach belegtem Identity-Pfad: kanonischer Record-Key aus Land+Periode+Eventtyp; Quell-URL und Identität getrennt, keine zufällige Querystring-ID erfinden. Neue Contractfixture und betroffene Pipeline-/Writer-Tests. Historische Collisions separat inventarisieren.

**B03-Identitätsentwurf (2026-09-27):** Der vorhandene Hash aus Land/Monat/Eventtyp bleibt die Qdrant-Dedup-ID und wird zusätzlich als Event-Identitätsbasis an die Pipeline übergeben. `hapi:conflict-events:<hash>` ist die separate Document-ID; die echte API-URL bleibt Quellenlink. Nur der explizite HAPI-Pfad verwendet `Document:HAPIDocument {doc_id}` bei MERGE und allen zugehörigen MATCH-Schritten. Andere Collector-Aufrufer behalten ihren URL-Vertrag. Die scoped Uniqueness-Constraint wird als operator-run Migration vorbereitet; vor parallelen HAPI-Schreiben muss sie separat angewandt und geprüft werden. Dieser PR führt keine Live-DDL aus. Bereits vorhandene Qdrant-Punkte bleiben dedupliziert und historische zusammengeführte Graph-Dokumente unverändert; R01 bleibt separat.

## A02 — TLE-Checksumme und Paar-ID

**Unnummerierter Hinweis 2 · P2.** Vollständig in **D07** enthalten, kein zweiter Patch. Beide Serviceparser mit gemeinsamem Fixturesatz prüfen; gültige Checksumme mit absichtlich unterschiedlicher ID muss ebenfalls abgelehnt werden. Keine Livefeed-Häufigkeit behaupten.

## A03 — Fehlende Hotspot-Messung darf Stufe nicht senken

**Unnummerierter Hinweis 3 · P1 · S.** Data-Ingestion `feeds/hotspot_updater.py`, neuer/benachbarter Updatertest.

**RED:** Qdranttimeout ist unterscheidbar von erfolgreichem Ergebnis 0; Timeout senkt keine Stufe. Gesunder 0-Fall behält bisherige Policy. Gemischter Lauf beschädigt nicht alle Hotspots.

**GREEN:** Queryfehler als unbekannt/Exception bis Entscheidungsstelle, vorherigen gültigen Record erhalten; ohne Vorwert kuratierte Basis plus bestehend kompatible Degraded-Diagnose, nicht eine erfundene Nullzählung. Erfolgreiches Snapshot-Schreiben darf nicht vorherige gesunde Einträge allein wegen Teilfehler verlieren. Tests für Fehler, 0, >15 und >30, Cache-Erhalt. Threat-/Snapshot-Neudesign bleibt X01.

## A04 — NLM-Claim-Verknüpfung typgebunden

**Stand B04 (gemergt, PR #137, `1359d14`):** `LINK_CLAIM_ENTITY` matcht Name+Typ; Typ stammt aus den deklarierten Extraction-Entities (kanonisiert). Namen ohne genau einen deklarierten Typ werden mit Warnlog übersprungen, nie name-only verknüpft. 4 Tests gegen isolierte Neo4j (`integration_tests/test_nlm_claim_links.py`). Altkanten aus früheren name-only-Läufen bleiben unberührt: Altdatenbedarf gehört zu R01.

**Unnummerierter Hinweis 4 · P1 · M/Senior-Datenreview.** Data-Ingestion `nlm_ingest/write_templates.py::LINK_CLAIM_ENTITY`, konkrete Caller in `nlm_ingest/ingest_neo4j.py`, Schema-/Template-/Ingesttests.

**RED:** zwei Entity-Nodes mit `name='Mercury'`, verschiedenen kanonischen Typen; Claim soll genau eine Kante erzeugen. Payload-Typ muss vom Extraktionsmodell bis zum gebundenen Templateparameter gelangen. Unbekannter Typ darf nicht wieder auf Name-only zurückfallen.

**GREEN:** MATCH über vorhandene kanonische Name+Type-Identität, parametergebunden; vorhandene Typnormalisierung/Constraints nutzen. Echte isolierte Neo4j-Fixture prüft Kantenanzahl. Kein globaler Homonym-Merge und kein automatisches Entfernen alter Kanten; Altdatenbedarf gesondert melden.

## ~~A05 — GDACS-Alternativwert trotz erstem Parsefehler lesen~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27, B03 / PR #136:** Implementierung `f4988aa`; keine offenen Findings. Unparsebarer oder nichtendlicher erster Severity-Wert verhindert den gültigen Alternativwert nicht mehr. Gültiger erster Wert gewinnt; bestehender Fallback 0.0 bei ausschließlich unbrauchbaren Kandidaten bleibt erhalten.
Gemeinsame unabhängige Abnahme: 1669 Ingestion-Tests bestanden, ein bestehender Dev-Compose-Test ausgelassen, 23 Live-Tests standardmäßig ausgeschlossen; Ruff und Diff-Check grün. PR-CI und Merge separat prüfen; kein Deployment.

**Unnummerierter Hinweis 5 · P2 · S.** Data-Ingestion `feeds/gdacs_collector.py::_severity`, entsprechende Collectortests.

**RED:** unparsebares `severity.value` und gültiges `severitydata.severity`; auch `NaN`/Infinity im ersten Slot. Zweiter Wert muss gewählt werden. Kein Wert → bestehender dokumentierter Fallback, dessen Bedeutung im Test benennen.

**GREEN:** nach ungeeignetem Kandidat nächste Quelle versuchen; finite Zahlen verlangen. Gültiger erster Wert gewinnt. Keine pauschale 0 bei erstem Fehler, keine Severity-Neuskalierung.

## ~~A06 — Ungemappte CAMEO-Konfiguration früh ablehnen~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27, B03 / PR #136:** Implementierung `f4988aa`; keine offenen Findings. Konfiguration und direkter Filter-Einstieg lehnen ungemappte Allowlist-Roots ab. Nicht mappbare Nuclear-Override-Events werden mit Diagnose entfernt, ihre GKG-Quellen bleiben erhalten; Verweise zeigen ausschließlich auf erhaltene Events. Gemappter Override außerhalb der Allowlist bleibt möglich. Writer-Vertrag weist leere/Whitespace-Typen zurück.
Gemeinsame unabhängige Abnahme: 1669 Ingestion-Tests bestanden, ein bestehender Dev-Compose-Test ausgelassen, 23 Live-Tests standardmäßig ausgeschlossen; Ruff und Diff-Check grün. PR-CI und Merge separat prüfen; kein Deployment.

**B03-Override-Vertrag:** Mappbare Roots außerhalb der Allowlist bleiben als Nuclear-Override zulässig (Regression mit Root 14). Nicht mappbare Override-Events werden mit Root-/Count-Diagnose ausgelassen; GKG-Quelldokumente bleiben erhalten, ihre Event-Verweise werden nur aus tatsächlich erhaltenen Events gebildet. Keine erfundene Ersatzklassifikation.

**Unnummerierter Hinweis 6 · P2 · S.** Data-Ingestion `gdelt_raw/{cameo_mapping,filter,config}.py`, passende Tests.

**RED:** Standard-Allowlist hat vollständiges Mapping; absichtlich zugelassener unbekannter Root erzeugt kein Event mit leerem codebook_type. Der Helper selbst gibt bereits None; Repro an `filter.py` durchführen.

**GREEN:** Konfigurationsvalidator verlangt vollständige Root-Abbildung oder explizite Skipregel mit Diagnose. Vorschlag: ungemappte Allowlist-Einträge als Konfigurationsfehler ablehnen. Eventvalidator darf leeren Typ nicht als gültig durchlassen. Kein Patch am deaktivierten GDELT-DOC-Collector.

## A07 — FIRMS-Hash aus kanonischer Erfassungszeit

**Unnummerierter Hinweis 7 · P2 · M mit Identitätsreview.** Data-Ingestion `feeds/firms_collector.py`, `tests/test_firms_collector.py`, Dedup-/Point-ID-Helper nur soweit nötig.

**RED:** `930`/`0930` und erlaubte Typvarianten erzeugen dieselbe beobachtete Zeit und neue kanonische Identität; zwei unterschiedliche Zeiten bleiben verschieden. Unzulässige HHMM-Werte werden nicht normalisiert zu scheinbar gültigen Punkten.

**Vor Codefix:** Bestand und Hashschema feststellen; Änderung produziert sonst neben alten IDs neue Dubletten. Minimalkonzept für Legacy-ID-Erkennung beim Dedup, versionierte Übergangsregel und idempotenten späteren Backfill vorlegen. Erst dann kanonische Zeit vor Hashing anwenden. Keine unangekündigte Reingestion/Massenlöschung.

## A08 — Gerundete Null in Location-Keys kanonisieren

**Unnummerierter Hinweis 8 · P2 · M mit Identitätsreview.** Data-Ingestion `graph_integrity/loc_key.py`, Backend vendored `app/services/_loc_key.py`, beide Key-/Paritätstests.

**RED:** ±0 sowie kleine positive/negative Werte, die auf drei Stellen zu 0 runden, ergeben dieselbe formatierte Null; normale nichtnull Werte unverändert. **Kein** Test mit falscher Annahme `-0.0 != 0.0`. Nahe-null Positionen sind nicht automatisch identisch mit exakter Null-Island-Policy.

**GREEN:** Rundung/Kanonisierung vor Formatieren, beide Kopien synchron, Paritätstest. ID-Änderung berührt Location-MERGE: erst Legacy-Key-/Migrationskonzept, kein unkontrollierter Duplikatneuanlauf. Null-Island-Unterdrückung nicht nebenbei auf ein größeres Gebiet ausweiten.

## X01 — Hotspot-Stufen und Snapshot-Vertrag entscheiden

**F-05 Policy/Geografie · P3 · Senior/Produkt.** Backend `app/routers/hotspots.py`, `app/models/hotspot.py`, Ingestion `feeds/hotspot_updater.py`, Frontend Hotspottyp/Farben lesen.

**Liefern:** maximal eine Seite mit vier Entscheidungen: (1) vier bestehende Stufen behalten und LOW-Kompression explizit dokumentieren oder LOW/UNKNOWN end-to-end ergänzen; (2) `hotspots:all` ist vollständiger Snapshot oder partielles Update; (3) kanonische IDs/Aliasse zwischen Default- und Updaterkatalog; (4) kuratierte Fallbacks klar von aktualisierten Daten unterscheiden. Empfehlung kurzfristig: aktuellen Vierstufen-/Snapshotvertrag erhalten, Nullfehler via D06 und Ausfall-Absenkung via A03 beheben; keine automatische Default-Union.

Taiwan-Strait-Referenzpunkt anhand verlässlicher geografischer Quelle und intendierter Gebietsbedeutung festlegen. Akzeptanzfälle: unvollständiger Lauf, absichtlich entfernter Hotspot, Cacheausfall, LOW, fehlende Stufe; keine doppelten bzw. still wiederbelebten Hotspots. Erst nach Entscheidung enges Implementierungsticket erstellen.

## X02 — FIRMS-Abdeckung ehrlich ausweisen

**F-14 · P2 Dokumentation, P3 Erweiterung · S/Produkt.** Ingestion `FIRMS_BBOXES`, militärische Collector-BBoxen, tatsächliche UI-Hinweise/README-Sourceliste lesen.

**Liefern:** explizite derzeitige BBox-Abdeckung, Namen als Operationsgebiete statt Länder. Minimalfix: sichtbarer Hinweis auf regionale Auswahl, keine globale Vollständigkeit behaupten. Technische Schlüssel zunächst erhalten, damit Rename nicht Cache/Tests bricht. Weltweite Abdeckung ist ein separater Auftrag mit API-Quota, Frequenz, Kosten und Antimeridian-Konzept. Keine Änderung an FRP-Farben/Explosionsheuristik im Rahmen dieses Findings.

## X03 — Mehrdeutigen Scope sichtbar ablehnen

**F-31 URL-Teil · P3 · Produkt/Sicherheit.** Frontend `src/spatial/navigation.ts`, zugehörige Navigation-/Hydrationtests.

**Liefern:** Entscheidung für `scope=UKR&scope=DEU`: derzeitige Invalidierung beibehalten, aber kein stilles unerklärtes Weltbild; sichtbarer Fehler bzw. letzte gültige Ansicht, ohne neue ungesicherte Länderabfrage. Identische Duplikate separat entscheiden. Kein „first wins“/„last wins“ ohne expliziten Vertrag. Scope-Revisionsschutz und Backendablehnung unverändert. Nach Entscheidung kleines UX-Testticket; SSE-U08 unabhängig abschließen.

## X04 — CelesTrak GP-JSON/OMM durch alle Verbraucher

**F-36 echte Abdeckung · P1 · L/Senior, früh beginnen.** Backend Satellite-Modell/-Service, Ingestion `feeds/tle_updater.py`, Frontend Satellite-Type/`SatelliteLayer`, `satellite.js` im Lockfile und dessen Propagationsadapter lesen.

**Entscheidungsvorlage:** CelesTrak-GP-JSON mit OMM-Feldsemantik als zukünftiges Eingabeformat, TLE für vorhandene Daten kompatibel halten. Keine großen IDs in künstliche 5-Zeichen-TLEs pressen. Prüfen, ob installierte Propagatorversion OMM sauber unterstützt; notwendiges gezieltes Upgrade mit Lockfile nur als expliziter Teil des Plans. Modell z.B. diskriminierte Orbitdaten TLE versus OMM, Cacheversion und Rollout-Reihenfolge festlegen.

**Anschließende kleine Tickets:** X04a Backenddecoder+API-Vertrag, X04b Ingestion+Cache, X04c Frontendadapter+Propagation, X04d Format-Cutover. Jedes mit Tests und kompatibler Zwischenversion. Fixture mit sechsstelliger ID muss vom Feed bis sichtbarer berechenbarer Position bestehen; alter ISS-TLE bleibt korrekt. Bekannte Referenzepoche/-position, UTC/Einheiten, ungültige Zeile, Transportfehler, Teilergebnis, Cachewechsel prüfen. Keine Vollabdeckung aus einem HTTP-200 allein ableiten.

Primärvertrag: [CelesTrak GP data formats](https://celestrak.org/NORAD/documentation/gp-data-formats.php). Alpha-5-Härtung aus D07 schließt dieses Paket nicht.

## R01 — Historische Daten nach den Codefixes untersuchen

**F-01/F-22/F-33/A01/A04/A07/A08 · separates Datenpaket, erst nach jeweiligem Fix.** Zunächst ausschließlich Read-only-Inventar und maschinenlesbarer Dry-run.

Pro Änderung: betroffene IDs, eindeutiger Quellbeleg, alte/neue Werte und Kanten, Konflikte, Anzahl, idempotenter Reparaturschlüssel, Backup-/Rollbackweg. FIRMS nur mit ursprünglicher URL/Signalprovenienz korrigieren, keine generelle Lat/Lon-Vertauschung. Unklare alte Incident-Statusübergänge nicht aus heutiger Heuristik rekonstruieren. ICAO-/NLM-Kanten nur bei überprüfbarer Zuordnung korrigieren. Hash-/Location-Key-Duplikate mit referenzierten Kanten und Signalen berücksichtigen.

Erst ein gesonderter Umsetzungsauftrag autorisiert Liveänderungen. Erfolg verlangt Vergleich vor/nach, keine unerwarteten Kantenverluste und zweiten idempotenten Lauf. Code-Rollback allein macht eine Datenmigration nicht rückgängig. Bis dahin Findings als „Code korrigiert, historische Daten ungeprüft“ führen, nicht pauschal geschlossen.
