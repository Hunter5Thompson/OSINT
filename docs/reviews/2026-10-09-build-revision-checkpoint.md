# Buildrevision — lokaler Implementierungscheckpoint

Dieser Schritt bearbeitet G02-Revisionsvertrag und Release-Konfiguration sowie
G03-Typprüfung und Image-CI. Konfigurations-/Servicetests sind lokal grün; echte
Image-Builds/Smokes, Browser-CI und produktiver Rollout sind noch offen. Kein
produktiver Live-Dienst geändert.

## Verhalten

Backend und Intelligence geben in ihren vorhandenen Health-Antworten additiv
`revision` aus. Sie lesen beim Modulstart die in das Image geschriebene
`.build-revision`; ein nachträgliches `ODIN_BUILD_REVISION` im Prozess-Env
ersetzt diese Angabe nicht. Ohne gültige volle Git-SHA bleibt die Revision
ausdrücklich `null`. Model-Readiness und bestehende API-Felder bleiben erhalten.

Frontend-Builds erzeugen `/build-info.json`. Ein gültiger Buildinput enthält
die volle SHA; Entwicklungsbuilds ohne Angabe enthalten `null`. Ungültige oder
abgekürzte Angaben brechen den Build ab. Nginx liefert die Datei mit
Revalidierung; fehlt sie, gilt HTTP 404 statt HTML-SPA-Fallback.

Die vier aktiven App-Dockerfiles haben einen expliziten Buildinput und OCI-Revisionlabel;
Compose reicht den Input durch, Default `unknown`. GitHub-Frontend-CI verwendet
die tatsächliche Checkout-SHA des jeweiligen Workflows. Backend-CI prüft jetzt
auch `mypy app/`; die drei Node-Tests des Metadata-Writers laufen in Frontend-CI.

Eine ausgegebene Buildrevision ist ein Metadatenvertrag. Erst ein geprüfter
Releasebuild aus genau diesem sauberen Git-Commit, ohne Codeüberschreibung per
Mount, sowie Image-/Prozessverifikation belegen den vollständigen Release.
Dieser Checkpoint behauptet diese noch nicht ausgeführten Image-/Livechecks
ausdrücklich nicht.

Ingestion liest ihre Revision beim Modulstart und meldet sie in
`scheduler_starting` und `scheduler_running`, vor den ersten Feed-Jobs.
Der neue `--release`-Modus entfernt lokale Builds und Code-Mounts, verlangt
Digest-Images und bindet den separaten gemeinsamen Datenbestand read-only ein.
Vor Lifecycle-Aktionen prüft er auch Datenpfade, zusätzliche Code-/Runtime-
Mounts und überschriebene Image-Startbefehle. Entwicklungs- und vorhandene
Recovery-Verträge bleiben geprüft. Der aktuelle externe Tracing-Stack muss
noch in die freizugebenden Images integriert werden.

CI baut die vier aktiven App-Images und führt `scripts/ops/smoke_image.py` aus.
Das Skript startet den tatsächlichen Image-CMD auf einem internen Netz, ohne
Hostports oder Produktivinputs. Intelligence verwendet einen deklarativen
Modellkatalog als Fixture (kein echtes LLM). Backend prüft Erreichbarkeit und
Revision bei unerreichbaren Datendiensten. Frontend prüft Nginx/JSON/Cache und
404 bei fehlender Metadatendatei; Ingestion prüft die Startlogrevision. Dies
belegt Artefaktstart, keine reale Feed-/Analysequalität. GitHub-Ausführung des
neuen Gates ist noch nicht belegt.

Die externen Buildinputs der vier aktiven Apps sind jetzt per Registry-Digest
fixiert (09.10.2026 frisch aufgelöst): Python3.12-slim
`a6e34c598f24…`, uv0.10.0 `78a7ff97cd27…`, Node22-alpine
`0a7108bf6c7b…`, Nginx-alpine `df221db836e1…`. Vollständige Indexdigests stehen
in den Dockerfiles. Weitere optionale/Kern-/Modellimages bleiben separat offen.

## RED und GREEN

- Backend: zwei HTTP-Regressionen zuerst rot wegen fehlendem `revision`-Feld.
- Intelligence: drei HTTP-Regressionen zuerst rot, einschließlich HTTP 503
  bei fehlendem Modell; kein Import-/Setupfehler als RED verwendet.
- Frontend: erfolgreicher bestehender Build hatte keine `dist/build-info.json`;
  separate Assertion fehlgeschlagen. Anschließend Writer-/Formatregressionen
  und erfolgreicher Build mit Revisionsdatei geprüft.
- CI: bestehender Backend-Job hatte keine Mypy-Prüfung; der Ops-Vertrag war
  fachlich rot und ist nach Ergänzung grün.
- Abschluss lokal: **900 Backend-, 599 Intelligence-, 684 Frontend-,
  66 Ops- und 3 Node-Tests bestanden**. Backend-Mypy über 92 Quelldateien,
  Backend-App-/Intelligence-Ruff, Frontend-ESLint/TypeScript und Frontend-Build
  bestanden; Diff-Check sauber. Python 3.13.12, uv 0.10.0, Node 22.23.1.
- Dependency-Locks unverändert. Die vorhandenen beiden exakten Intelligence-
  Health-Antwortfixtures wurden ausschließlich um das neue additive
  `revision: null` ergänzt; Modell-/Statuskriterien nicht abgeschwächt.
- Folgeschritt: zwei fachlich rote Ingestion-Startlogtests, zwei rote
  `--release`-Entrypointtests und zwei rote Command-/Entrypoint-Overridefälle.
  CI-Image-Gate fehlte; vier Floating-Buildinput-Verträge waren rot. Das alte
  Backendimage scheitert read-only am OCI-Revisionsvergleich, vor jedem Start.
- Danach **1687 Ingestion-Tests bestanden, 1 bestehender Skip, 23 opt-in
  Live-Tests abgewählt**; **89 Ops-Tests bestanden**. Vollständiger Service-Ruff
  und gezielter Ops-Ruff grün. Keine Dependency-Lockänderung.
- Für große Image-/Cacheartefakte eigener Rootless-Docker unter
  `/data/odin-caches/goal-docker`, vollständig getrennt vom produktiven Daemon.
  Kernel/Host-Docker/Produktivcontainer nicht umkonfiguriert. Das Hilfsbinary
  slirp4netns1.3.6 liegt unter/data, mit offiziellem Release-SHA256 verglichen.

Rohlogs befinden sich ausschließlich unter
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G01/` mit Prefix
`red-` bzw. `green-`. Die künstliche SHA `aaaa…` im Build ist eine Fixture,
keine behauptete Git- oder Deploymentrevision.

## Anschluss

Als Nächstes tatsächliche isolierte Image-Builds auf
Python 3.12/Node 22 sowie Label-/Metadaten-/Health-Abgleich, G03-Browsergates
und konkreter Rollout/Rollback. Trace-/Catalog-/Persistenzinputs und
HAPI-Voraussetzung erhalten. Erst nach diesen Prüfungen als fertig zur
Releasefreigabe vorlegen.
