# B07 — Identitätsübergang vor dem Codefix

## A07 FIRMS

Legacyhash: SHA256 des lower/strip-normalisierten Keys
`lat:.4f|lon:.4f|acq_date|acq_time`; Point-ID aus den ersten16Hexstellen.
Sensoragnostik und Koordinatenpräzision bleiben erhalten. Das4stellige HHMM
ist kanonisch; gültige ungepaddete String-/Integerformen führen zur gleichen
UTC-Minute. Ungültiges Pflichtdatum/HHMM darf keine kanonische Beobachtung werden.

Neue Producerkennzeichnung: `firms-location-hhmm-v2`. Standardmäßig bereits
vierstellig gespeicherte Identitäten behalten denselben Hash. Vor jeder neuen
Verarbeitung die kanonische ID und die begrenzten alten gültigen Zero-Padding-
Varianten prüfen; jeder Legacytreffer unterdrückt die Neuanlage. DB-Lesefehler
bleibt Fehler, nicht cachemiss. Keine vorhandenen IDs, Vektoren oder Originale
überschreiben, keine automatische Reingestion. Im Batch gleiche kanonische ID
nicht mehrfach verarbeiten. Gemischte aktive alte/neue Writer sind vor einem
späteren Rollout gesondert auszuschließen; derzeit kein produktiver Rollout.

## A08 Location

Neue reine Keyfunktion kanonisiert auf3Stellen gerundete Null auf `0.000`.
Originalkoordinate und exakte `(0,0)`-Sentinelregel bleiben unverändert.
Pro Zero-Koordinate höchstens zwei Legacyzeichenformen, insgesamt maximal4Keys.
Parametrisierter Write prüft diese Kandidaten **vor jeder Mutation**: kein
Treffer→kanonischer MERGE; genau ein Treffer→bestehenden Key/Node wiederverwenden;
mehrere Nodes→kein Write. Canonical+Legacy gleichzeitig ist ein Konflikt, keine
automatische Zusammenführung. Idempotente Promoter-Replays vorhandener Incidents
bleiben reine Ergebnisrückgabe ohne erneute Ortsmutation.

Backend-Incidenttemplates und Ingestion-Geo-Wiring müssen denselben Vertrag
nutzen. Der alte manuell gestartete Rekey-Executor behält seinen Legacytarget-
Algorithmus; er wird weder ausgeführt noch still in eine neue Migration umgebaut.
Echte isolierte Neo4j-/Concurrencyprüfung und `loc_key`-Unicity sind vor Freigabe
des neuen Writerstandes erforderlich; Mock-/Querytexttests ersetzen das nicht.

## Bestand, spätere Migration und Rücknahme

Die eingefrorenen Qualification-/61.501-ID-Handoffs und Reviewmanifest sind
gelesen. Bereits abgeschlossene Reparaturen/Verifikationen nicht wiederholen;
fehlende FIRMS-Originale bleiben unverifiziert. Ein neuer read-only Dry-run
würde ursprüngliche ID/Key/Rawzeit, kanonisches Ziel, vorhandene Aliasnodes,
Konflikte und betroffene Kanten mit Hashes in einem eigenen Journal erfassen.
Kein heuristisches Gleichsetzen verschiedener Sensor-/Originalversionen.

R01 ist separat: vor Datenänderung Backup, Konfliktsperre, exakte Vorherwerte,
idempotente Aktions-ID und genehmigte Liste; Quarantäne statt Massenlöschung.
Rollback der Daten stellt alte IDs/Keys/Kanten aus diesem Journal wieder her;
Code-Rollback allein repariert keine bereits geänderten Identitäten. Zunächst
nur kompatibler Sourcefix; tatsächliche Originalinventur und Datenmigration offen.
