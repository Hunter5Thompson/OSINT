# Incident-Pakete

Gemeinsamer Vertrag: [README](README.md). Alle Pfade relativ zu `services/backend`, sofern anders bezeichnet.

## ~~I01 — FIRMS-Produzent und Detektor auf denselben Koordinatenvertrag bringen~~ — GEMERGT

**Review 2026-09-27:** Implementierungscommit `a900604`, PR #131; keine offenen Findings. Unabhängig 50 Backend- und 8 Collector-Tests bestanden. PR #131 als `a45a13c` gemergt. Historische Incidents wurden nicht verändert; die Spezifikation bleibt als Abschlussnachweis erhalten.

**F-01 Koordinaten · P0 · S.**

**Scope:** `app/services/incident_promoter/detectors/firms.py`, `tests/incident_promoter/detectors/test_firms.py`. Lesen: `app/routers/firms.py::_build_map_url`, Data-Ingestion `feeds/firms_collector.py` und dortige `tests/test_firms_collector.py`.

**RED:** echte `_build_map_url` → `_parse_firms_coords` für `(48.1,37.8)`, `(35,139)`, `(40,-120)`, negative Breite, Nullmeridian, Bereichsgrenzen. Ergebnis immer `(lat,lon)`. Fehlerhafte URL und Werte außerhalb Lat ±90/Lon ±180 ergeben `None`. Bestehende Test-Fixtures und Envelope-Factory auf tatsächliches `@lon,lat` umstellen; nicht nur eine Assertion ändern.

**GREEN:** benannte Gruppen/Lesereihenfolge korrigieren, endliche Bereichsprüfung, interne Tuple-Reihenfolge beibehalten. Cluster-Schlüssel aus korrigierten Koordinaten. Collector-URL-Vertrag in dessen eigener Suite mit gleichem Referenzfall verriegeln; keine Cross-Service-Imports zur Laufzeit.

**Abnahme:** Detektor-/Router-/Collector-FIRMS-Tests. Kein Austausch von Latitude/Longitude im Frontend; dort sind Felder bereits richtig. Historische Incidents in separatem Datenpaket untersuchen.

## ~~I02 — Reservierung und Ignition nach Create-Fehlern wiederholbar machen~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27:** Implementierungscommit `3528d50`, PR #132; keine offenen Findings. Unabhängig 108 Promoter-/Pipeline-/Store-Tests, Ruff, fokussiertes Mypy und Diff-Check bestanden. Stabile Create-ID und ursprünglicher Request bleiben bei Fehlern erhalten; neue Retry-Beiträge werden dedupliziert bis zur erfolgreichen Anlage gesammelt. Der interne create-only-Pfad setzt `incident_id_unique` voraus. Kein Live-DB-Nachweis, keine dauerhafte Outbox, keine Prozesscrash-Garantie oder allgemeine Update-Wiederholung. CI und Merge separat prüfen; der folgende Vertrag bleibt als Abschlussnachweis erhalten.

**F-01 Recovery · P0 · M · nach I01.**

**Scope:** `app/services/incident_promoter/cluster_store.py`, `detectors/firms.py` nur falls nötig; `tests/incident_promoter/test_cluster_store.py`, `test_promoter.py`, FIRMS-Detektortests.

**RED:** nach Reservierung scheitert (a) Request-Validierung, (b) `create_incident`, (c) Task wird abgebrochen. Derselbe Cluster kann beim folgenden gültigen Hit erneut erstellt werden. Erfolg: genau ein Create bei gleichzeitigen Hits, kein vorgezogenes `incident.open`, keine verlorene Reservierung. Nach Persistenzfehler weiter ankommende Signale nicht dauerhaft als Race verwerfen; beitragende Signale/Titel/Initialzählung bleiben konsistent.

**GREEN:** gesamte Create-Phase einschließlich Koordinatenauflösung und Request-Konstruktion in garantierte Freigabe einschließen; `finally` für Reservierung, Cancellation weiterwerfen. Erfolg erst nach persistiertem Record finalisieren und publizieren. Erst testen, ob Store-gesteuerter Retry den Detektor ausreichend wiederaufnimmt; keine neue Ack-Architektur allein wegen `ignited` einführen. Falls Ignition-Metadaten verloren gehen, minimalen Failed-Create-Callback mit erhaltenem Fenster ergänzen und getrennt testen.

**Abnahme:** oben genannte Tests, keine Polling-Sleeps in Racetests, kontrollierte Async-Barrieren. Keine automatische Wiederholung mit neuer ID bei unklarem DB-Commit ohne Idempotenzprüfung.

## I03 — Telegram-Centroids vor Eviction zeitlich initialisieren

**F-32 · P1 · S.**

**Scope:** `app/services/incident_promoter/detectors/telegram.py`, `tests/incident_promoter/detectors/test_telegram.py`.

**RED:** Kapazität voll, alter und neuer unterschiedlicher Cluster; neuester Cluster bleibt, ältester fällt. Weitere passende Posts erreichen `telegram_min_hits`. Uhrgleichheit deterministisch, Kapazität 1, Suppression und normaler Updatefall prüfen.

**GREEN:** einen konsistenten `now`-Wert für Anlage/last_seen nutzen und vor Eviction setzen bzw. erst nach vollständiger Initialisierung evicten. Kein pauschales Erhöhen der Kapazität, keine Änderung der Jaccard-/Ignition-Schwellen. Fake-Clock statt realer Wartezeiten.

## I04 — Incident-Mutationen in der Datenbank serialisieren

**F-33 · P0 · L/Senior.** Zunächst konkreten Transaktionspatch entwerfen und reviewen; danach zwei Unterläufe Persistenz, dann Router/Promoter-Reaktionen.

**Scope:** `app/services/incident_store.py`, `app/cypher/incident_write.py`, `app/services/neo4j_client.py` nur benötigte Async-Transaktionsschnittstelle, `app/routers/incidents.py`, `app/services/incident_promoter/{cluster_store,promoter}.py`; `tests/test_incident_store.py`, Router-/Promotertests und neuer isolierter Neo4j-Nebenläufigkeitstest.

**Fester Vertrag:** Signal darf nur OPEN aktualisieren und niemals Status/closed_ts aus einer alten Kopie schreiben. Terminaler Status bleibt terminal. Gleicher Abschluss wiederholt = no-op; anderer Abschluss auf terminalem Record = conflict/no-op nach bestehendem API-Vertrag, kein falsches SSE. Mutation liefert `applied`, `unchanged` oder `not_found` plus aktuellen Record, kein mehrdeutiges „Record bedeutet geändert“.

**Implementierungsrichtung:** explizite DB-Transaktion: zielgerichtete Schreibsperre am Incident erwerben, **danach** Status und aktuelle Timeline lesen, erlaubten Übergang/Anhang berechnen, deterministisches Update unter derselben Sperre, Commit. Neo4j-taugliches Lock-Muster anhand isolierter Tests nachweisen; nicht bloß `WHERE status='open'` vor einem ungeschützten Whole-Record-SET setzen. Kein `MERGE` zum unbemerkten Wiederanlegen beim Update. Severity-Monotonie und Quellen-/Hint-Union aus dem gesperrten aktuellen Stand berechnen. Bestehende Geo-Kanten bei reinem Signalupdate nicht neu verdrahten.

**RED/Abnahme:** Update↔Silence, Update↔Close, Update↔Promote, zwei Updates, zwei Abschlüsse, fehlender Incident. Zwei unabhängige DB-Sessions, kontrollierter Interleave. Kein Reopen, keine verlorene Timeline/Quelle, Severity sinkt nicht. SSE/`mark_promoted`/`mark_silenced` nur beim passenden tatsächlichen Übergang. Mocks ergänzen, ersetzen aber den DB-Racetest nicht. Transaktionsretry muss idempotent sein; Callback publiziert niemals selbst SSE. Event-Auslieferung bei Prozesscrash ist kein Exactly-once-Versprechen dieses Patches.

## I05 — Poison-Rows isolieren und Promoter-Ausfall sichtbar machen

**F-34 · P0 · M · nach I04.**

**Scope:** `app/services/incident_store.py`, `app/services/incident_promoter/promoter.py`, vorhandene Promoter-Health-/Inspector-Anbindung; `tests/test_incident_store.py`, `tests/incident_promoter/test_promoter.py`, `test_admin_inspector.py`.

**RED:** gültig–`severity=medium`–gültig, ungültiger Status, kaputte Koordinate, kaputte Pflichtzeit. Liste und Rehydration behalten gültige Nachbarn. Ein echter Neo4j-Ausfall darf nicht als leere erfolgreiche Rehydration erscheinen. Drain-Task-Abbruch muss im Status sichtbar werden; „Sweeper lebt“ bedeutet nicht „Promoter gesund“.

**GREEN:** eng begrenzte Row-Decode-Isolation für Datenfehler, aggregierte Diagnose mit Incident-ID/Fehlerklasse; keine stillen Typumdeutungen. Rehydration liefert verwertbare Rows plus Degraded-Hinweis. Infrastrukturfehler kontrolliert retryen oder klar unhealthy bleiben. Vor erfolgreicher Rehydration keine neue Promotion beginnen, die bestehende Incidents duplizieren könnte. Regelung für nur ungültige Rows sichtbar degraded, kein false-green.

**Abnahme:** Liste/Promoter/Inspector-Testkette. Ungültige Einzelobjekt-Leseanfragen als Datenfehler behandeln, nicht in 404 umdeuten. Keine Live-Reparatur oder Löschung der beschädigten Daten.

## I06 — Historische Zeitwerte deterministisch lesen

**F-35 Zeitteil · P1 · M · nach I05.**

**Scope:** `app/services/incident_store.py`, `report_store.py`, deren Lesemodelle/-Router nur für kontrollierte Fehlerbehandlung; Store-/Reports-Tests plus neuer Zeitparser-Test.

**RED:** `Z`, positive/negative Offsets, naive ISO-Strings und naive datetime-Objekte; derselbe Input unter UTC und Europe/Berlin gibt denselben UTC-Wert. Ungültige Pflichtzeit ergibt Decode-Fehler, optionale Nullzeit bleibt null. Kein now()-Fallback beim Lesen persistierter kaputter Daten; explizite Create-Defaults bleiben erlaubt.

**GREEN:** gemeinsame kleine serviceinterne Parse-Hilfe, Naive→UTC explizit, zoniert→UTC. Bei Report-Store erst bestehende Bedeutung des expliziten `fallback`-Arguments prüfen und alle Caller anpassen; Pflichtzeitfehler pro Row isolieren wie I05. Keine Änderung von Eventzeit zu Ingestzeit. Tests kontrollieren TZ-Änderungen mit sauberer Wiederherstellung.
