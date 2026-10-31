# Reproduzierbarer App-Betrieb

`./odin.sh --env-file /data/odin-releases/<release>/release.env --release ...`
wendet drei Dateien explizit in dieser Reihenfolge an: `docker-compose.yml`,
`docker-compose.override.yml`, `docker-compose.release.yml`. Compose ab 2.24.4
ist nötig, weil `!override` die bisherigen Code-Mounts vollständig ersetzt.
Referenz: [Docker Merge-Regeln](https://docs.docker.com/reference/compose-file/merge/).
Ohne `--release` bleibt die bisherige Entwicklungskonfiguration aktiv.

Der Release-Modus startet selbst keine Builds. Er verlangt sechs ausdrücklich
gewählte Image-Referenzen mit vollständigem `@sha256:<64 hex>`-Digest, auch für
inaktive Profile: `ODIN_BACKEND_IMAGE`, `ODIN_FRONTEND_IMAGE`,
`ODIN_INTELLIGENCE_IMAGE`, `ODIN_INGESTION_IMAGE`, `ODIN_VISION_IMAGE`,
`ODIN_RERANK_IMAGE`. Beide Ingestion-Profile verwenden dasselbe Image. Ein
Docker-Image-ID aus `docker inspect` ist kein Registry-Manifest-Digest.

`ODIN_RELEASE_DATA_DIR` zeigt auf ein vorbereitetes absolutes Verzeichnis
außerhalb des Code-Checkouts. Darin liegen `backend/` und `backend/spatial/`.
Backend liest den gesamten Datenbaum; Intelligence und beide Ingestionsdienste
lesen denselben Spatial-Bestand. Die Binds sind read-only und erzeugen keine
fehlenden Host-Verzeichnisse. Der Vorabcheck prüft die Verzeichnisse vor
Start/Swap. Er prüft noch nicht ihre inhaltliche Catalog-Kompatibilität; dafür
gehören Manifestversion und Hashes in den Release-Nachweis.

Munin-Modellbefehl und `SYNTHESIS_MODEL`, Telegram-Sessionpfade, GDELT-/Telegram-
Persistenz, Kern-Datenbankvolumes und Modellcaches werden erhalten. Kern- und
Modellimages werden durch diese App-Erweiterung noch nicht vollständig gepinnt.
Das lokale 27B-vLLM aus der Basiskonfiguration ist weiterhin kein freigegebener
Betriebsweg; die bekannte Profiling-Störung ist vor `up ingestion` separat zu
lösen. Die GPU-Regel gilt weiterhin.

Vor einer tatsächlichen Betriebsumstellung:

1. Sauberen Git-Commit mit Locked Dependencies bauen; `ODIN_BUILD_REVISION`
   erhält dessen vollständigen SHA. OCI-Label und geladene API-/Logrevision
   müssen anschließend übereinstimmen. `unknown`/`null` ist kein Release-Nachweis.
2. Images isoliert prüfen und ihre Manifest-Digests, Basisimages, Lock-Hashes,
   Catalog-/Codebook-Versionen sowie Modelle in `release.env` und im
   Reviewbericht festhalten. Kein Produktivsecret in Git oder öffentliche Logs.
3. Den bestehenden Datenbestand sicher unter `/data` bereitstellen und
   vergleichen; vorhandene Originale und eingefrorene Validierungen erhalten.
   Dieser Modus kopiert oder migriert keine Daten.
4. Den aktuellen zusätzlichen Tracing-Stack separat integrieren. Dessen
   Python-Code-Mounts sind im Release-Modus unzulässig: Instrumentierung muss
   mit der freizugebenden Revision im Image liegen; Trace-Ausgaben und Tokens
   bleiben Laufzeitinputs. Ein Start über diese drei Dateien allein übernimmt
   den außerhalb des Repos liegenden Tracing-Stack **noch nicht**. Kein
   produktiver Rollout ohne belegte Erhaltung dieser Funktion.
5. `doctor` mit der vorgesehenen Release-Datei ausführen. Für zusätzlich
   zusammengesetzte Compose-Dateien den gesamten JSON-Render durch
   `python3 scripts/ops/validate_release.py --check-paths` prüfen, bevor eine
   Lifecycle-Aktion erfolgt. Den kompletten Render wegen möglicher Secrets
   nicht veröffentlichen.
6. Rollout und Rückweg anhand
   [Releaseinventar](../reports/2026-10-09-release-inventory.md) freigeben lassen.
   HAPI-Schemavoraussetzung separat abnehmen; kein automatisches Live-DDL.

`--release up` und `--release swap` prüfen Digest-Referenzen, Code-/Runtime-
Mounts, unveränderte Image-Startbefehle und Datenpfade, bevor auch nur der erste
Dienst gestoppt wird. `vision up` und `nlm up` nutzen denselben Vorabcheck.
Diese Konfigurationsprüfung ist keine Attestation aller geladenen Module und
kein Funktions-/Qualitätsnachweis gegen produktive Modelle oder Daten.

Die vier aktiven App-Images haben in CI jeweils einen Build und einen isolierten
Artefakt-Smoke. Lokal lässt sich derselbe Smoke mit
`python3 scripts/ops/smoke_image.py <service> <image> <full-git-sha>` ausführen;
`DOCKER_HOST` kann dafür einen separaten Daemon wählen. Der Smoke nutzt nur
eigene zufällig benannte Container und ein internes Netzwerk, weder Hostports
noch produktive Secrets, Datenmounts, Datenbanken oder Modelle. Er entfernt
seine eigenen Testressourcen auch bei Fehlern. Die Grenzen der Prüfung stehen
im [Checkpointbericht](../reviews/2026-10-09-build-revision-checkpoint.md).

Für Rollback und Recovery die zuletzt geprüfte Release-Datei außerhalb des
Checkouts aufbewahren. `--release down`, `ps`, `logs` und `gdelt` benötigen
weiterhin deren Image-/Datenvariablen zum Rendern. Die bisherigen Recovery-
Kommandos ohne `--release` bleiben erhalten; vor einer Umstellung insbesondere
Compose-Projektname, ursprüngliche Config-Dateien und tatsächliche Volumes im
Releasebericht festhalten. Nie ein neues Projekt über vorhandene Daten starten,
um fehlende Provenienz zu umgehen.
