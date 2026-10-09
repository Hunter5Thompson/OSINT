FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
ENV EVENT_CODEBOOK_PATH="/app/runtime_contracts/event_codebook.yaml"

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.10.0@sha256:78a7ff97cd27b7124a5f3c2aefe146170793c56a1e03321dd31a289f6d82a04f /uv /usr/local/bin/uv

# Copy dependency definition first for layer caching
COPY services/data-ingestion/pyproject.toml .
COPY services/data-ingestion/uv.lock .

# Install dependencies
RUN uv sync --locked --no-dev --no-install-project

# Copy application code
COPY services/data-ingestion/config.py .
COPY services/data-ingestion/canonicalize.py .
COPY services/data-ingestion/qdrant_spatial.py .
COPY services/data-ingestion/source_spatial.py .
COPY services/data-ingestion/pipeline.py .
COPY services/data-ingestion/scheduler.py .
COPY services/data-ingestion/build_revision.py .
COPY services/data-ingestion/tracing.py services/data-ingestion/spark_trace_reporter.py ./
COPY services/data-ingestion/feeds/ feeds/
COPY services/data-ingestion/gdelt_raw/ gdelt_raw/
COPY services/data-ingestion/graph_integrity/ graph_integrity/
COPY services/data-ingestion/migrations/location_spatial_scope_indexes.cypher migrations/location_spatial_scope_indexes.cypher
COPY services/data-ingestion/nlm_ingest/ nlm_ingest/
COPY services/data-ingestion/infra_atlas/ infra_atlas/
COPY services/data-ingestion/spatial_catalog/__init__.py spatial_catalog/__init__.py
COPY services/data-ingestion/spatial_catalog/identity.py spatial_catalog/identity.py
COPY services/data-ingestion/spatial_catalog/manifest.py spatial_catalog/manifest.py
COPY services/data-ingestion/spatial_catalog/models.py spatial_catalog/models.py
COPY services/data-ingestion/spatial_catalog/normalize.py spatial_catalog/normalize.py
COPY services/data-ingestion/spatial_catalog/source_lock.py spatial_catalog/source_lock.py
COPY services/data-ingestion/spatial_catalog/topology.py spatial_catalog/topology.py
COPY services/data-ingestion/spatial_catalog/catalog-plan.json spatial_catalog/catalog-plan.json
COPY services/data-ingestion/spatial_catalog/data/country_crosswalk.json spatial_catalog/data/country_crosswalk.json
COPY services/backend/data/spatial/ data/spatial/
COPY services/data-ingestion/suv_structured/ suv_structured/
COPY services/data-ingestion/qdrant_doctor/ qdrant_doctor/
COPY services/intelligence/codebook/event_codebook.yaml runtime_contracts/event_codebook.yaml

# Install the local project so console-script entrypoints are available.
RUN uv sync --locked --no-dev

ARG ODIN_BUILD_REVISION=unknown
RUN python -c "import os, pathlib, re; r = os.environ['ODIN_BUILD_REVISION']; assert r == 'unknown' or re.fullmatch('[0-9a-f]{40}', r), 'invalid build revision'; pathlib.Path('/app/.build-revision').write_text(r + '\\n')"
LABEL org.opencontainers.image.revision=$ODIN_BUILD_REVISION

# Use only the environment baked into the image. --no-sync forbids runtime
# dependency resolution or downloads.
CMD ["uv", "run", "--no-sync", "python", "scheduler.py"]
