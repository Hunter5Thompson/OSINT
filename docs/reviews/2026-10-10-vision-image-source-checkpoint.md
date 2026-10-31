# G01/G03 — Vision-Imagequelle

Der optionale Visiondienst ist nun im fünften App-Image-CI-Slot und im
Commit-Build-Einstieg enthalten. Pythonbasis entspricht dem im Repo bereits
gewählten Digest; lockeduv unverändert. Image schreibt .build-revision und
OCI-Label; der tatsächliche main()-Start loggt nur diese geladene Revision.
Runtime-ODIN_BUILD_REVISION kann sie nicht ersetzen. Development/fehlende/
invalid Metadaten bleiben null.

Sieben neue Vertragsfälle waren RED: vier fehlende Readerfälle, tatsächlicher
Mainstart ohne Revisionsfeld, fehlende Digest/Bake/Label und fehlender CI-/
Build-/Smokeeintrag. Danach GREEN. Zwei zusätzliche Smoke-REDs beweisen, dass
Vision einen eigenen Prozessrevisionspfad braucht und einen Runtime-SHA trotz
korrektem OCI-Label abweist. Dockerprozessgrenzen im Test ausdrücklich gefaked.

Abschluss: Vision44 vollständige Tests und Ruff grün;59 Ops-/Source-/Lock-/
Vendorverträge grün, Ruff/diff grün. Initiale Rufffehler in neuen Tests gezielt
formatiert, danach grün. Ein erster Editaufruf verwendete versehentlich den
Servicecwd als Reporoot, scheiterte vor Mutation und wurde korrigiert. Kein
fachlicher RED oder Qualitätsbeleg daraus. Keine unveränderten Images/Smokes
neu gestartet, kein Dockeraufruf außerhalb der Fakegrenze.

Der vorbereitete tatsächliche Image-CMD-Smoke benutzt ein eigenes internes
Netzwerk, keine Hostports/Source-/Datenmounts und keine Queue/DB/Modellfixtures.
Er prüft Startuprevision und laufenden Prozess; consumer_readiness bleibt
not_assessed. Laufender Prozess ist kein arbeitender Consumer, keine Nachricht
oder erfolgreiche Analyse und kein realer Storewrite. Vor optionalem Vision-
Rollout bleiben Qdrantschema, Modelle, Queue/Retry/DLQ, Stores und Autorisierung
eigene Gates. Finale CI/Build/Image-/Live-/Faktenabnahme offen.

Artefakte Goal/evidence/G03/{red-vision-image-contract,red-vision-process-smoke,
vision-full-final,vision-ruff-final,vision-and-release-contracts-final,
vision-ops-ruff-final}.log. Vorgehen vorher festgelegt in
[Sourceplan](../plans/vision-release-source-2026-10-10.md).
