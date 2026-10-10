# G02 — Buildquelle eindeutig an den Commit binden

Der historische manuelle SHA3234993-Build ist verworfen. Dieser begrenzte
Source-Slice ergänzt einen lokalen Build-Einstieg für die vier bereits in CI
geprüften Appimages. Er ersetzt keinen Smoke, Manifestdigest, Rollout oder
Freigabenachweis und führt hier keinen Dockeraufruf aus.

Vorab-Gates: Gitroot/HEAD aus Git lesen, vollständigen SHA validieren; tracked
und untracked Änderungen vor jedem Build abweisen. Buildkontext ausschließlich
als git-archive des validierten Commits exportieren; kein beweglicher Checkout,
keine ignored Secrets/Caches. Backend/Frontend/Intelligence behalten ihren
Servicekontext, Ingestion den Rootkontext. Spatial-Buildflag bleibt true.
Revisionslabel muss dem tatsächlichen Export-SHA entsprechen. Receipts enthalten
Kontext-Hash, SHA und lokale Image-ID; keine erfundenen Registrydigests oder
Release-PASS. CLI bietet Plan ohne Docker und expliziten Build. Keine Möglichkeit,
manuellen SHA, Dirty-Override, alternativen Gitindex oder produktive Aktionen
anzugeben. Bereits vorhandene Receipt-/Kontextdateien nicht überschreiben.

RED/GREEN gegen korrekte Git-/Dockerprozessgrenzen: Dirty/Untracked und ungültiger
SHA ohne Build; vollständiger Commit in Buildarg und Export; vier korrekte
Kontexte; falsches OCI-Label abgewiesen; Sourceänderung vor Folgeimage stoppt.
Die Tests beweisen den Sourcevertrag, keinen tatsächlichen Imagebuild.
