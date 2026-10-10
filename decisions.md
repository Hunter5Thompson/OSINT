<!-- manifest: project=WorldView | doc_version=1.0 | updated=2026-03-05 -->

# Entscheidungslog

## DEC-001: 2026-03-05 — Single-User statt Multi-User-System
**Kontext**: Soll WorldView ein Multi-User-System mit Auth werden?
**Optionen**:
  A) Multi-User mit Keycloak — Pro: Teamfähig / Contra: Massive Komplexität, Auth-Overhead
  B) Single-User ohne Auth — Pro: Einfach, schnell / Contra: Nicht teilbar
**Entscheidung**: B) Single-User
**Begründung**: Lokaler Entwickler-Stack, kein Team-Zugriff nötig. Auth kann in v2 nachgerüstet werden.
**Auswirkung auf**: REQ-006 (keine Auth-Middleware), architecture.md (kein Keycloak Container)
**Review-Termin**: Wenn Team-Zugriff gewünscht

---

## DEC-002: 2026-03-05 — Python Monorepo statt Microservices
**Kontext**: Backend, Intelligence und Data-Ingestion als separate Services oder Monolith?
**Optionen**:
  A) Separate Docker-Container pro Service — Pro: Isolation / Contra: IPC-Overhead, mehr Dockerfiles
  B) Monorepo mit shared libs — Pro: Einfacher Import, weniger Overhead / Contra: Weniger Isolation
**Entscheidung**: A) Separate Services, aber shared Python libs via workspace
**Begründung**: Intelligence-Pipeline braucht GPU-Zugriff und andere Dependencies als Backend. Docker Compose handhabt die Orchestrierung.
**Auswirkung auf**: architecture.md (Dateistruktur), FEAT-010 (Docker Compose)

---

## DEC-003: 2026-03-05 — Ollama als Dev-Default, vLLM als Prod-Option
**Kontext**: Welcher Inference-Server als Default?
**Optionen**:
  A) Nur Ollama — Pro: Einfach / Contra: Weniger Throughput
  B) Nur vLLM — Pro: Performance / Contra: Setup-Aufwand, nicht für alle Modelle
  C) Beide, konfigurierbar — Pro: Flexibel / Contra: Zwei Code-Pfade
**Entscheidung**: C) Beide via OpenAI-kompatible API
**Begründung**: Beide bieten OpenAI-kompatible `/v1/chat/completions`. Ein einziger Client mit konfigurierbarer `base_url` reicht. Ollama für Quick-Start, vLLM für Production-Load.
**Auswirkung auf**: architecture.md (Tech-Stack), CLAUDE.md (LLM-Konfiguration)

---

## DEC-004: 2026-03-05 — uv statt pip/poetry für Python
**Kontext**: Python Package Manager
**Optionen**:
  A) pip + requirements.txt — Pro: Universal / Contra: Kein Lockfile, langsam
  B) Poetry — Pro: Lockfile / Contra: Langsam, Docker-Layer-Caching problematisch
  C) uv — Pro: 10-100x schneller, Lockfile, workspace support / Contra: Relativ neu
**Entscheidung**: C) uv
**Begründung**: Albert kennt uv bereits. Drastisch schnellere Installs, native workspace support für shared libs.
**Auswirkung auf**: Alle Python-Services (pyproject.toml statt requirements.txt)

---

## DEC-005: 2026-10-10 — Versionierte GP-Orbitdaten mit TLE-Kompatibilität

**Kontext:** Der dokumentierte Goal-Auftrag vom 09.10.2026 verlangt die
kompatible GP-JSON/OMM-Umsetzung bis zu einer sichtbaren sechsstelligen NORAD-ID.
Der frisch gesicherte CelesTrak-Feed enthält solche IDs; fünfstellige TLEs
decken sie nicht ab. Die frühere X04-Notiz war nur eine Entscheidungsvorlage.

**Entscheidung für die lokale Umsetzung:**
- `/api/satellites` behält den bestehenden TLE-Antwortvertrag für alte Clients.
  Die D07-Grammatik-/Klassifikationskorrekturen werden separat nachgewiesen.
- `/api/satellites/orbits` liefert `schema_version: 1`, gemeinsame
  Satellitenmetadaten und diskriminierte `orbit`-Daten: `format: tle` mit den
  unveränderten Zeilen oder `format: omm` mit validierten OMM-Feldern. Keine
  synthetischen TLE/Alpha-5-Ersatz-IDs. NORAD bleibt vollständig und numerisch;
  der Propagator erhält den ungekürzten Katalogstring.
- Die neue Antwort enthält UTC-Abrufzeit und Gruppenabdeckung: erfolgreiche
  und fehlgeschlagene konfigurierte Gruppen sowie invalid/unsupported Counts.
  `complete` bezieht sich ausschließlich auf diesen konfigurierten Abruf,
  nicht auf alle existierenden Satelliten, aktuelle Ephemeridenqualität oder
  externe Faktenverifikation. Teilfehler bleiben sichtbar; ausschließlich
  defekte/ausgefallene erwartete Gruppen sind kein erfolgreiches leeres Ergebnis.
  Ein ausdrücklich gültiger leerer Snapshot bleibt ein gültiger eigener Fall.
- Neuer Cache `satellites:orbits:v1`, TTL 7200 Sekunden, getrennt von
  `satellites:tle` und `tle:group`/`tle:norad`. Abrufzeit wird beim Cachelesen
  erhalten. Kein globales Löschen, keine automatische historische Migration.
- Der unterstützte GP-JSON-Vertrag ist EARTH/TEME/UTC/SGP4. CelesTraks fehlende
  redundante Metadaten werden nach seinem ausdrücklichen Vertrag normalisiert;
  andere explizite Frames/Zeitmodelle/Theorien werden abgelehnt. Zahlen bleiben
  endlich, Winkel/Exzentrizität/Mean Motion werden mit benannten Einheiten
  geprüft; unbekannte Daten werden nicht als Nullmessung erfunden.
- Beide Python-Services bleiben unabhängig paketierbar. Ein kanonischer kleiner
  Parser unter `shared/` wird als bytegleiche Servicekopie eingebaut; ein
  Ops-Vertrag verhindert Drift. Gemeinsame Fixtures prüfen die Semantik.
  Kein Laufzeitimport aus dem anderen Service oder einem externen Checkout.
- Frontendadapter für beide Varianten, gezieltes exaktes `satellite.js`-Upgrade
  auf 7.1.0 erst nach unabhängiger Referenzqualifikation. Null/fehlerhafte
  Propagation isolieren. Eine gecachte SatRec pro Elementdatensatz; Position
  und begrenzte Orbitbögen folgen ausschließlich der Cesium-Uhr gemäß U05.

**Sequenz / PR-Grenzen:** X04a Decoder, Modell und versionierter Backendreader;
X04c qualifizierter Frontendreader/Propagator; D07/U05 als einzelne TDD-Unterläufe;
X04b beide Produzenten mit getrennten Cachegenerationen; X04d erst nach
durchgängiger API→Position→Globe-Abnahme. Ein gemeinsamer B13/X04-PR ist nur bei
überschaubaren unabhängig deploybaren Stufen sinnvoll; andernfalls begründeter
Split entlang dieser Kompatibilitätsgrenzen. Release-/CI-Vorarbeiten bleiben
als eigene scoped Commits reviewbar.

**Vorab festgelegte numerische Abnahme:** WGS72-SGP4 liefert TEME-Positionen in km
und Geschwindigkeit in km/s. Gegen die getrennte veröffentlichte C++-Referenz
maximal 0.01 km Euklidfehler und 0.00001 km/s Geschwindigkeitsfehler an festgelegten
UTC-Zeitpunkten. Diese Schranke berücksichtigt Date-Millisekunden gegenüber
OMM-Mikrosekunden; tatsächliche Abweichungen zusätzlich berichten. Geodätische
Umrechnung und Cesium-Meter separat prüfen. Der vorhandene synthetische ISS-
Parserinput mit falschen Checkdigits ersetzt keine quellenbelegte gültige Fixture.

**Rollout / Rücknahme:** Neue Backendreader vor neuen Frontendclients ausliefern;
alte Clients behalten ihren Endpunkt. Produzenten erst nach Readerprüfung
umschalten. Zurücknahme verwendet zuvor geprüfte Images/alte Cachegenerationen
ohne Datenlöschung; Legacy-TLE beschränkt die Katalogabdeckung ausdrücklich.
Ein heutiger lokaler Architekturentscheid erteilt keine produktive Merge-,
Deployment-, Neustart- oder Datenmigrationsfreigabe. Die konkreten Releasegates
und menschlichen/fachlichen Abnahmen des Goals bleiben offen.
