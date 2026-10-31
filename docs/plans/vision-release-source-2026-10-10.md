# G01/G03 — Vision-Imagevertrag ergänzen

Vorab: Das optionale Visionimage wird vom Releaseoverlay verlangt, hat aber
keine OCI-/gebakene Prozessrevision und fehlt im Image-CI-Gate. Dieser Slice
schließt nur die Source-/CI-Vorbereitung. Keine Imageprüfung erneut ausführen,
keinen Docker-/Produktivdienst starten oder Daten schreiben.

TDD-Gates: Vision liest ausschließlich .build-revision und ignoriert ein
Runtime-ODIN_BUILD_REVISION; unbekannt/invalid bleibt null. Der tatsächliche
main()-Start loggt diese Revision. Dockerfile pinnt denselben bereits im Repo
gewählten Pythonbasisdigest, lockeduv bleibt. OCI-Label/Bake, fünfter CI-Build,
Commitarchivkontext und Smokeauswahl müssen konsistent sein. Der isolierte
Smoke startet Image-CMD ohne Hostports/Mounts, nur eigenes internes Netzwerk,
keine Redis-/Qdrant-/Neo4j-/Modellinstanz und keine Quellen. Erwartet werden
gebakene Startrevision und laufender Prozess; dies beweist keine Consumer-
Bereitschaft, Messages, Analyse oder Cross-store-Atomicity. Keine neue LLM-/
Redis-/DBaktivierung oder Tracingveränderung. Alle alten vier Smokes erhalten.
