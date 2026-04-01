# Stihia LibreChat Bundle

Dockerised LibreChat setup with a Stihia guardrail proxy for real-time threat detection.

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
cd backend/services/stihia-librechat

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
                      ├─ Input guardrail  (default-input-think)
                      └─ Output guardrail (default-output)
                             │
                             ▼
                        Stihia API
```

The proxy is transparent — it forwards HTTP requests as-is to the upstream
provider while applying Stihia `SenseGuard` guardrails in parallel.

### Supported providers

| Provider | Endpoint(s) |
|---|---|
| OpenAI | `/v1/chat/completions` |
| Anthropic | `/v1/messages` |
| Google Gemini | `/v1beta/models/{model}:generateContent`, `/v1beta/models/{model}:streamGenerateContent` |

### Streaming vs non-streaming

- **Streaming**: Uses `SenseGuard.shield()` to wrap the upstream SSE stream.
  Input guardrails gate the first chunk; output guardrails run on stream completion.
- **Non-streaming**: Input guard and LLM request run in parallel. If input
  triggers, the LLM response is discarded and an error is returned. Output
  guardrails run on the complete response before it is returned.

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

The Compose stack now refuses to start if `LIBRECHAT_RAG_POSTGRES_DB`,
`LIBRECHAT_RAG_POSTGRES_USER`, or `LIBRECHAT_RAG_POSTGRES_PASSWORD` are missing.
Set unique production values through your deployment environment or a non-committed
`.env` file.

When storing passwords in `.env`, escape each `$` as `$$`. Docker Compose
interpolates `.env` values, so an unescaped `$` can silently corrupt a strong password.

The bundled pgvector database image is pinned to `pgvector/pgvector:0.8.2-pg15`
to avoid drift from `latest` in production deployments while remaining compatible
with existing PostgreSQL 15 data volumes.

If you later upgrade the pgvector image to a newer PostgreSQL major, migrate or rebuild
the `vectordb_data` volume first. Reusing a PostgreSQL 15 data directory with PostgreSQL 16+
or 17 will fail at container startup.

## Development

Run the proxy locally (without Docker):

```bash
cd backend
uv sync --all-packages --extra dev
cd services/stihia-librechat
uvicorn stihia_librechat.main:app --reload --port 4005
```

Run tests:

```bash
cd backend
uv run pytest services/stihia-librechat/tests -v
```
