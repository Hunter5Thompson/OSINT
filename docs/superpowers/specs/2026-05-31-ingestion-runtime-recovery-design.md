# P0b - Ingestion Runtime Recovery (Design Spec)

**Datum:** 2026-05-31
**Status:** Implemented on 2026-06-01

**Implementation:** `4758616` (Codebook fail-fast), `c7d6499` (image/lock contract),
`0b813c1` (offline-safe scheduler entrypoint)
**Ziel:** Das Data-Ingestion-Image mit gelockten Python-Abhaengigkeiten und
deterministischen Runtime-Artefakten bauen. Sein Scheduler startet mit allen
Runtime-Modulen und dem kanonischen Event-Codebook.

## 1. Motivation

Die Data-Ingestion-Tests laufen lokal, aber das Docker-Image verletzt seinen
Runtime-Vertrag:

1. `feeds/base.py`, `feeds/rss_collector.py` und weitere Module importieren
   `qdrant_doctor.schema`. Der Dockerfile kopiert `qdrant_doctor/` nicht.
   Ein frischer Image-Start scheitert bereits beim `import scheduler`.
2. Der Dockerfile kopiert auch `infra_atlas/` nicht, obwohl das Projekt den
   CLI-Einstiegspunkt `odin-infra-atlas` ausliefert.
3. `pipeline.py` sucht das Event-Codebook ueber einen impliziten
   Monorepo-Nachbarpfad:

   ```python
   Path(__file__).parent.parent / "intelligence" / "codebook" / "event_codebook.yaml"
   ```

   Dieser Pfad existiert im Container nicht. Der Prozess degradiert still auf
   `other.unclassified`, obwohl gueltige Event-Typen vorliegen.
4. Es gibt keine `.dockerignore`. Lokale `.venv`-, Cache- und Build-Dateien
   vergroessern den Docker-Build-Kontext unnoetig.
5. `services/data-ingestion/uv.lock` existiert lokal, ist aber gitignoriert.
   Ein sauberer CI-Checkout besitzt deshalb keinen reproduzierbaren
   Dependency-Contract fuer das Image.

Das ist kein neues Feature. Es ist die Reparatur eines gebrochenen
Auslieferungsvertrags.

**Praezisierung:** Dieser Slice verspricht reproduzierbare Python-Abhaengigkeiten
und deterministische Runtime-Paketierung, kein bit-identisches OCI-Image.
`python:3.12-slim` bleibt bewusst ein patchbares Base-Image. Vollstaendige
Digest-Pins und SBOM-Attestierung sind ein eigener Supply-Chain-Slice.

## 2. Engineering Lens

| Frage | Antwort |
|---|---|
| Welcher fachliche Invariant wird geschuetzt? | Ein gebautes Ingestion-Image muss seinen Scheduler starten und gueltige Event-Typen gegen dasselbe kanonische Codebook validieren wie die lokale Pipeline. |
| Welcher Context besitzt ihn? | Collection besitzt den Scheduler und sein Image. Intelligence besitzt den Inhalt des Event-Codebooks. Die Image-Paketierung ist der explizite Vertrag zwischen beiden Contexts. |
| Was ist der kleinste explizite Vertrag? | Das Image kopiert einen getrackten Lockfile, alle ausgelieferten Runtime-Module sowie genau das kanonische YAML-Artefakt an einen konfigurierten Pfad. Der Root-Build-Kontext schliesst Secrets atomar aus. |
| Welcher Test ist vor der Aenderung rot? | Ein Clean-Build-Smoke-Test scheitert bei `import scheduler` mit `ModuleNotFoundError: qdrant_doctor`. Ein Container-Codebook-Test sieht nur den Fallback-Typ. Statische Contract-Tests finden weder getrackten Lockfile noch Root-`.dockerignore`. |
| Was verschwindet? | Freie Dependency-Neuaufloesung, implizite Nachbarverzeichnis-Abhaengigkeit, stille Codebook-Degradation und unvollstaendige Image-Paketierung. |

DDD dient hier als Karte: Das Codebook bleibt ein fachlicher Contract zwischen
Contexts. Es wird kein Shared-Python-Package eingefuehrt.

## 3. Packaging Contract

### 3.1 Packaging-Aenderungen atomar ausliefern

Der Kontextwechsel, die Secret-Ausschluesse, der getrackte Lockfile und der
vollstaendige Dockerfile landen in **demselben Commit**. Es gibt keinen
Zwischenstand, in dem der Repo-Root als Build-Kontext aktiv ist, aber
`.dockerignore` fehlt.

Der atomare Commit umfasst:

- Root-`.dockerignore`
- `.gitignore`-Ausnahme fuer `services/data-ingestion/uv.lock`
- getrackten `services/data-ingestion/uv.lock`
- `services/data-ingestion/Dockerfile`
- beide Compose-Build-Kontexte

Beide Compose-Services verwenden danach den Repo-Root als Build-Kontext:

```yaml
build:
  context: .
  dockerfile: services/data-ingestion/Dockerfile
```

Das betrifft:

- `data-ingestion`
- `data-ingestion-spark`

Nur so kann der Dockerfile das kanonische Codebook als Build-Artefakt kopieren,
ohne eine zweite YAML-Kopie einzufuehren.

### 3.2 Lockfile-Policy eng korrigieren

Die bisherige Repo-Regel ignoriert alle Service-Lockfiles. Das ist fuer
ad-hoc lokale Testumgebungen bequem, aber fuer ein ausgeliefertes
Scheduler-Image zu schwach. Data Ingestion erhaelt bewusst eine enge Ausnahme:

```gitignore
services/**/uv.lock
!services/data-ingestion/uv.lock
```

`services/data-ingestion/uv.lock` wird regeneriert und getrackt. Die
operative Repo-Dokumentation wird im selben PR auf die Ausnahme hingewiesen:
Lockfiles bleiben grundsaetzlich lokal, der Data-Ingestion-Deployment-Lock ist
bewusst versioniert.

`uv sync --locked` ist hier passender als `--frozen`: Das Projekt ist kein
uv-Workspace, daher kann uv bereits beim ersten Sync pruefen, dass Lockfile und
`pyproject.toml` zusammenpassen. Ein veralteter Lockfile muss den Build sichtbar
abbrechen statt still installiert zu werden.

### 3.3 Dockerfile vollstaendig machen

Nach dem Wechsel zum Root-Kontext werden **alle** lokalen COPY-Quellen mit
`services/data-ingestion/` qualifiziert. Zielpfade unter `/app` bleiben
unveraendert.

```dockerfile
FROM python:3.12-slim

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
ENV EVENT_CODEBOOK_PATH="/app/runtime_contracts/event_codebook.yaml"

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv

COPY services/data-ingestion/pyproject.toml services/data-ingestion/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY services/data-ingestion/config.py .
COPY services/data-ingestion/pipeline.py .
COPY services/data-ingestion/scheduler.py .
COPY services/data-ingestion/feeds/ feeds/
COPY services/data-ingestion/gdelt_raw/ gdelt_raw/
COPY services/data-ingestion/nlm_ingest/ nlm_ingest/
COPY services/data-ingestion/qdrant_doctor/ qdrant_doctor/
COPY services/data-ingestion/infra_atlas/ infra_atlas/
COPY services/intelligence/codebook/event_codebook.yaml runtime_contracts/event_codebook.yaml

RUN uv sync --locked --no-dev

CMD ["python", "scheduler.py"]
```

Das erste `uv sync` installiert nur Drittanbieter-Abhaengigkeiten. Das zweite
installiert das lokale Projekt mit seinen Console-Scripts. Damit sind
`odin-ingest-gdelt`, `odin-ingest-nlm`, `odin-qdrant-doctor` und
`odin-infra-atlas` im finalen Image real aufrufbar.

`services/data-ingestion/migrations/` wird **nicht** kopiert: Diese top-level
Cypher-Dateien werden zur Runtime nicht referenziert. Die tatsaechlich
verwendeten GDELT-Migrationen liegen unter `gdelt_raw/migrations/` und kommen
mit `gdelt_raw/` ins Image.

### 3.4 Dockerignore

Eine Root-`.dockerignore` schliesst mindestens aus:

```text
.git
.claude/worktrees
.env
**/.env
**/.env.*
**/.venv
**/__pycache__
**/.pytest_cache
**/.ruff_cache
**/node_modules
**/dist
```

Secrets und lokale Umgebungen duerfen weder im Build-Kontext noch in
Image-Layern landen. `**/uv.lock` wird bewusst **nicht** ignoriert, weil der
getrackte Ingestion-Lock Build-Input ist.

## 4. Codebook Contract

### 4.1 Konfigurierter Pfad

`services/data-ingestion/config.py::Settings` erhaelt die einzige
data-ingestion-seitige Pfad-Policy:

```python
event_codebook_path: Path = (
    Path(__file__).parent.parent / "intelligence" / "codebook" / "event_codebook.yaml"
)
```

Der Default erhaelt den lokalen Monorepo-Workflow. Der Dockerfile setzt:

```dockerfile
ENV EVENT_CODEBOOK_PATH="/app/runtime_contracts/event_codebook.yaml"
```

`pipeline.py` und `tests/test_gdelt_cameo_mapping.py` lesen nur noch diesen
konfigurierten Pfad. Der Runtime-Vertrag ist damit sichtbar und
ueberschreibbar; parallele Pfadarithmetik verschwindet.

### 4.2 Fehlendes Artefakt ist ein Konfigurationsfehler

`pipeline.py` erhaelt eine eigene Fehlerklasse:

```python
class CodebookConfigError(RuntimeError):
    """Canonical event codebook is missing or invalid."""
```

`ExtractionConfigError` bleibt ausschliesslich fuer item-bezogene
vLLM-Konfigurationsfehler wie HTTP `401`, `403` oder `404`. Collectors duerfen
diese weiterhin pro Item behandeln. Sie fangen `CodebookConfigError` nicht.

Das Codebook wird beim Modulimport einmal geladen und daraus werden sowohl
`_VALID_CODEBOOK_TYPES` als auch `_SYSTEM_PROMPT` gebaut:

```python
def _load_codebook(path: Path) -> dict[str, Any]:
    ...


_CODEBOOK = _load_codebook(settings.event_codebook_path)
_VALID_CODEBOOK_TYPES = _get_codebook_types(_CODEBOOK)
_SYSTEM_PROMPT = _build_system_prompt(_CODEBOOK)
```

Die Loader-Funktion nimmt den Pfad explizit als Argument. Tests koennen
fehlende, leere und kaputte Dateien direkt pruefen, ohne
`importlib.reload()`-Akrobatik.

- Fehlende, unlesbare, leere oder strukturell kaputte YAML-Datei: sichtbarer
  `CodebookConfigError` beim Startup.
- Unbekannter vom LLM gelieferter Typ: weiterhin kontrollierter Fallback auf
  `other.unclassified`.

Diese Faelle sind fachlich verschieden. Ein LLM darf irren; ein Image ohne
seinen kanonischen Contract ist nicht gesund.

### 4.3 Kein vorschnelles Shared-Package

Das YAML bleibt vorerst unter `services/intelligence/codebook/` die kanonische
Quelle. Data Ingestion erhaelt beim Build eine explizite Artefaktkopie.

Eine Verschiebung nach `contracts/` ist erst sinnvoll, wenn weitere Consumer
entstehen oder der Contract unabhaengig versioniert werden muss. Fuer diesen
Recovery-Slice waere sie zusaetzliche Migration ohne Reliability-Gewinn.

## 5. Tests

### 5.1 Unit- und Contract-Tests

Neue Tests in `tests/test_pipeline_codebook_config.py` belegen:

- Der konfigurierte Codebook-Pfad wird verwendet.
- Ein fehlendes, leeres oder strukturell kaputtes Codebook wirft
  `CodebookConfigError`.
- `CodebookConfigError` ist keine Unterklasse von `ExtractionConfigError`.

Bestehende Tests werden gehaertet statt dupliziert:

- `tests/test_pipeline.py::TestPipelineCodebookBinding` prueft bereits, dass
  das echte Codebook deutlich mehr als eine minimale Hardcode-Liste liefert.
- `tests/test_pipeline_codebook_guard.py` prueft weiterhin:
  `military.airstrike` ist gueltig und unbekannte LLM-Typen werden auf
  `other.unclassified` remapped.
- `tests/test_gdelt_cameo_mapping.py` verwendet
  `Settings.event_codebook_path` statt eigener Pfadarithmetik.

Ein neuer statischer `tests/test_docker_runtime_contract.py` prueft:

- `.dockerignore` existiert am Repo-Root und schliesst `.env`, `.git`,
  Worktrees und lokale Environments aus.
- `services/data-ingestion/uv.lock` existiert und `.gitignore` enthaelt die
  enge Re-Include-Regel.
- Der Dockerfile verwendet Root-Kontext-Pfade sowie
  `uv sync --locked --no-dev` in beiden Stufen.
- Beide Compose-Services zeigen auf denselben Root-Build-Kontext.
- Der Dockerfile enthaelt kein pauschales `COPY . .`.

Die Packaging-Contract-Aenderung ist test-first: Der neue Test ist vor dem
atomaren Packaging-Commit rot.

### 5.2 Clean-Build-Smoke-Test

Aus dem Repo-Root:

```bash
set -euo pipefail
trap 'docker image rm -f odin-data-ingestion-audit >/dev/null 2>&1 || true' EXIT

docker build -f services/data-ingestion/Dockerfile -t odin-data-ingestion-audit .
docker run --rm --entrypoint /app/.venv/bin/python odin-data-ingestion-audit \
  -c "import scheduler; import pipeline; assert 'military.airstrike' in pipeline._VALID_CODEBOOK_TYPES"
docker run --rm --entrypoint sh odin-data-ingestion-audit \
  -c '! test -e /app/.env'
docker run --rm --entrypoint odin-qdrant-doctor odin-data-ingestion-audit --help
docker run --rm --entrypoint odin-infra-atlas odin-data-ingestion-audit --help
```

Der Test braucht keine laufenden Infrastruktur-Container. Er prueft nur den
ausgelieferten Runtime-Vertrag. Der Trap entfernt das Audit-Image auch bei
einem fehlgeschlagenen Zwischenschritt.

### 5.3 Service-Suite

Aus `services/data-ingestion`:

```bash
uv run pytest
uv run ruff check .
uv lock --check
git ls-files --error-unmatch uv.lock
```

## 6. Explizit Out of Scope

- Umzug des Event-Codebooks nach `contracts/`.
- Shared-Python-Package zwischen Intelligence und Data Ingestion.
- Aenderung der Event-Taxonomie.
- Umbau der Collector-Scheduler-Architektur.
- Bit-identische OCI-Builds, Base-Image-Digest-Pins und SBOM-Attestierung.
- NLM-Report-Integration oder Evidence-Contract.
- Ein Docker-Compose-Rewrite.

## 7. Implementation Record

Der Codebook-Vertrag wurde in `4758616` umgesetzt. Der atomare Packaging-Slice
folgte in `c7d6499`; `0b813c1` stellte den Runtime-Entrypoint anschliessend auf
den bereits gebauten venv-Python um, damit der Container beim Start weder
Dependencies neu aufloest noch Netzwerkzugriff benoetigt. Spaetere Module wurden
dem Dockerfile unter demselben getesteten Packaging-Vertrag hinzugefuegt. Diese
Spec ist ein Design- und Entscheidungsrecord, kein offener Arbeitsplan.
