FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency definition first for layer caching
COPY pyproject.toml .

# Install dependencies
RUN uv sync --no-dev

# Copy application code
COPY config.py .
COPY scheduler.py .
COPY feeds/ feeds/

# Run the scheduler
CMD ["uv", "run", "python", "scheduler.py"]
