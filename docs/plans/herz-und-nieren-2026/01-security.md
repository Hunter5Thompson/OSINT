# Security-Pakete

Gemeinsamer Vertrag: [README](README.md). Security-Reviews werden pro Paket dokumentiert. Hier geht es um Anwendungsgrenzen; reale Erreichbarkeit/DB-Rechte wurden nicht allgemein getestet.

## ~~S01 — Freies Cypher begrenzen und Template-Limits erzwingen~~ — ERLEDIGT

**Abgenommen am 2026-09-27:** 122 fokussierte Tests bestanden; F-15-Angriffe und unbekannte Template-IDs ohne DB-Aufruf abgewiesen. Ruff und `git diff --check` grün. DB-Rechte und serverseitige Timeout-Durchsetzung nicht live geprüft. Die folgende Spezifikation bleibt als Abschlussnachweis erhalten.

**F-15, F-10 Limitteil · P0 · M · unabhängig.** Service Intelligence.

**Scope:** `agents/tools/graph_query.py`, `agents/tools/graph_templates.py`, `graph/read_queries.py`, `graph/client.py`, `config.py`; zugehörige `tests/test_graph_query.py`, `test_graph_templates.py`, `test_cypher_validation.py`, `test_graph_client.py`, `test_scoped_graph_query.py`, `test_config.py`.

**Entscheidung:** Konfigurationsschalter für freie Queries default **aus**, Gate direkt in `execute_graph_query`, bevor eine DB-Ausführung erfolgen kann; auch NL-Fallback nicht mehr unnötig generieren, wenn ausgeschaltet. Bekannte Templates und Scope-Allowlist bleiben nutzbar. Ablehnung muss als unsupported/rejected erscheinen, nicht als erfolgreich angewandte Abfrage. `READ_ACCESS` weiter nutzen, irreführende „enforcement“-Kommentare korrigieren.

**RED:** alle Kommentar-/Quote-Angriffe aus F-15 dürfen bei Standardkonfiguration niemals `run_query` erreichen; auch ein harmloses freies MATCH wird im deaktivierten Modus abgelehnt. Bekannte Template-Abfrage weiterhin erfolgreich. Template-`limit`: -1, 0, 1, 100, 101, 10^9, `True`, String, `null` nach Parametermerge testen, sowohl global als auch scoped.

**GREEN:** ein verbindlicher Maximalwert 100; Integer auf 1..100 begrenzen, falsche Typen vor DB-Aufruf ablehnen; fehlendes Limit verwendet Template-Default innerhalb der Schranke. Keine Änderung an souverän gepinnten Scopeparametern. Query-Timeout zusätzlich im Client konfigurieren/testen; LIMIT allein begrenzt nicht die DB-Rechenarbeit.

**Abnahme:** focused Tests oben plus Scope-/Application-Marker-Tests. Kein Freischalten des alten Regex-Gates als „sicher“. Für spätere Aktivierung eigenes Senior-Design: korrekter Lexer für Kommentare/Strings/Backticks/Escapes, ein Statement, erlaubte Read-Grammatik und Funktionen, externe IO/Prozeduren ausgeschlossen, harte Gesamt-Resultat-/Zeitgrenze auch bei UNION/Subqueries und bereits vorhandenem LIMIT. DB-seitige Rechte/Read-Instanz passend zur Edition nachweisen. Dieses Folge-Design ist nicht Teil des kleinen Patches; eingeschränkte freie Funktionalität dokumentieren.

## ~~S02 — Query-URLs und lokale Worker-Dateien getrennt validieren~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27:** Commit `8b30249`, PR #128, gemergt als `732fadc`; alle CI-Tests, Ruff und CodeQL erfolgreich. 50 Intelligence-, 37 Backend- und 20 Worker-Tests unabhängig bestanden. Keine offenen Review-Findings. S03 wird separat dokumentiert. Die folgende Spezifikation bleibt als Abschlussnachweis erhalten.

**F-04 Pfad/API, F-12 Pfad · P0 · M · unabhängig.** Unterläufe: S02a Intelligence+Backend; S02b Worker.

**Scope:** Intelligence `main.py`, `agents/tools/vision.py`, `config.py`, `tests/test_vision.py` plus Requesttests; Backend `app/models/intel.py` und Modelltests; Vision-Enrichment `vision.py`, `config.py`, `tests/test_vision.py`, `tests/test_config.py`.

**Soll:** Öffentliche Backend-/Intelligence-Query-Eingänge akzeptieren für `image_url` ausschließlich absolute HTTPS-URLs ohne Credentials; keine lokalen Pfade oder file/data-URLs. Gleiche parametrisierte Contract-Fixtures in beiden unabhängigen Services. Keine DNS-I/O im synchronen Pydantic-Validator. Loader selbst muss seine Grenzen ebenfalls prüfen, nicht allein auf den Aufrufer vertrauen.

**Worker:** `image_path` nur unter expliziter konfigurierter Bildwurzel. Vollständigen Pfad und Wurzel kanonisieren, tatsächliche Elternbeziehung prüfen, nur reguläre Dateien. Kein Stringpräfix. Symlinks im untrusted Pfad ablehnen; bei veränderbaren Verzeichnissen descriptor-basiert race-sicher öffnen oder verbleibende Schreibrechteannahme explizit im Senior-Review schließen. Nie den ursprünglichen ungeprüften Pfad nach erfolgreichem Resolve öffnen. Bereits vor unbeschränktem Lesen maximale Bytes begrenzen.

**RED/Abnahme:** gültiges Bild innerhalb der Wurzel; `../`, ähnlich benanntes Nachbarverzeichnis, Symlink nach außen, Verzeichnis statt Datei, übergroße Datei. Ablehnung vor Dateilesen/LLM-Call. Direkter Intelligence-HTTP-Request muss ebenso 422 liefern wie Backend. Keine Produktionsdateien als Testziel. S03 bleibt nötig für Remote-Downloads.

## ~~S03 — Remote-Download an geprüfte IP binden~~ — FACHLICH ABGENOMMEN

**Review 2026-09-27:** Implementierungscommit `a514db8`, PR #129 als `58843a7` gemergt; alle CI-Checks erfolgreich. Unabhängig 94 Tests, Ruff, Offline-Lockfile-Check und Diff-Check bestanden. Die Tests prüfen IP-Pinning, TLS-Parameter und Loader mit Teststreams, keinen Live-Zertifikatshandshake. Die Spezifikation bleibt als Abschlussnachweis erhalten.

**F-04 Netzwerk · P0 · L/Senior · nach S02.** Intelligence `agents/tools/vision.py`, optional neuer lokaler Transporthelper, `config.py`, Visiontests.

**Soll:** nur globale Unicast-Ziele; alle DNS-A/AAAA-Antworten prüfen. CGNAT, Loopback, RFC1918, Link-local, unspecified, Multicast, reservierte Ziele und gemappte IPv4-Varianten blockieren. Auflösung asynchron bzw. außerhalb Eventloop. Verbindung ausschließlich zur geprüften Adresse; ursprünglichen TLS-Hostname/SNI und Zertifikatsprüfung erhalten. Kein zweites unkontrolliertes Resolve, kein Proxy aus Prozessumgebung, Redirects ablehnen. Begrenzter Streaming-GET mit Timeout und harter Byteobergrenze; HEAD darf keine Sicherheitsannahme begründen. Content-Type und dekodierte Bilddimensionen prüfen.

**RED:** Resolver liefert privat, gemischt public/private oder wechselt zwischen Prüfung und Connect; kein verbotener Connect. 302 auf privat; fehlende/falsche Content-Length, Chunked/komprimierte Übergröße; ungültiger Content-Type; gutes HTTPS-Bild. Mocks prüfen Ziel-IP UND TLS-Hostname, nicht nur Validatorrückgabe.

**Abnahme:** kleiner Integrations-Testtransport/Fixture, der DNS-Pinning überprüft, ohne interne Adressen tatsächlich anzusprechen. Kein ad-hoc-URL-Umschreiben auf IP mit abgeschaltetem TLS. Wenn vorhandene HTTP-Transport-API kein sauberes Pinning erlaubt: kleines Senior-Design für unterstützten Transport, keine selbst erfundene HTTP/TLS-Implementierung. Bis zur Abnahme Remote-Vision gezielt deaktiviert oder nachweislich über einen begrenzten Egress-Pfad betreiben; nicht nur CGNAT patchen und schließen.

## S04 — Qdrant-Schema erst nach wirklichem Erfolg freigeben

**F-12 Schema · P1 · S.** Vision-Enrichment `consumer.py`, `qdrant_schema.py`, `tests/test_consumer.py`, `tests/test_qdrant_schema.py`.

**RED:** erster Schema-Check Timeout, zweiter valide; erster Timeout, zweiter SchemaMismatch; Collection fehlt. Beim gescheiterten Check keine Payload-Schreiboperation, kein enriched-Erfolg, kein Erfolgs-ACK. Flag bleibt false und nächster Versuch prüft erneut. Erfolgreicher Check setzt Flag true und wird nicht für jede Nachricht wiederholt.

**GREEN:** Netzwerkfehler propagieren in bestehenden Retry-/DLQ-Pfad; fehlende Collection ist kein erfolgreicher Schema-Nachweis. Preflight vor persistierenden Seiteneffekten dieses Verarbeitungslaufs platzieren; bestehende Reihenfolge schreibt Neo4j schon vorher. Dauerhaften Mismatch sichtbar behandeln, bestehende begrenzte Retry-Policy erhalten. Testen, dass kein Erfolgsstatus aus einem nur teilweise geschriebenen Vorgang publiziert wird. Keine neue verteilte Transaktionsplattform bauen.
