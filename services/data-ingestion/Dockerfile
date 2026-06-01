FROM python:3.12-slim

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
ENV EVENT_CODEBOOK_PATH="/app/runtime_contracts/event_codebook.yaml"

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv

# Copy dependency definition first for layer caching
COPY services/data-ingestion/pyproject.toml .
COPY services/data-ingestion/uv.lock .

# Install dependencies
RUN uv sync --locked --no-dev --no-install-project

# Copy application code
COPY services/data-ingestion/config.py .
COPY services/data-ingestion/pipeline.py .
COPY services/data-ingestion/scheduler.py .
COPY services/data-ingestion/feeds/ feeds/
COPY services/data-ingestion/gdelt_raw/ gdelt_raw/
COPY services/data-ingestion/nlm_ingest/ nlm_ingest/
COPY services/data-ingestion/infra_atlas/ infra_atlas/
COPY services/data-ingestion/qdrant_doctor/ qdrant_doctor/
COPY services/intelligence/codebook/event_codebook.yaml runtime_contracts/event_codebook.yaml

# Install the local project so console-script entrypoints are available.
RUN uv sync --locked --no-dev

# Run the scheduler with the built venv python (PATH points at /app/.venv/bin).
# Do NOT launch it through uv at runtime: that re-resolves dependencies at
# container start, pulling dev tooling (ruff/duckdb/...) and needing network.
CMD ["python", "scheduler.py"]
