# Stihia LibreChat Proxy Dockerfile
# Multi-stage build for optimized production image

# --- Build Stage ---
FROM python:3.14-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy workspace files
COPY backend/pyproject.toml backend/uv.lock ./backend/
COPY backend/libs ./backend/libs
COPY backend/services/stihia-librechat ./backend/services/stihia-librechat

WORKDIR /app/backend

# Create venv and build workspace packages as wheels for proper installation
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN uv venv $UV_PROJECT_ENVIRONMENT && \
    uv sync --frozen --no-dev --no-editable --package stihia-librechat

# --- Production Stage ---
FROM python:3.14-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment (includes all dependencies as proper packages)
COPY --from=builder /app/.venv /app/.venv

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 4005

# Run with gunicorn
CMD ["gunicorn", "stihia_librechat.main:app", \
        "--bind", "0.0.0.0:4005", \
        "--workers", "1", \
        "--worker-class", "uvicorn.workers.UvicornWorker", \
        "--timeout", "300", \
        "--keep-alive", "5", \
        "--access-logfile", "-", \
        "--error-logfile", "-"]
