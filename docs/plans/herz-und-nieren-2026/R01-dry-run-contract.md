# R01 — Separater historischer Dry-run und Datenrücknahme

R01 bleibt ein Datenpaket mit eigener Freigabe. Lokale Sourcefixes aus B03/B04/
B07 sowie die technische Qualifikation setzen keine historische Mutation frei.
Die eingefrorenen Corpus-/Reviewmanifeste und die gestoppte Reparaturkopie
werden erhalten. Keine alten mutierenden Executor/Postchecks erneut starten.

Vorbereitung vom 10.10.2026: drei deterministisch ausgewählte offene FIRMS-IDs
aus dem bestehenden Reviewledger, keine neue Massenprüfung. Sechs zugehörige
Cachekörper stimmen mit den bestehenden SHAs überein. Kein neues Original,
kein erneut ausgeführter Beobachtungsvergleich, keine geschlossene ID.
Per-ID-Status und Quellbindungen liegen in
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G06/original-intake/`.
Der vollständige alte Ledger bleibt für alle anderen offenen IDs maßgeblich.

NASA beschreibt den [Archivdownload](https://firms.modaps.eosdis.nasa.gov/download/)
als authentifiziert; NRT-Daten werden später durch Standardprodukte ersetzt.
Das erklärt, warum eine heutige Standarddatei kein Beleg derselben historischen
NRT-Version ist. [Area-API](https://firms.modaps.eosdis.nasa.gov/api/area/) und
Archivzugang haben unterschiedliche Verträge. Vorhandene negative Antworten
beweisen keine universelle Nichtverfügbarkeit. Kein Login, Emailcode oder
Credentialauftrag wurde ausgelöst; normale TCP-Verbindung ist policyblockiert.

Ein zukünftiger maschinenlesbarer Dry-run enthält je ID:

| Feld | Verbindlicher Inhalt |
|---|---|
| Auswahl | explizite ID-/Collection-/Graphgeneration und Query-SHA; keine ungeprüfte globale Auswahl |
| Identität | Datum, UTC-Minute, Koordinaten und Satellit/Produktversion; nahe Positionen oder Standardversionen getrennt |
| Original | originale URL ohne Secrets, Produktversion, Archivdatum, Abrufzeit, Körper-SHA und tatsächlich verglichene Felder |
| Vorher | Payload-/Property-/Kantenliste mit SHA, bestehende IDs, referenzierende Signals/Incidents/Reports |
| Nachher | exakt beabsichtigte Feld-/ID-/Kantenänderung; technische und faktische Aussage getrennt |
| Konflikt | aktuelle Generation/SHA muss Vorher entsprechen; keine Mehrdeutigkeit, Mehrfachkandidaten oder unerwarteten Referenzen |
| Reparaturschlüssel | SHA aus Version+ID+Vorher+Nachher+Originalbeleg, eindeutig und wiederholbar |
| Journal | proposed → validated → backed_up → applied → independently_checked; Fehler/Abbruch explizit, kein stilles Success |
| Backup | frischer passender Datenbackup plus per-ID-Rücknahmepaket, Restore auf isolierter Kopie tatsächlich geprüft |
| Rücknahme | nur protokollierte eigene Änderungen zurücknehmen, Nachher-SHA erneut prüfen; fremde spätere Änderungen sperren Rücknahme |

FIRMS: keine allgemeine Lat/Lon-Vertauschung oder neue ID aus bloßer Nähe.
A07-Hashvarianten erkennen vorhandene Altidentität; eine neue kanonische ID
darf erst nach Original- und Referenzprüfung an Stelle der alten treten.
A08: einziger alter Location-Key kann wiederverwendet werden; mehrere Keys
sperren den Write. Exakte Null-Island-Policy bleibt unverändert. HAPI-/NLM-/
ICAO-Kanten benötigen typgebundene Originalzuordnung, keine Homonymheuristik.
Unklare Incident-Statusübergänge nicht aus heutiger Policy rekonstruieren.

Neo4j- und Qdrant-Writes sind keine gemeinsame Transaktion. Eine genehmigte
Ausführung benötigt begrenzte Batchgröße, Operator-Lease, deterministische
parametergebundene Templates, Vorherbedingungen je Store und dokumentierte
Kompensation. Wiederholung eines applied-Schlüssels bestätigt Nachher oder
scheitert am Konflikt; sie erzeugt keine weiteren Nodes/IDs/Kanten.

Gesonderte Datenrücknahme wird gegen den protokollierten eigenen Nachherstand
geprüft; App-Image-Rollback repariert keine Daten. Kein Löschen produktiver
Volumes, keine pauschale Full-Restore- oder Fremdcleanupfreigabe. Erst nach
vollständig reviewbarer Proposal-/Backup-/Rücknahmematrix die konkrete
Produktivdatenentscheidung einholen.

Aktueller Dry-run: **0 eligible Änderungen, 3 Originalbelege erforderlich**.
Backup, Executor, Apply, reale Idempotenz-/Rücknahmeabnahme und vollständige
Faktenverifikation sind offen; sie werden aus dieser Vorbereitung nicht abgeleitet.
