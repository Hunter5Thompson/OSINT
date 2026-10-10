# D07 — Textreader-Checkpoint

Der lokale Sourcefix liest benannte und nackte TLE-Paare mit derselben reinen
Grammatik in Backend und Ingestion. Der D07-Abschluss bleibt offen, weil die
vollständigen Serviceprüfungen dieser Folgesession durch die Sandbox blockiert
sind. Es gibt keinen Deployment-, GP-Ketten-, Fakten- oder Humanabschluss.

## Vertrag und Änderungen

- Kanonischer Scanner in `shared/orbit_elements.py`, bytegleiche Servicekopien;
  unveränderte qualifizierte Paar-/OMM-Mathematik. Namen, `0`-Namen, nackte Paare,
  Leerzeilen und Kommentare werden getrennt von Elementzeilen gelesen.
- Nackte Paare heißen deterministisch `NORAD <ID>`. Defekte Paare und verwaiste
  Zeilen verlieren keine gesunden Nachbarn; invalid/unsupported werden gezählt.
  Nichtleere Quellen ohne brauchbare Paare schlagen fehl. Nur Whitespace ist
  ein gültiger leerer Snapshot; reine Fehlermeldung/Not-updated-Text ist keiner.
- Backend behält gesunde Gruppen und meldet Teilfehler strukturiert im Log.
  Ausschließlich unbrauchbare Quellen ergeben HTTP 502; valide Leere HTTP 200.
  Ein gecachtes `[]` ist gültig. Das Legacy-Listenformat bleibt kompatibel;
  bereits vorhandene Legacy-Cachezeilen werden nicht migriert oder gelöscht.
- Updater hält alte Caches bei Fehlern, speichert valide Leere und meldet bei
  ausschließlich Fehlern den Lauf als fehlgeschlagen. 403 unchanged benötigt
  einen erhaltenen Gruppencache. Keine Produktivschreibprobe ausgeführt.
- AGPS/USES sind keine GPS/SES-Treffer; QZS/QZSS sind explizite Aliase.
  AEHF/MUOS gehören zu militärischen Comms; DSP erhält keinen pauschalen
  Recon-Typ. Das ist Nameklassifikation, kein unabhängiger Identitätsbeweis.

## TDD und Prüfung

Artefakte: `/data/odin-goals/2026-10-09-repo-hardening/evidence/G05/`.
Fachliche REDs: sieben Klassifikationsfälle; nacktes Paar in beiden Services;
je drei Kommentarfälle; je 14 invalid/unsupported/error-only Fälle; vier
Backend-Gruppen-/Leerefälle; zwei Updaterfälle; cached-empty und unchanged ohne
Cache. Die gemeinsame Textmatrix umfasst 26 Fälle und referenziert die
unveränderte publizierte ISS-Fixture sowie bewusst beschädigte Decoderfälle.

GREEN: Backend-Fokus 59, Ingestion-Fokus einschließlich Feedtests 70,
Ruff auf App/betroffenen Tests/Feeds, Backend-Mypy 95 Dateien, Vendoring-Gate 3,
Diffcheck. Alte synthetische Unit-Fixtures erzeugen jetzt explizit korrekte
Prüfziffern; sie sind keine Referenzorbits. Die alte fehlerhafte ISS-Fixture
in der Frontend-Legacyprüfung bleibt unverändert und wird nicht authentifiziert.
Der alte malformed-input-Erfolgsassert wurde gemäß D07 durch Parsefehler ersetzt.

Vollsuites wurden begonnen und nach reproduziertem Hängen beendet (exit 130).
Die Diagnose hängt bei unveränderten `TestClient`-/Asyncio-Threadpfaden; ein
Unix-Socketpaar kann in dieser Sandbox nicht senden (`EPERM`). Rohstacks stehen
in `d07-{backend,ingestion}-full-diagnostic.log`, ein kleiner Policybeleg in
`evidence/session-01a12332/unix-wakeup-policy.txt`. Kein Skip, keine Änderung
der Thread-/Testsemantik, keine Sandboxumgehung. Vollchecks und scoped Commit
müssen als eigenständige Gates nachgewiesen werden.

## Weiter

U05 auf dem qualifizierten Orbitadapter, danach GP-Produzenten und echte
HTTP→Globe-Kette. Remoteabgleich scheitert aktuell an DNS, Dockerzugriff ist
verweigert; ältere Image-/Remote-/Livebelege bleiben ausdrücklich historisch.
