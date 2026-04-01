# Stihia LibreChat Bundle

[![CI](https://github.com/stihia-ai/stihia-librechat/actions/workflows/ci.yml/badge.svg)](https://github.com/stihia-ai/stihia-librechat/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/stihia-ai/stihia-librechat)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

Dockerised LibreChat setup with a Stihia AI security proxy for real-time threat detection.

## Vision & Scope

**Goal:** Provide a turnkey, self-hosted LibreChat deployment with built-in
real-time threat detection powered by Stihia.

**In scope:**

- Transparent HTTP proxy that applies [Stihia](https://stihia.ai)
  real-time threat detection to LLM requests.
- Docker Compose stack that bundles LibreChat, MongoDB, Meilisearch, RAG API,
  and the Stihia AI security proxy.
- Configuration and deployment documentation.

**Out of scope:**

- The Stihia AI security engine itself (provided by the Stihia API and wrapped by the [`stihia`](https://github.com/stihia-ai/stihia-sdk-python) Python SDK package).
- LibreChat core development — this repo uses official LibreChat Docker images.
- Hosting or managed service offerings.

## Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md)
before opening a pull request. This project follows a
[Code of Conduct](CODE_OF_CONDUCT.md).

To report a security vulnerability see [SECURITY.md](SECURITY.md).

## Third-party licensing

This bundle is designed to run with the official LibreChat images. LibreChat is
a separate open-source project licensed under the [MIT License](https://github.com/danny-avila/LibreChat/blob/main/LICENSE).

This repository contains the Stihia integration and configuration for that
deployment and does not include LibreChat source code.

## What's included

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full LibreChat stack (MongoDB, Meilisearch, RAG API) + Stihia Proxy |
| `librechat.yaml` | Custom endpoints that route LLM requests through the proxy |
| `.env.example` | Template for API keys |
| `Dockerfile` | Multi-stage build for the proxy service |
| `src/stihia_librechat/` | FastAPI proxy source code |

## Quick start

```bash
# 1. Configure your API keys
cp .env.example .env
# Edit .env — add your STIHIA_API_KEY, LLM provider keys, and RAG Postgres credentials

# 2. Launch everything
docker compose up
```

LibreChat is available at **http://localhost:3080**.

## Architecture

```
LibreChat  ──▶  Stihia Proxy (:4005)  ──▶  LLM Provider (OpenAI / Anthropic / Gemini)
                      │
                      ├─ Input sensor  (default-input-think)
                      └─ Output sensor (default-output)
                             │
                             ▼
                        Stihia API
```

The proxy is transparent — it forwards HTTP requests as-is to the upstream
provider while applying Stihia `SenseGuard` sensors in parallel.

### Supported providers

| Provider | Endpoint(s) |
|---|---|
| OpenAI | `/v1/chat/completions` |
| Anthropic | `/v1/messages` |
| Google Gemini | `/v1beta/models/{model}:generateContent`, `/v1beta/models/{model}:streamGenerateContent` |

### Streaming vs non-streaming

- **Streaming**: Uses `SenseGuard.shield()` to wrap the upstream SSE stream.
  Input sensors gate the first chunk; output sensors run on stream completion.
- **Non-streaming**: Input sensors and LLM request run in parallel. If input
  triggers, the LLM response is discarded and an error is returned. Output
  sensors run on the complete response before it is returned.

### Stihia key mapping

| Stihia Key | Source | Fallback |
|---|---|---|
| `project_key` | `STIHIA_PROJECT_KEY` env var | `"default"` |
| `user_key` | `X-User-ID` header | `"unknown"` |
| `process_key` | `X-Process-Key` header | `"unknown"` |
| `thread_key` | `X-Conversation-ID` header | `"unknown"` |
| `run_key` | `X-Message-ID` header | `"unknown"` |

### Fail-open behavior

If the Stihia API is unreachable or returns an error, the proxy **does not
block LibreChat**. LLM requests are forwarded normally and responses are
returned to the user. Errors are logged to stderr.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `STIHIA_API_KEY` | *(empty)* | Stihia API key (guardrails disabled when empty) |
| `STIHIA_API_URL` | `https://api.stihia.ai` | Stihia API base URL |
| `STIHIA_PROJECT_KEY` | `librechat` | Stihia project key |
| `ALLOWED_UPSTREAM_HOSTS` | *(see below)* | Comma-separated allowlist of upstream hostnames |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `OPENAI_API_KEY` | — | OpenAI API key (passed through to provider) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (passed through to provider) |
| `GOOGLE_GEMINI_API_KEY` | — | Google Gemini API key (passed through to provider) |
| `CREDS_KEY` | — | **Required** — 32-byte hex key (64 chars) for credential encryption |
| `CREDS_IV` | — | **Required** — 16-byte hex IV (32 chars) for credential encryption |
| `JWT_SECRET` | — | **Required** — 32-byte hex key (64 chars) for signing access tokens |
| `JWT_REFRESH_SECRET` | — | **Required** — 32-byte hex key (64 chars) for signing refresh tokens |
| `LIBRECHAT_RAG_POSTGRES_DB` | — | Required Postgres database name for the RAG API pgvector store |
| `LIBRECHAT_RAG_POSTGRES_USER` | — | Required Postgres user for the RAG API pgvector store |
| `LIBRECHAT_RAG_POSTGRES_PASSWORD` | — | Required strong Postgres password for the RAG API pgvector store |
| `LIBRECHAT_RAG_POSTGRES_PORT` | `5432` | Optional internal Postgres port that the RAG API uses when dialing `vectordb` |

Set unique production values through your deployment environment or a non-committed
`.env` file.

When storing passwords in `.env`, escape each `$` as `$$`. Docker Compose
interpolates `.env` values, so an unescaped `$` can silently corrupt a strong password.

The bundled pgvector database image is pinned to `pgvector/pgvector:0.8.2-pg15`
to avoid drift from `latest` in production deployments while remaining compatible
with existing PostgreSQL 15 data volumes.

If you upgrade the pgvector image to a newer PostgreSQL major, migrate or rebuild
the `vectordb_data` volume first. Reusing a PostgreSQL 15 data directory with PostgreSQL 16+
or 17 will fail at container startup.

## Development

Run the proxy locally (without Docker):

```bash
# 1. Clone the repo
git clone git@github.com:stihia-ai/stihia-librechat.git

# 2. Install the `uv` package manager, if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Create and activate Python venv
uv venv
source .venv/bin/activate

# 4. Install dependencies (including dev extras)
uv sync --extra dev

# 5. Start the dev server
uvicorn stihia_librechat.main:app --reload --port 4005
```

Run tests:

```bash
uv run pytest tests -v
```

Run linting and type checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```
