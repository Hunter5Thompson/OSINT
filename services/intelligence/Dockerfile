FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.10.0@sha256:78a7ff97cd27b7124a5f3c2aefe146170793c56a1e03321dd31a289f6d82a04f /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

ARG ODIN_BUILD_REVISION=unknown
RUN python -c "import os, pathlib, re; r = os.environ['ODIN_BUILD_REVISION']; assert r == 'unknown' or re.fullmatch('[0-9a-f]{40}', r), 'invalid build revision'; pathlib.Path('/app/.build-revision').write_text(r + '\\n')"
LABEL org.opencontainers.image.revision=$ODIN_BUILD_REVISION

EXPOSE 80
CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
