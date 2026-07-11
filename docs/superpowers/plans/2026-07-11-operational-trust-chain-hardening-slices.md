# TASK-119 — Operational Trust Chain Hardening: Slice Work Orders

**Datum:** 2026-07-11

**Status:** IN EXECUTION — S01 VERIFIED, COMMIT/PR PENDING

**Design-Spec:**
`docs/superpowers/specs/2026-07-11-operational-trust-chain-hardening-design.md`

## Arbeitsregel

Jeder Slice ist ein eigener PR. Ein Slice beginnt nicht mit Produktionscode,
sondern mit dem relevanten Abschnitt der Design-Spec und einem roten Test am
beschriebenen Seam.

```text
SPEC → RED → GREEN → REFACTOR → VERIFY → RECORD
```

Pflicht im PR:

- Link auf diesen Arbeitsauftrag und die Design-Spec
- exakter RED-Befehl plus erwarteter Fehler
- exakter GREEN-/Abnahmebefehl
- nur Dateien dieses Slices; fremde Worktree-Änderungen bleiben unangetastet
- keine stillen Skips und kein Abschwächen einer Assertion, um Grün zu erzeugen
- keine neue Abstraktion ohne mindestens Produktions- und Test-Adapter
- nach GREEN ein kurzer Löschungstest: Verdoppelt sich die Logik bei Entfernung
  des neuen Moduls nicht, ist das Modul vermutlich zu flach und wird entfernt

Der aktuelle staged Change an `docker-compose.override.yml` gehört Slice 01 und
wird bis dahin weder verworfen noch mit anderen Slices vermischt.

## Reviewauflösung vom 2026-07-11

| Finding | Entscheidung |
|---|---|
| WARN-001 — `tests/ops` ohne Runner | Akzeptiert: S02 verdrahtet die Suite in den Quality-Loop; S04 ergänzt den CI-Job. |
| WARN-002 — Compose-Render hängt an `.env` | Akzeptiert und vertieft: S01 führt einen getrackten synthetischen Environment-Adapter ein; S01/S03/S05 verwenden ausschließlich ihn. |
| WARN-003 — getrackte Unit würde als Root laufen | Akzeptiert: Die installierte System-Unit läuft bereits als `deadpool-ultra`, die getrackte Unit aber nicht. S02 verhindert, dass ein Sync den Host auf Root zurückstuft. |
| WARN-004 — Bind-Mount-Verlust bricht Dev-Loop | Akzeptiert: S05 trennt Production- und Development-Compose; `up`/`swap` behalten den sichtbar markierten Dev-Adapter, `deploy` verwendet ihn nie. |
| INFO-001 — Node-Vorzustand unpräzise | Korrigiert: Docker nutzt bereits Node 22; nur CI nutzt Node 20, beide verwenden noch `npm install`. |
| INFO-002 — Timer angeblich nicht installiert | Für den auditierten Host widerlegt: System-Timer ist installed/enabled/active; nur die User-Unit fehlt. Config-Drift bleibt ein S02-Finding. |
| INFO-003 — Ports 8010/8011 und LAN-Warnung | Akzeptiert in S03. |
| INFO-004 — Vorher-Baseline | Akzeptiert: zehn feste Queries vor S06, vollständige 30-Query-Trace nach S09. |

---

## S01 — Kanonischer Munin Runtime Model Contract

**Status:** IMPLEMENTED + VERIFIED — COMMIT/PR PENDING

**Priorität:** P0

**Abhängigkeiten:** keine

**Risiko:** mittel, weil Readiness den Interactive-Start beeinflusst

**Invariant:** OT-01

**Erwarteter Umfang:** ein kleiner Ops-Contract-Test, ein tiefes
Readiness-Modul, Health-Wiring, Smoke-Skript und Compose-Hotfix

### SPEC

Das Interface des Runtime-Model-Contracts ist:

```text
{base_model, optional synthesis_model} + vLLM model catalog
    -> ready | not-ready(reason, missing_models)
```

- Ist `SYNTHESIS_MODEL` leer, ist nur `VLLM_MODEL` Pflicht.
- Ist es gesetzt, sind beide Modelle Pflicht.
- Ein nicht erreichbarer Katalog und ein fehlendes Modell sind unterschiedliche
  Gründe, aber beide bedeuten HTTP not-ready.
- Kein stiller Fallback von einem expliziten `munin` auf Base.
- Health nutzt einen kurzen Timeout. Der Prozess selbst darf während des
  parallelen vLLM-Boots laufen, damit Compose-Health-Retries greifen.
- Der bestehende ReAct-Pfad bleibt auf `qwen3.5`; nur Synthese nutzt `munin`.
- Compose-Render-Tests verwenden den getrackten Test-Adapter
  `tests/fixtures/compose.env`. `docker-compose.yml` referenziert Service-
  Environments über `${ODIN_ENV_FILE:-.env}`; Produktion behält damit `.env`,
  Tests setzen `ODIN_ENV_FILE` und `--env-file` explizit auf die Fixture.

**Non-Goals:** generischer Service-Discovery-Client, vLLM-Neustartlogik,
LoRA-Rollout-Controller.

### RED — Tests zuerst

1. Neu: `tests/fixtures/compose.env` mit ausschließlich synthetischen Werten,
   insbesondere einem klaren Test-Neo4j-Passwort und einem nicht geheimen
   Modellpfad.
2. Neu: `tests/ops/test_interactive_model_contract.py`
   - rendert die Profile `interactive`, `ingestion` und `interactive-spark` über
     `docker compose ... config --format json`;
   - setzt `ODIN_ENV_FILE=tests/fixtures/compose.env` und
     `--env-file tests/fixtures/compose.env` und beweist in einer Umgebung ohne
     Root-`.env`, dass kein Hostzustand benötigt wird;
   - bindet Backend, Intelligence und beide Ingestion-Services nachweislich an
     dieselbe synthetische Fixture;
   - verlangt das gepinnte vLLM-Image, `--enable-lora`, genau das
     `munin=/models/lora/munin`-Mapping und `SYNTHESIS_MODEL=munin`;
   - prüft, dass Base- und Synthese-Modell verschieden konfigurierbar bleiben.
3. Neu: `services/intelligence/tests/test_model_readiness.py`
   - Base + Munin vorhanden → ready;
   - Munin fehlt → not-ready mit `missing_models=["munin"]`;
   - Katalog nicht erreichbar/ungültig → not-ready, kein ungefangener Parserfehler;
   - leeres Synthese-Modell verlangt nur Base.
4. Ergänzen: Health-Test erwartet einen Nicht-2xx-Status, wenn der Contract nicht
   erfüllt ist.

Der Compose-Test ist wegen des vorgezogenen Emergency-Hotfixes im Worktree ein
Charakterisierungstest. Sein roter Vorzustand wird gegen den getrackten `HEAD`
festgehalten, ohne den Worktree zurückzusetzen. Die neuen Readiness-Tests müssen
vor Implementierung normal rot sein.

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_interactive_model_contract.py -q)
(cd services/intelligence && uv run pytest \
  tests/test_model_readiness.py tests/test_synthesis_model_setting.py -q)
```

### GREEN — minimale Implementierung

- staged Canary-Override als kanonische getrackte Konfiguration übernehmen
- Compose-`env_file`-Einträge über `ODIN_ENV_FILE` testbar machen; kein Kopieren
  oder Erzeugen einer Root-`.env` im Test
- `services/intelligence/scripts/react_smoke.py` gezielt aus Commit `88b3b84`
  übernehmen; kein Branch-Merge
- ein kleines Readiness-Modul mit genau einem öffentlichen Prüfeinstieg anlegen
- vorhandenen `/health`-Endpoint daran anbinden
- keine neue HTTP-Abstraktionsschicht; `httpx.MockTransport` ist der Test-Adapter
  zum produktiven `httpx`-Transport

### REFACTOR

- Modellmengenbildung nur an einer Stelle
- keine zweite vLLM-URL- oder Modellkonfiguration
- Fehlermeldungen ohne Tokens, Header oder vollständige Response-Bodies

### VERIFY

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_interactive_model_contract.py -q)
(cd services/intelligence && uv run pytest -q)
ODIN_ENV_FILE=tests/fixtures/compose.env docker compose \
  --env-file tests/fixtures/compose.env --profile interactive config --quiet
(cd services/intelligence && uv run python -m scripts.react_smoke \
  --synthesis-model munin)
```

### EXIT

- `/health` ist nur grün, wenn `qwen3.5` und das explizit konfigurierte `munin`
  im Katalog stehen.
- Der Live-Smoke beweist einen Base-Tool-Call und eine nichtleere Munin-Antwort.
- Ein Reset auf getracktes `main` kann den Canary nicht mehr entfernen.

### RECORD — 2026-07-11

- RED: Der hermetische Compose-Test scheiterte zweimal an der fest verdrahteten
  Root-`.env`; der Readiness-Test brach bei der Collection mit
  `ModuleNotFoundError: model_readiness` ab. Der zusätzliche Smoke-Test war vor
  Anlage des Skripts ebenfalls nicht importierbar. Ein späterer
  Determinismus-Test belegte die fehlende `temperature=0`-Festlegung vor deren
  Implementierung.
- GREEN: `${ODIN_ENV_FILE:-.env}` ist der einzige Service-Environment-Adapter;
  `model_readiness.py` vergleicht die kanonische Modellmenge mit `/v1/models`;
  `/health` bildet das strukturierte Ergebnis ohne Fallback auf HTTP 200/503 ab.
- REFACTOR: Der aus `88b3b84` übernommene Smoke-Vertrag nutzt die vorhandenen
  Settings beziehungsweise explizite CLI-Werte statt einer zweiten
  hartcodierten URL-/Modellkonfiguration. Fehlerausgaben enthalten keine
  Response-Bodies oder Header.
- VERIFY: Ops-Contract `2 passed`; vollständige Intelligence-Suite `353 passed`;
  `ruff check` und `ruff format --check` auf den fünf geänderten Intelligence-
  Python-Dateien sowie dem Ops-Contract grün; hermetischer Compose-Render grün;
  Live-Smoke mit strukturiertem Base-Tool-Call und wiederholt mehr als 700 Zeichen
  Munin-Antwort grün. Das neu gebaute
  Intelligence-Image ist Docker-`healthy`; `/health` liefert extern und intern
  HTTP 200 mit `required_models=["qwen3.5", "munin"]` und leerer Missing-Liste.
- KANONISCHE INVOCATIONS: Ops-Contracts laufen aus `services/backend` mit
  `uv run pytest ../../tests/ops/test_interactive_model_contract.py -q`; der
  Live-Smoke läuft aus `services/intelligence` mit
  `uv run python -m scripts.react_smoke --synthesis-model munin`. Direkter
  Skriptstart vom Repository-Root und System-Pytest sind keine unterstützten
  Runner und werden weder im VERIFY-Block noch im PR-Handoff verwendet.
- Folgefinding für S04: Der service-lokale Build-Kontext enthält derzeit die
  Host-`.venv`; `uv run` reparierte sie deshalb beim Containerstart und lud
  Dependencies nach. S04 erhält dafür einen ausführbaren Build-Kontext- und
  No-Sync-Vertrag; S01 wird dafür nicht verbreitert.
- Noch offen: Der vorhandene Nutzer-Change an `docker-compose.override.yml`
  bleibt unverändert staged. Erst Commit/PR macht ihn zu getracktem `main` und
  erfüllt damit das letzte EXIT-Kriterium; S02 beginnt vorher nicht.

**Commit:** `fix(intelligence): make Munin runtime contract reproducible`

---

## S02 — Hermetischer Quality-Loop

**Priorität:** P0

**Abhängigkeiten:** S01, damit der erste PR sofort vom Gate geschützt wird

**Risiko:** niedrig

**Invariant:** OT-02

**Erwarteter Umfang:** Backend-Testfixture, fokussierter Regressionstest,
Quality-Loop-Runner-Ownership und Unit-Datei-Synchronisation

### SPEC

- Tests dürfen lokale Admin-Tokens nicht aus `.env` übernehmen.
- Test-Defaults werden vor dem Import der App gesetzt und von einzelnen Tests
  explizit überschrieben.
- `tests/ops` ist die erste Suite des Quality-Loops. Sie läuft über die bereits
  vorhandene Backend-`uv`-Umgebung, nicht über unverwaltetes System-Pytest.
- Der vorhandene Quality-Loop bleibt bewusst fail-fast. Ein komplexer Shell-
  Aggregator ist nicht nötig, um ein korrektes Gate zu erhalten.
- Die getrackte System-Unit enthält `User=deadpool-ultra`,
  `Group=deadpool-ultra`, ein korrektes `HOME` und einen expliziten ausführbaren
  `PATH`. Sie darf niemals als Root laufen.
- Systemd lädt exakt die im Repository getrackten Unit-Dateien. Auf dem
  auditierten Host ist der System-Timer bereits installed/enabled/active; die
  installierte Non-Root-Unit und die unvollständige getrackte Unit driften aber.
- Ein fehlgeschlagener Lauf bleibt non-zero und erzeugt einen verwertbaren
  Handoff; ein erfolgreicher Lauf geht bis `odin.sh smoke`.

**Non-Goals:** zweiter Timer, paralleler Test-Runner, automatischer Fixer,
Benachrichtigungsplattform.

### RED — Tests zuerst

1. Ergänzen: `services/backend/tests/unit/test_reports_router.py`
   - der Test für einen nicht konfigurierten Admin-Token setzt keinen lokalen
     Zustand voraus und erwartet stabil `503`.
2. Ergänzen: `services/backend/tests/conftest.py`
   - ein Contract-Test beweist, dass die Test-App mit leeren Report-/Incident-
     Tokens startet, selbst wenn der aufrufende Prozess andere Werte besitzt.
3. Ergänzen: `tests/ops/test_quality_loop.py`
   - die getrackte Service-/Timer-Unit referenziert weiterhin den kanonischen
     Script-Pfad;
   - der Dry-Run endet beim Smoke und listet alle fünf Services;
   - fehlgeschlagener Handoff bleibt unveröffentlicht.
   - Dry-Run listet vor Backend die neue Sektion `Ops Contracts` mit
     `uv run pytest ../../tests/ops`;
   - die getrackte Unit enthält User, Group und HOME und enthält kein
     root-ausführbares Default.

Der vorhandene fokussierte Test ist der rote Repro:

```bash
(cd services/backend && uv run pytest \
  tests/unit/test_reports_router.py::TestReportsRouter::test_create_report_requires_admin_token -q)
```

Erwarteter Vorzustand auf einem Host mit gesetztem Token: `401` statt `503`.

### GREEN — minimale Implementierung

- Testkonfiguration in `tests/conftest.py` vor dem App-Import neutralisieren
- testspezifische Werte nur im Testprozess setzen; Produktions-Settings bleiben
  unverändert
- `Ops Contracts` als erste Quality-Loop-Sektion über
  `services/backend && uv run pytest ../../tests/ops -q` ausführen
- getrackte Unit zuerst um die bereits live bewährte Non-Root-Identität ergänzen,
  dann Diff gegen `/etc/systemd/system` prüfen, synchronisieren und
  `systemctl daemon-reload` ausführen
- keine Änderung an der fail-fast-Orchestrierung, sofern der volle Lauf danach
  grün durchläuft

### REFACTOR

- wiederholte Token-Monkeypatches nur dann zentralisieren, wenn ihr Default
  identisch ist; Tests mit bewusst gesetztem Token bleiben lokal lesbar
- keine globale Settings-Factory nur für diesen Defekt einführen

### VERIFY

```bash
(cd services/backend && uv run pytest -q)
(cd services/backend && uv run pytest ../../tests/ops/test_quality_loop.py -q)
ODIN_QUALITY_LOOP_DRY_RUN=1 ops/quality-loop/quality_loop.sh
systemctl status odin-quality-loop.timer --no-pager
systemctl show odin-quality-loop.service -p User -p Group -p Environment
```

Danach genau einen vollständigen manuellen Quality-Loop ausführen und Report +
Exit-Code im PR dokumentieren.

### EXIT

- der Regressionstest ist mit und ohne lokale `.env` grün
- der vollständige Loop erreicht alle fünf Services und den Smoke
- `tests/ops` wird vor den fünf Service-Suites automatisch ausgeführt
- die geladene systemd-Unit entspricht der getrackten Unit; kein
  `daemon-reload`-Warnhinweis
- vom Loop neu erzeugte `.venv`-, `node_modules`- und Log-Artefakte gehören nicht
  Root

**Commit:** `fix(ops): isolate nightly quality gate from host environment`

---

## S03 — Local Exposure Floor

**Priorität:** P0

**Abhängigkeiten:** S02

**Risiko:** mittel, weil Host-Zugriffspfade geändert werden

**Invariant:** OT-03

**Erwarteter Umfang:** Compose-Portbindings, Doctor-Prüfung, Ops-Tests,
einmalige Dateimodus-Korrektur

### SPEC

- Alle publizierten Ports binden standardmäßig an
  `${ODIN_BIND_HOST:-127.0.0.1}`.
- Container-zu-Container-Verbindungen verwenden weiterhin Compose-DNS und sind
  von Host-Bindings unabhängig.
- Neo4j besitzt kein schwaches Default-Passwort in Compose; fehlende
  Konfiguration ist ein Renderfehler.
- `.env`-Dateien mit Gruppen-/Weltrechten sind ein Doctor-Fehler.
- `odin_yggdrasil` in `TASKS.md` wird durch einen offensichtlichen Platzhalter
  ersetzt, obwohl es nicht das aktive Secret ist.
- `.env.example` enthält ebenfalls kein passwortähnliches Default.
- Ein explizites Nicht-Loopback-`ODIN_BIND_HOST` darf rendern, lässt `doctor`
  wegen der weiterhin unauthentifizierten internen Dienste aber sichtbar non-zero
  enden. Kein zweites „ich weiß was ich tue“-Flag.

**Non-Goals:** Qdrant-/Redis-/vLLM-Auth, JWT/RBAC, Firewall-Management,
Tailscale-Konfiguration.

### RED — Tests zuerst

Neu: `tests/ops/test_local_exposure_contract.py`

- gerendertes Compose weist für jeden publizierten Port `127.0.0.1` als
  `host_ip` aus, wenn `ODIN_BIND_HOST` nicht gesetzt ist; geprüft werden alle
  Profile einschließlich Voxtral `8010` und Vision `8011`
- ein expliziter Nicht-Loopback-Testwert wird korrekt gerendert, aber von
  `doctor` mit klarer unauthenticated-exposure-Meldung abgelehnt
- Compose enthält keinen Neo4j-Passwort-Fallback
- alle Render-Aufrufe verwenden die synthetische S01-Environment-Fixture
- Doctor liefert non-zero für eine testweise unsichere Secret-Datei und zero für
  Modus `600`; der Test nutzt ein temporäres Repository/Dateipfad-Argument, nicht
  die echte `.env`

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_local_exposure_contract.py -q)
```

### GREEN — minimale Implementierung

- vorhandene Portstrings um genau eine Bind-Variable ergänzen
- Neo4j-Passwort mit Compose-required-Interpolation verlangen
- Secret-Modusprüfung als kleine Funktion in das bestehende `odin.sh doctor`
  integrieren; kein separates Security-Framework
- reale `.env`-Dateien einmalig auf `600` setzen

### REFACTOR

- eine Bind-Variable, keine servicespezifischen Hostvariablen
- Doctor gibt nur Pfad und erwarteten Modus aus, niemals Secret-Inhalt

### VERIFY

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_local_exposure_contract.py -q)
ODIN_ENV_FILE=tests/fixtures/compose.env docker compose \
  --env-file tests/fixtures/compose.env --profile interactive config --quiet
./odin.sh doctor
ss -ltn | rg ':(5173|6333|6334|6379|7474|7687|8000|8001|8002|8003|8010|8011|8080)\b'
```

### EXIT

- kein ODIN-Port lauscht im Default auf `0.0.0.0` oder `[::]`
- alle gefundenen `.env`-Dateien sind höchstens `600`
- fehlendes Neo4j-Passwort stoppt Compose vor Containerstart
- ein explizites Nicht-Loopback-Binding erzeugt einen sichtbaren Doctor-Fehler,
  solange die internen Dienste keine Auth besitzen

**Commit:** `fix(ops): bind ODIN host ports to loopback by default`

---

## S04 — Locked Dependency Contract

**Priorität:** P1

**Abhängigkeiten:** S02

**Risiko:** mittel; der erste gelockte Build kann bisher verdeckte Drift zeigen

**Invariant:** OT-04

**Erwarteter Umfang:** vier Lockfiles, Gitignore/AGENTS, CI, vier Dockerfiles,
service-lokale Dockerignore-Regeln, Quality-Loop

### SPEC

Deployment-relevante Lockfiles sind Quellartefakte:

- `services/backend/uv.lock`
- `services/intelligence/uv.lock`
- `services/data-ingestion/uv.lock`
- `services/vision-enrichment/uv.lock`
- `services/frontend/package-lock.json`

Alle Python-Pfade verwenden `uv 0.10.0` und `uv sync --locked`; Frontend nutzt
Node 22 und `npm ci`. Lokale Ad-hoc-Trainingslockfiles bleiben außerhalb.
Service-lokale Docker-Build-Kontexte schließen Host-`.venv`, `node_modules` und
Caches aus. Ein gestarteter Container darf Dependencies weder synchronisieren
noch aus dem Netz nachladen; Python-Entrypoints verwenden deshalb den beim Build
erzeugten Environment-Zustand mit `uv run --no-sync`.

**Non-Goals:** ein Monorepo-Lockfile, Renovate/Dependabot, Base-Image-Digests,
Dependency-Upgrades über das zur Lock-Erzeugung notwendige Maß hinaus.

### RED — Tests zuerst

Neu: `tests/ops/test_dependency_contract.py`

- alle fünf Lockfiles existieren und sind von Git getrackt
- CI enthält pro Service den Locked-Install
- Dockerfiles kopieren den Lock vor dem Install und nutzen Locked-Modus
- Service-Build-Kontexte schließen `.venv`, `node_modules` und Cache-Artefakte
  aus; Python-Container starten mit `uv run --no-sync`
- Frontend-CI und Docker verwenden Node 22 + `npm ci`
- Quality-Loop verwendet dieselben Installkommandos
- ein eigener CI-Job führt `tests/ops` über die gelockte Backend-Testumgebung und
  die synthetische Compose-Environment-Fixture aus
- der CI-Job führt `docker compose version` als harte Capability-Prüfung aus;
  fehlendes Compose ist ein Runnerfehler, kein Test-Skip
- `AGENTS.md` beschreibt genau diese Policy

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_dependency_contract.py -q)
```

Der Vorzustand muss wegen vier ungetrackter Locks, unlocked `uv sync`,
`npm install` in CI und Docker sowie CI-Node 20 rot sein. Das Frontend-Dockerfile
verwendet bereits Node 22; diese Teilassertion ist eine grüne Charakterisierung,
kein behaupteter Defekt.

### GREEN — minimale Implementierung

- vorhandene lokale Locks ohne absichtliches Upgrade generieren/prüfen und
  tracken
- Gitignore nur für diese Deployment-Locks negieren
- Backend-, Intelligence- und Vision-Dockerfile dem bewährten
  Data-Ingestion-Muster angleichen
- minimale `.dockerignore`-Regeln an jedem service-lokalen Build-Kontext
  ergänzen und Python-Entrypoints auf `uv run --no-sync` setzen
- `uv:latest` auf `uv:0.10.0` pinnen
- Frontend auf Node 22 und `npm ci`
- CI und Quality-Loop spiegeln dieselben Befehle
- CI-Job `test-ops-contracts` nutzt `services/backend/uv.lock`, führt
  `uv run pytest ../../tests/ops -q` aus und exportiert ausschließlich die
  synthetische Compose-Fixture; davor muss `docker compose version` erfolgreich
  sein

### REFACTOR

- Kommentare entfernen, die die alte ungetrackte Policy erklären
- keine gemeinsame Build-Matrix einführen; fünf klare Jobs sind leichter zu
  prüfen als eine dynamische Matrix

### VERIFY

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_dependency_contract.py -q)
git ls-files 'services/**/uv.lock' 'services/frontend/package-lock.json'
(cd services/backend && uv sync --locked --all-extras && uv run pytest -q)
(cd services/intelligence && uv sync --locked --all-extras && uv run pytest -q)
(cd services/data-ingestion && uv sync --locked --all-extras && uv run pytest -q)
(cd services/vision-enrichment && uv sync --locked --all-extras && uv run pytest -q)
(cd services/frontend && npm ci && npm run lint && npm run type-check && npm test)
```

Build-Smoke für alle betroffenen Images durchführen.

### EXIT

- ein manuell verändertes Manifest bei altem Lock lässt CI/Image-Build hart
  fehlschlagen
- CI, Docker und Nightly lösen keine neue Dependency-Version auf
- ein App-Container lädt beim Start keine Dependencies nach und übernimmt keine
  Host-Environment-Artefakte in sein Image
- der CI-Job `test-ops-contracts` führt alle bis dahin vorhandenen Root/Ops-
  Contracts automatisch und ohne Host-`.env` aus

**Commit:** `build(ops): lock deployment dependencies across services`

---

## S05 — Runtime Provenance, Deploy und Drift

**Priorität:** P1

**Abhängigkeiten:** S01, S03, S04

**Risiko:** hoch; betrifft Build- und Startpfad aller App-Container

**Invariant:** OT-05

**Erwarteter Umfang:** Dockerfiles/Compose, Health-Metadaten, `odin.sh`, Ops-Tests

### SPEC

- Jedes selbst gebaute App-Image trägt
  `org.opencontainers.image.revision=<full git sha>`.
- HTTP-Service-Health liefert mindestens `service`, `version`, `git_sha`;
  Intelligence zusätzlich `base_model` und `synthesis_model`. Worker ohne HTTP-
  Interface werden ausschließlich über ihr OCI-Revisionlabel geprüft — für
  Build-Metadaten entsteht kein künstlicher Health-Server.
- Production-Container führen gebackenen Code aus. Der Backend-Code-Bind-Mount
  entfällt; persistente Daten dürfen gemountet bleiben.
- `docker-compose.dev.yml` ist der zweite reale Compose-Adapter und enthält nur
  den bestehenden Backend-Code-Bind-Mount. `odin.sh up`/`swap` behalten den
  schnellen Development-Pfad; `odin.sh deploy` verwendet ausschließlich den
  Production-Adapter. Ein implizites oder temporäres Bind-Mount-Fallback ist
  verboten.
- Der Dev-Adapter setzt einen eindeutigen Runtime-Mode. `doctor` meldet ihn als
  Development und behauptet dort keine imagebasierte Code-Identität; im
  Production-Mode bleiben SHA- und Config-Hash-Abweichungen harte Fehler.
- `odin.sh deploy <profile>` baut genau den sauberen aktuellen Commit, tagged
  Images mit dessen SHA, startet neu und ruft den strikten Smoke auf.
- Deploy verändert Git nicht automatisch: kein Pull, Reset oder Branchwechsel.
- `odin.sh doctor` vergleicht `HEAD`, Image-Revision, laufenden Compose-Config-
  Hash und konfigurierte Modellmenge.
- Abweichung ist non-zero, nicht nur `WARN`.

**Non-Goals:** Registry-Push, Remote-Deployment, Blue/Green, automatische
Rollback-Entscheidung, bitidentische OCI-Layer.

### RED — Tests zuerst

Neu beziehungsweise erweitert unter `tests/ops/`:

- `test_runtime_provenance.py`: Dockerfiles/Compose propagieren einen Fixture-SHA
  in Label und Environment
- `test_odin_deploy.py`: dirty Worktree wird abgelehnt; sauberer Fixture-Commit
  führt Build → Up → Smoke in dieser Reihenfolge aus; Git wird nie mutiert
- `test_odin_doctor.py`: SHA- oder Config-Hash-Abweichung ergibt non-zero
- Backend-/Intelligence-Healthtests verlangen die neuen Felder
- Regressionstest: Production-Compose mountet `/app/app` nicht aus dem Worktree
- Regressionstest: Development-Compose mountet `/app/app`, `up` verwendet den
  Dev-Adapter und `deploy` kann ihn nicht referenzieren
- Regressionstest: `doctor` unterscheidet Development sichtbar von verifiziertem
  Production und lässt Production-Drift weiterhin fehlschlagen
- alle Compose-Render-Tests nutzen die synthetische Environment-Fixture

Tests nutzen Command-Shims und Fixture-Ausgaben; sie starten keine echten
Produktionscontainer.

```bash
(cd services/backend && uv run pytest \
  ../../tests/ops/test_runtime_provenance.py \
  ../../tests/ops/test_odin_deploy.py ../../tests/ops/test_odin_doctor.py -q)
```

### GREEN — minimale Implementierung

- ein Build-Arg/Environment-Wert `ODIN_GIT_SHA`, von `odin.sh` gesetzt
- OCI-Revisionlabel und Health-Feld daraus erzeugen
- genau einen neuen `deploy`-Case in `odin.sh`; bestehende `up`-Semantik bleibt
- explizite Compose-Argumentlisten für Production und Development; der neue
  Dev-Override erhält den bisherigen Backend-Code-Mount, ohne ihn im
  Production-Render sichtbar zu machen
- `doctor` um zwei harte Vergleiche erweitern: Revision und Compose-Hash
- `smoke` prüft die Health-SHAs und ruft für Interactive den S01-ReAct/Munin-
  Smoke auf
- Backend-Code-Bind-Mount entfernen

### REFACTOR

- Git-SHA-Ermittlung nur in `odin.sh`, keine fünf leicht abweichenden Shellpfade
- Health-Daten je Service klein halten; kein allgemeines Build-Info-Framework
- bestehende `_check`-/Service-Helfer in `odin.sh` wiederverwenden

### VERIFY

```bash
(cd services/backend && uv run pytest ../../tests/ops -q)
./odin.sh doctor
./odin.sh deploy interactive
./odin.sh smoke
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8003/health
```

Zusätzlich einen absichtlich falschen Fixture-SHA im Test prüfen; keine laufenden
Container dafür manipulieren.

### EXIT

- im Production-Mode entsprechen alle laufenden HTTP-Service-Health-SHAs und
  Worker-Revisionlabels `git rev-parse HEAD`
- im Production-Mode entsprechen vLLM- und Intelligence-Compose-Hashes dem
  aktuellen Render; Development ist eindeutig und nicht als Production-grün
- ein Dirty- oder Drift-Zustand blockiert Deploy/Doctor sichtbar
- der bestehende Nightly-Quality-Loop erbt den strikten Smoke ohne zweiten Timer
- der dokumentierte Dev-Loop benötigt für Backend-Codeänderungen keinen Rebuild;
  der Production-Pfad besitzt trotzdem keinen Code-Bind-Mount

**Commit:** `feat(ops): make ODIN runtime provenance verifiable`

---

## S06 — Evidence Hygiene am Codec-Seam

**Priorität:** P1

**Abhängigkeiten:** S05

**Risiko:** mittel; zu aggressive Filter können valide Evidenz verwerfen

**Invariant:** OT-06

**Erwarteter Umfang:** kleiner gemeinsamer Datenvertrag, zwei bestehende
Content-Quality-Implementierungen, Evidence-Codec und Lane-Guard

### SPEC

- `source_ref_id` ist die primäre Quellenidentität. Mehrere Chunks derselben
  Quelle belegen nicht mehrere Quellenplätze.
- `content_hash` darf zusätzlich identischen Inhalt verschiedener IDs deduplizieren,
  aber niemals die Source-Deduplizierung ersetzen.
- In geordneter Eingabe gewinnt der zuerst gerankte brauchbare Chunk.
- Der Content-Guard gilt identisch für Analysis und Realtime.
- Hashtag-/URL-only-Inhalte sind Zero-Content.
- Boilerplate-Regeln sind konservativ und durch reale, redigierte AC-/WOTR-
  Fixtures belegt. Keine generische „lösche kurze Zeilen“-Heuristik.
- Read-Path schützt sofort; Fulltext-Ingest verhindert neue Verschmutzung.
- Keine destruktive Qdrant-Bereinigung in diesem Slice.
- Vor der ersten RED/GREEN-Änderung wird mit zehn fest registrierten Queries ein
  Vorher-Snapshot über den bereits aktiven Capture-Hook erzeugt. Festgehalten
  werden die heute verfügbaren Felder: Tool-Call-Anzahl, Evidence-Blöcke,
  Source-Diversität, Duplicate-/Zero-Content-Zahlen und Endergebnis. Rohcaptures
  bleiben lokal; der PR enthält Query-Manifest, Hashes und aggregierte Metriken.

### RED — Tests zuerst

1. Neuer sprachneutraler Vertrag:
   `contracts/evidence-content-quality-v1.json` mit positiven und negativen
   Textfällen aus den beobachteten Captures.
2. Intelligence:
   - `test_evidence_codec.py`: gleiche `source_ref_id`, verschiedene Hashes → ein
     Block; verschiedene IDs, gleicher Hash → ein Block
   - `test_corpus_policy.py`: Hashtag-only und URL-only werden in Realtime
     verworfen
   - Boilerplate-Fixture wird entfernt, Artikelprosa bleibt
3. Data-Ingestion:
   - dieselben Contract-Cases gegen `feeds/content_quality.py`
   - `test_fulltext_fetch.py`: bekannte Navigations-/Subscribe-Blöcke verschwinden,
     Substanz bleibt

```bash
(cd services/intelligence && uv run pytest \
  tests/test_evidence_codec.py tests/test_corpus_policy.py -q)
(cd services/data-ingestion && uv run pytest \
  tests/test_fulltext_fetch.py tests/test_content_quality.py -q)
```

### GREEN — minimale Implementierung

- Evidence-Codec führt getrennte `seen_source_refs` und `seen_content_hashes`
- `validate_lane` wendet denselben Textguard auf Realtime an
- die bestehenden Content-Quality-Zwillinge erfüllen denselben versionierten
  Datenvertrag; kein Shared-Package
- kleine, belegte Boilerplate-Bereinigung in `clean_body` und am Read-Seam

### REFACTOR

- Doppellogik innerhalb eines Services entfernen
- öffentliches Evidence-Format unverändert lassen
- Filtergründe als kleine feste Werte loggen, keine Rohinhalte

### VERIFY

```bash
(cd services/intelligence && uv run pytest -q)
(cd services/data-ingestion && uv run pytest -q)
```

Danach die acht vorhandenen Canary-Eingaben offline erneut durch Codec/Guard
laufen lassen und Vorher/Nachher-Zahlen dokumentieren.

### EXIT

- null doppelte `source_ref_id`-Blöcke
- null Hashtag-/URL-only-Realtime-Blöcke
- bekannte AC-/WOTR-Boilerplate fehlt, Artikelprosa bleibt
- keine Änderung an `SourceRef`-Metadaten oder Evidence-Parser-Kompatibilität

**Commit:** `fix(intelligence): enforce source-level evidence hygiene`

---

## S07 — Graph Write/Read Contract und Integritätsvokabular

**Priorität:** P1

**Abhängigkeiten:** S02

**Risiko:** hoch; falsche Cypher-Pfade können plausible leere Resultate liefern

**Invariant:** OT-07

**Erwarteter Umfang:** Graph-Templates, kompakte Context-Serialisierung,
disposabler Integrationstest, Integrity-Report-Namen

### SPEC

Die kanonischen aktiven Pfade werden explizit unterschieden:

```text
RSS:   Document -[:MENTIONS]-> Entity
       Document -[:DESCRIBES]-> Event
       Document -[:FROM_SOURCE]-> Source

GDELT: GDELTDocument -[:MENTIONS]-> GDELTEvent
       GDELTEvent -[:OCCURRED_AT]-> Location   (wenn Geo vorhanden)

NLM:   Claim -[:INVOLVES]-> Entity
```

`events_by_entity`, `co_occurring` und `source_backed` müssen zunächst den
RSS-Document-Pfad korrekt bedienen. NLM-Claims werden nicht künstlich zu Events
umgedeutet. Zusätzliche Pfade benötigen einen eigenen expliziten Intent.

Graph-Context serialisiert nur Relationen mit benannten Endpunkten. Fehlender
`name` wird nicht als `None` ausgegeben; für Document/Event wird ein sinnvoller
Titel verwendet oder der Eintrag verworfen.

Der Integrity-Report nennt getrennt:

- `structurally_disconnected`: `NOT (n)--()`
- `without_document_lineage`: rein beschreibende Metrik, nach Writer/Label gruppiert
- `store_counterpart_missing`: Qdrant-URL ohne Document/GDELTDocument

Keine dieser Metriken autorisiert Löschung.

**Non-Goals:** Graph-Reparatur, Massenmigration, Event/Claim-Unifikation,
generisches Cypher-ORM.

### RED — Tests zuerst

1. Neuer Integrationstest mit disposable Neo4j:
   `services/intelligence/tests/integration/test_graph_write_read_contract.py`
   - erzeugt eine minimale RSS-Fixture mit den echten deterministischen
     Writer-Statements
   - `events_by_entity("Russia")` liefert das Event
   - `co_occurring("Russia")` liefert die zweite Entity
   - `source_backed("Russia")` liefert die Source
   - Testdaten tragen einen eindeutigen Prefix und werden im Fixture entfernt
   - niemals gegen den Produktionsgraphen ausführen
2. `test_graph_templates.py` hört auf, `INVOLVES` als korrekten Event-Pfad zu
   verlangen, und prüft Parameterbindung sowie Rückgabeform.
3. `test_graph_context.py` pinnt: kein `None`, keine 20 identischen MENTIONS-
   Dumps, nur erlaubte kompakte Zeilen.
4. `test_graph_integrity_report.py` pinnt die drei Namen und beweist, dass alle
   Abfragen read-only sind. Eine GDELT-Fixture ohne `DESCRIBES`, aber mit
   `MENTIONS`, darf nicht als strukturell isoliert gelten.

```bash
(cd services/intelligence && uv run pytest \
  tests/test_graph_templates.py tests/test_graph_context.py -q)
(cd services/data-ingestion && uv run pytest tests/test_graph_integrity_report.py -q)
```

Der disposable Integrationstest wird separat mit expliziter Test-URI ausgeführt.

### GREEN — minimale Implementierung

- drei tote Templates auf den Document-Pfad umstellen
- Query-Ergebnisse mit `DISTINCT` und harten Limits begrenzen
- Graph-Context auf eine kleine Allowlist und benannte Endpunkte reduzieren
- Integrity-Report-Felder eindeutig umbenennen und Store-Divergenz aus dem
  bestehenden Reconciler ableiten
- keinen Writer ändern, solange der Test nicht beweist, dass der Writer falsch ist

### REFACTOR

- gemeinsame RSS-Pfadfragmente nur zentralisieren, wenn mindestens zwei
  Templates exakt dasselbe Fragment benötigen
- alte Tests, die nur den falschen String `INVOLVES` konservieren, ersetzen
  statt zusätzlich neue Tests darüberzulegen

### VERIFY

```bash
(cd services/intelligence && uv run pytest -q)
(cd services/data-ingestion && uv run pytest -q)
(cd services/data-ingestion && uv run python -m graph_integrity.cli)
```

Zusätzlich den read-only Live-Check für `Russia` dokumentieren; keine Live-Writes.

### EXIT

- RSS-Fixture liefert für alle drei Intents erwartete Rows
- bekannte Live-Abfrage für `Russia` ist nicht mehr leer
- kein Graph-Context enthält `(None)`
- Report weist 149.147 GDELTEvents ohne `DESCRIBES` nicht als 149.147
  strukturelle Orphans aus
- keine Repair-/Delete-Operation wurde ausgeführt

**Commit:** `fix(intelligence): align graph reads with writer schema`

---

## S08 — Ehrliche Publication Metadata

**Priorität:** P2

**Abhängigkeiten:** S06

**Risiko:** mittel; Webseiten ändern Metadatenformen

**Invariant:** OT-08

**Erwarteter Umfang:** gepinnte Provider-Fixtures, reiner Extractor,
Fulltext-Payload und Metadaten-Backfill

### SPEC

Vor Produktionscode wird pro AC, RUSI und WOTR genau eine redigierte reale
Fixture gespeichert, die die verfügbare Datumsquelle belegt. Der aktuelle
Crawl4AI-`/md`-Response enthält nur Markdown; deshalb wird zuerst verifiziert, ob
die vorhandene Fetch-Antwort Metadaten erweitern kann oder ein direkter HTML-
Fetch nötig ist. Ohne belegte Inputform stoppt der Slice.

Priorität der belegten Quellen:

1. JSON-LD `datePublished`
2. `article:published_time`/gleichwertiges Meta-Feld
3. semantisches `<time datetime>`
4. bereits vorhandenes RSS-Publikationsdatum
5. sonst `null`

Jeder Wert trägt `published_at_basis`. Observed-, Indexed-, Event- und
Ingestionszeit sind niemals Publication Metadata.

**Non-Goals:** LLM-Datumsextraktion, freie Textdatumsheuristik über den ganzen
Artikel, erneutes Embedding nur wegen Metadaten.

### RED — Tests zuerst

- Neu: `services/data-ingestion/tests/fixtures/publication_dates/`
- Neu: `services/data-ingestion/tests/test_publication_metadata.py`
  - je Provider ein positiver Fall
  - Zeitzonen-Normalisierung nach UTC/ISO-8601
  - widersprüchliche Felder folgen der festen Priorität
  - Event-/„last updated“-/Ingestionszeit wird nicht verwendet
  - kein belegtes Datum → `(None, None)`
- Fulltext-Payloadtest verlangt Datum plus Basis, ohne bestehendes RSS-Datum zu
  überschreiben, sofern HTML keine höherwertige belegte Publikationszeit liefert

```bash
(cd services/data-ingestion && uv run pytest \
  tests/test_publication_metadata.py tests/test_fulltext_payload.py -q)
```

### GREEN — minimale Implementierung

- ein reiner Extractor mit kleinem Ergebnisobjekt `{published_at, basis}`
- kleinste verifizierte Fetch-Erweiterung wählen; keine Provider-Klassen, wenn
  der generische strukturierte Extractor alle drei Fixtures trägt
- Payload um `published_at_basis` ergänzen
- ein dry-run-first Metadaten-Backfill nutzt `set_payload`; Vektoren bleiben
  unverändert

### REFACTOR

- Datumsnormalisierung genau einmal
- Provider-Sonderfall nur mit eigener Fixture und Begründung
- keine Zeitfeld-Fallbackkette außerhalb des Extractors

### VERIFY

```bash
(cd services/data-ingestion && uv run pytest -q)
```

Dry-run auf einer festen Stichprobe aus AC/RUSI/WOTR; anschließend Apply nur nach
Review der geplanten Payload-Änderungen.

### EXIT

- Nullrate in der festgeschriebenen 27-Treffer-Stichprobe unter 10 Prozent oder
  jeder verbleibende Nullfall nachweislich ohne Publikationsmetadatum
- kein Event-/Observed-/Ingestionsdatum wurde als `published_at` gespeichert
- keine Re-Embeddings

**Commit:** `feat(data-ingestion): extract evidence-backed publication dates`

---

## S09 — Directional Retrieval Gate und kleinste Korrektur

**Priorität:** P2

**Abhängigkeiten:** S06, S08

**Risiko:** mittel; eine Überkorrektur kann allgemeine Recall verschlechtern

**Invariant:** OT-09

**Erwarteter Umfang:** kleine feste Eval-Tranche, Metrikrunner, erst danach eine
gezielte Retrieval-Änderung

### SPEC

Die Eval enthält mindestens zwanzig gepaarte Fragen mit identischen Akteuren, aber
entgegengesetzter Richtung. Jede Zeile besitzt:

```text
query, subject, action, object, relevant_source_ref_ids,
reverse_distractor_source_ref_ids
```

Gemessen werden Recall@5 und `correct_before_reverse`. Die Tranche enthält den
bekannten Ukraine-Energie-Fall und bleibt nach ihrer Registrierung unverändert.

Reihenfolge möglicher Korrekturen:

1. präzisere Query-Formulierung/Expansion
2. deterministischer Richtungs-Feature-Boost im vorhandenen Kandidatenpool
3. erst danach andere Modelle oder Korpusänderungen

Nur die kleinste Maßnahme, die das Gate erfüllt und die neutrale Kontrolltranche
nicht verschlechtert, wird implementiert.

**Non-Goals:** neues Embedding-Modell, höheres ReAct-Budget, Knowledge-Graph-
Reasoner, unregistriertes manuelles Prompt-Tuning.

### RED — Benchmark zuerst

- Neu: `services/intelligence/eval/directional_retrieval_v1.jsonl`
- Neu: `services/intelligence/eval/run_directional_retrieval.py`
- Tests pinnen Schema, feste IDs, Metrikberechnung und Offline-Replay
- einmaliger Baseline-Lauf gegen den aktuellen Korpus wird als JSON-Artefakt mit
  Commit und Collection-Stand gespeichert

```bash
(cd services/intelligence && uv run pytest tests/test_directional_eval.py -q)
(cd services/intelligence && uv run python -m eval.run_directional_retrieval)
```

Der bekannte Fall muss vor der Korrektur rot sein; ist er bereits grün, wird die
Spec mit dem neuen Baseline-Befund aktualisiert und kein Fix erfunden.

### GREEN — minimale Implementierung

- anhand der Baseline genau eine der oben geordneten Maßnahmen auswählen
- Änderung im bestehenden Retriever/Reranker-Seam, kein paralleler Retrievalpfad
- Richtungssignal und ursprüngliche Scores im Eval-Artefakt sichtbar halten

### REFACTOR

- keine providerspezifischen Query-Regeln
- keine Schwellen ohne Namen und Test
- tote Experimente aus dem PR entfernen

### VERIFY

```bash
(cd services/intelligence && uv run pytest -q)
(cd services/intelligence && uv run python -m eval.run_directional_retrieval)
```

### EXIT

- 100 Prozent der registrierten Richtungsfragen haben einen korrekten Treffer in
  Top 5
- mindestens 90 Prozent ranken einen korrekten Treffer vor dem Reverse-Distractor
- neutrale Kontrollfragen verlieren nicht mehr als einen absoluten Recall-Punkt

**Commit:** `fix(intelligence): preserve direction in retrieval ranking`

---

## S10 — ReAct Research Trace, Injection-Gate und Entscheidung

**Priorität:** P2

**Abhängigkeiten:** S05, S06, S07, S09

**Risiko:** niedrig für Laufzeit, mittel für Datenschutz/Artefaktgröße

**Invariant:** OT-10

**Erwarteter Umfang:** versioniertes Trace-Modell, Vertiefung des vorhandenen
Capture-Hooks, Tests und ein registrierter 30-Query-Benchmark

### SPEC

Dieser Slice ändert keine Agent-Policy. Er macht Research vollständig messbar.

Ein Capture enthält mindestens:

- Schema-Version, Query-Hash und Zeit
- Base- und Synthese-Modell
- Iterationen sowie Tool-Call-Anzahl
- Toolname, redigierte Argumente, Start/Ende/Dauer und Ergebnisstatus
- referenzierte `source_ref_id`s pro Toolresult
- finalen Stop-Grund: `model_done`, `tool_budget`, `iteration_budget`, `timeout`
  oder `error`
- Gesamtdauer und ob Synthese erreicht wurde

Der bestehende Filesystem-Capture bleibt der produktive Adapter; ein temporäres
Verzeichnis ist der Test-Adapter. Keine Datenbank und kein Telemetrie-SDK.

Toolargumente und Fehler werden über Allowlist serialisiert. Keine Secrets,
vollständigen Feedtexte oder Authorization-Header im Trace.

Eine feste Poison-Fixture prüft den Tool-Pfad. Sie enthält eine Canary-Anweisung
in untrusted Qdrant-/Telegram-Evidenz. Gemessen wird, ob die Canary in späteren
Toolargumenten oder der finalen Antwort auftaucht. Ein Fail erzeugt einen
separaten Security-Fix-Slice; er wird nicht in der Messimplementierung versteckt.

### RED — Tests zuerst

- `tests/test_research_trace.py`
  - vollständiger erfolgreicher Trace
  - früher `model_done`-Stop
  - Tool-/Iterationslimit
  - Timeout und Toolfehler
  - Redaction und atomarer Dateischreibvorgang
- Workflow-Test beweist, dass der bisherige Capture ohne Stop-Grund/Dauern die
  neue Schema-Validierung nicht erfüllt
- Poison-Fixture-Test ist deterministisch und judge-unabhängig

```bash
(cd services/intelligence && uv run pytest \
  tests/test_research_trace.py tests/test_distill_capture.py \
  tests/test_react_injection.py -q)
```

### GREEN — minimale Implementierung

- kleines `ResearchTrace`-Modell mit einer öffentlichen Capture-Funktion
- vorhandenen `distill_capture`-Filesystempfad wiederverwenden oder klar in
  `capture/` vertiefen; keine zweite Capture-Umgebungsvariable
- vorhandenen `tool_trace`-State um Dauer, Ergebnisstatus und Stop-Grund ergänzen
- atomar über temporäre Datei + Rename schreiben
- bestehendes Synthese-Capture als Teil desselben versionierten Dokuments erhalten

### REFACTOR

- Trace-Erzeugung vom Filesystem-Adapter trennen, aber keine allgemeine Event-
  Bus-Abstraktion
- Argument-Redaction an einer Stelle
- alte Capture-Tests ersetzen, wenn sie nur das frühere flache Format pinnen

### VERIFY

```bash
(cd services/intelligence && uv run pytest -q)
```

Danach mindestens 30 registrierte repräsentative Queries durch den laufenden
Interactive-Pfad ausführen. Bericht enthält Median/P95 für Calls und Dauer,
Stop-Gründe, Evidence-Diversität, Richtungsfails und Injection-Ergebnis.
Für die zehn Queries der S06-Baseline werden zusätzlich nur die gemeinsamen
Vorher-/Nachher-Felder verglichen; fehlende alte Timing-/Stop-Grund-Felder werden
nicht nachträglich erfunden.

### EXIT

- 30/30 Captures validieren gegen dieselbe Schema-Version
- kein Lauf besitzt einen unbekannten Stop-Grund
- keine Secrets oder vollständigen Rohfeedtexte in Captures
- eine Entscheidung wird als Spec-Addendum dokumentiert:
  1. keine Policy-Änderung nötig,
  2. neuer kleiner Controller-Slice nötig, oder
  3. separate Policy-Distillation sinnvoll
- kein Controller und keine Budgeterhöhung in diesem PR

**Commit:** `feat(intelligence): capture complete ReAct research traces`

---

## Abschlussmatrix

| Slice | Harte Abnahme | Blocks |
|---|---|---|
| S01 | Modellkatalog + Base/Munin-Smoke | S05 |
| S02 | Full Quality-Loop grün und hermetisch | alle folgenden Slices |
| S03 | Default nur Loopback, Secrets `600` | S05 |
| S04 | CI/Image/Nightly locked | S05 |
| S05 | SHA/Config/Model-Drift erkennbar | S10; Nightly-Vertrag vollständig |
| S06 | Canary-Replay ohne Duplicate/Zero-Content | S09, S10 |
| S07 | Writer-Fixture liefert echte Read-Rows | S10 |
| S08 | belegte Datumsbasis, Nullrate-Gate | S09 |
| S09 | Directional Gate + neutrale Kontrolle | S10 |
| S10 | 30 valide Traces + dokumentierte Entscheidung | TASK-119 Abschluss |

## Bewusst vertagt

Diese Punkte benötigen nach TASK-119 gegebenenfalls eigene Specs:

- Repair oder Löschung strukturell isolierter Graphknoten
- Qdrant-/Redis-/vLLM-Authentifizierung nach der Netzisolation
- ReAct-Controller oder Policy-Distillation nach S10
- Eval-Artefakt-Registry für das separate `munin-distill`-Repository
- Image-Signierung, SBOM und Remote-Registry
