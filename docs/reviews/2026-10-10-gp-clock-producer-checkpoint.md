# U05 / GP-Produzent — lokaler Sourcecheckpoint

Der Sourcepfad erhält die sechsstellige ID100651 vom GP-Feed über API und Cache
bis zum Produktionsadapter. U05 aktualisiert Billboards und begrenzte Orbitbögen
über dieselbe Cesium-Uhr. Die echte HTTP→Built-SPA→sichtbare Position ist weiterhin
offen: diese Folgeinstanz darf keinen TCPsocket öffnen. B13/G05 sind nicht abgenommen.

- D07 vorher separat: [Textreaderbericht](2026-10-10-d07-text-reader-checkpoint.md).
- U05: gecachte SatRec, ein Layerlistener, regulär maximal1Hz, sofortige explizite
  Zeitsprünge, Pause/Reverse, max64Arcs mit50Minuten und regulär30s Aktualisierung,
  bestehende LOD-/Degradationsgrenze, Hidden/Unmount/Destroyed-Viewer geschützt.
- Hook: versionierter Snapshot statt Legacy-TLE, UTC-Quellabruf statt Clientnow;
  Abort plus Sequenz und Effectgeneration, sichtbarer Gruppen-/Fehler-/Frischestatus.
- GP-Ingestion: `SATELLITE_ORBIT_FORMAT=omm` wählt neuen Producer, Default bleibt
  `tle`. Keine produktive Aktivierung. `CELESTRAK_GP_URL` explizit konfigurierbar.
  Gruppe und volle NORAD-ID in `orbits:v1:*`, unabhängig von Backendcache und
  Legacykeys. Row-/Gruppenisolation, valides leeres Snapshot, corrupt-cache refetch,
  Originalabrufzeit, 7200s Abrufzyklus bei24h TTL, Redis WATCH/MULTI schützt neuere
  individuelle Epochen gegen überlappende Gruppenschreibungen; max3Versuche.
- REDs unter `evidence/G05/red-u05-*`, `red-gp-*`: Uhr/Reverse/Hover/Seek,
  API100651/Quellzeit/Disable/Fehler, Quellstatus, ProducerID/Isolation/Zyklus/
  Epochenkonflikt, Schedulerformat. Import-/Setupfehler werden nicht als RED gezählt.
- GREEN: Layer11, Hook5, Status3; vollständiges Frontend127Dateien/751Tests,
  ESLint/Repo- und Browser-TypeScript/Vitebuild. Ein alter Spatial-Page-Mock musste
  den neuen öffentlichen Bridgeexport und typisierten Snapshot liefern; seine
  Verhaltensasserts bleiben erhalten. GP18 plus Scheduler2, Ingestionfokus90 mit
  D07/Feeds, Ruff. Backend-D07-Fokus59/Mypy95 unverändert gültig.
- `gp-source-chain/`: reale ProxyService/CacheService über HTTPX Mock-/ASGITransport
  und RAM-Redisinterface, JSON-Wirebody danach im tatsächlichen Produktionsdecoder/
  RecordCache/Propagator gelesen. Kein TCP, Redisserver oder Browser daraus ableiten.
- Zwei neue GP-Browserfälle mit echten Controls/Canvaspick/Quelle/Retry/Remount
  vorbereitet, typgeprüft und noch nicht ausgeführt: Preview `listen EPERM` auf
 127.0.0.1:15174. Screenshots/Orbitdarstellung und nativeGPU/Human sind offen.
- Backend-/Ingestionvolltests hängen im unveränderten Unix-Threadwakeup-Pfad;
  bounded Diagnose belegt EPERM, keine Skips oder Threadpatches. Gitindex-Write
  ist RO, kein scopedCommit, kein Indexbypass. Sourcebuildrevision bleibt null.

Belege unter `/data/odin-goals/2026-10-09-repo-hardening/evidence/G05`;
HEADe8603c6 mit eigenen dirtySourceänderungen. Frühere Decoder-/Propagator-/Image-
und Datenreparaturqualifikationen wurden nicht unverändert neu gestartet.
Keine produktiven Dienste, Daten, Modellprozesse oder fremden Worktrees geändert.
