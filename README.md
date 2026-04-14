# Stihia LibreChat Bundle

[![CI](https://github.com/stihia-ai/stihia-librechat/actions/workflows/ci.yml/badge.svg)](https://github.com/stihia-ai/stihia-librechat/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/stihia-ai/stihia-librechat)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

Dockerised [LibreChat](https://www.librechat.ai/) setup with a [Stihia](https://stihia.ai/) AI security proxy for real-time threat detection.

## Vision

**Goal:** Provide a turnkey, self-hosted LibreChat deployment with built-in
real-time threat detection powered by Stihia.

## Getting Started

This guide takes you from zero to a fully protected, self-hosted AI chat
interface in under 10 minutes.

> [!CAUTION]
> **The default configuration is for local development only and is not suitable for production.**
> Auto-generated secrets, default database credentials, and exposed ports must be replaced
> before deploying to any shared or public environment.
> See [Environment variables](#environment-variables) for the full list of values to set.

### Prerequisites

| Requirement | Notes |
|---|---|
| [Docker](https://docs.docker.com/get-docker/) & Docker Compose | v2+ recommended |
| A **Stihia API key** | Free — see Step 1 below |
| An **OpenAI API key** | [OpenAI](https://platform.openai.com/api-keys) |

### Step 1 — Create your Stihia account and API key

> **Note:** By default this project connects to the **cloud-hosted Stihia platform** ([api.stihia.ai](https://api.stihia.ai)).
> To use a locally hosted Stihia instance instead, set the `STIHIA_API_URL` environment variable in your `.env` file
> (see [Environment variables](#environment-variables)).

1. Sign up for a free account at **[app.stihia.ai](https://app.stihia.ai)**.
2. Create a new **organization** — this is where your projects, team members,
   and API keys live.
3. *(Optional)* Go to **[Your Profile → Organization → Notification Settings](https://app.stihia.ai/organization)**
   to receive email alerts when Stihia detects a threat.
4. Navigate to **[Your Profile → Organization → API Keys](https://app.stihia.ai/organization)**
   and click **Create API Key**. Copy the key (it starts with `sk_`).

> **Keep your API key safe.** Treat it like a password — never commit it to
> version control. You'll store it in a local `.env` file in the next step.

### Step 2 — Clone and configure

```bash
git clone https://github.com/stihia-ai/stihia-librechat.git
cd stihia-librechat
cp .env.example .env  # Create a local .env file from the example template
```

> [!CAUTION]
> Storing unencrypted credentials in `.env` is not recommended for production.
> Use a secrets manager or encrypted vault solution where possible.

Open `.env` in your editor and fill in:

| Variable | Where to get it |
|---|---|
| `STIHIA_API_KEY` | The `sk_…` key from Step 1 |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |

`CREDS_KEY`, `CREDS_IV`, `JWT_SECRET`, and `JWT_REFRESH_SECRET` are
auto-generated during `docker compose up` when left blank. RAG Postgres
credentials also have local defaults when unset. If running on production,
make sure to set these values explicitly as environment variables.
See [Environment variables](#environment-variables) for details.

### Step 3 — Launch

```bash
docker compose up --build
```

On Linux, add `sudo` only if your current user does not have permission to talk
to the Docker daemon on that host.

This starts the entire stack: LibreChat, MongoDB, Meilisearch, the RAG API
with pgvector, and the Stihia security proxy.

`docker compose up --build` stays attached to container logs. That is normal.
The stack can still be healthy and usable while logs continue to stream.

If you want it to keep running in the background instead:

```bash
docker compose up -d --build
docker compose logs -f
```

Stop the stack with:

```bash
docker compose down
```

The Compose services already use `restart: unless-stopped`, so detached mode is
usually enough. You do not need to wrap the bundle in an extra OS service for a
normal installation.

### Step 4 — Start chatting

1. Open the LibreChat URL for your deployment:
   - Local machine: **[http://localhost:3080](http://localhost:3080)**
   - Another machine on your LAN or VPN: `http://<server-ip-or-hostname>:3080`
   - Reverse-proxied deployment: your configured LibreChat domain
2. Create a new LibreChat user on first login.
   Your LibreChat account is separate from your Stihia account and API key.
3. If LibreChat opens on the MCP view first, click **Start chatting** to switch
   to the regular chat interface.
4. Pick a model and send a message. Every request now flows through the Stihia
   proxy, which runs real-time threat detection on both inputs and outputs
   (see [Architecture](#architecture)).

> **Note:** You may experience an initial delay in the response to your first message.
> This is normal as the system initializes. Subsequent messages should be faster.

> **Note:** If this bundle is deployed behind a reverse proxy or on a shared
> server, set `DOMAIN_CLIENT`, `DOMAIN_SERVER`, and `TRUST_PROXY` in `.env`
> before handing it to other users. See [LibreChat docs](#librechat-docs).

### Step 5 — View your threat detection traces

Open the **[Stihia Console → Threads](https://app.stihia.ai/threads)** to see
a live timeline of every detection, drill into individual traces, and review
threat severity across your project.

### What Stihia sees

- In this bundle, LibreChat is configured to expose the custom endpoint that
  routes model traffic through the Stihia proxy.
- That means AI chat requests in the default bundle flow through Stihia before
  they reach the upstream model provider.
- By default, `STIHIA_SEND_FULL_HISTORY=true`, so the full conversation history
  is sent to Stihia for evaluation. Set it to `false` if you want Stihia to see
  only the system prompt(s) and latest message.
- Provider API keys such as `OPENAI_API_KEY` are forwarded to the model
  provider and are not sent to Stihia.
- Detection traces are visible in the [Stihia Console](https://app.stihia.ai/threads) so security teams can
  review what was flagged.

### What can I configure?

**Stihia guardrails**

- `STIHIA_INPUT_SENSOR` controls which Stihia sensor evaluates incoming user
  prompts.
- `STIHIA_OUTPUT_SENSOR` controls which Stihia sensor evaluates model outputs.
- The default sensors (`default-input-think`, `default-output`) cover common
  prompt injections, PII leakage, and destructive actions.
- To switch to a different Stihia sensor, set the sensor name in `.env` and
  restart the stack.

Example:

```bash
STIHIA_INPUT_SENSOR=default-input-think
STIHIA_OUTPUT_SENSOR=default-output
```

See the [API reference](https://stihia.ai/api/reference/) for more details about sensors.

If you already have custom sensors in your Stihia project, point these
variables at those sensor names. If you need industry-specific compliance,
custom threat categories, or tuned sensitivity,
contact **[support@stihia.ai](mailto:support@stihia.ai)**.

**LibreChat access and abuse controls**

- `ALLOW_REGISTRATION` controls whether users can self-register.
- LibreChat also supports login, registration, and message rate limits, plus
  automated banning for abuse. See [LibreChat docs](#librechat-docs) for
  `LOGIN_MAX`, `REGISTER_MAX`, `BAN_VIOLATIONS`, `LIMIT_MESSAGE_IP`, and
  related settings.

**Deployment controls**

- `ALLOWED_UPSTREAM_HOSTS` restricts which upstream model hosts the proxy may
  contact.
- `DOMAIN_CLIENT`, `DOMAIN_SERVER`, and `TRUST_PROXY` matter when exposing the
  bundle on a server, VPN, or public domain.

For the full API surface, see the
**[Stihia API Reference](https://stihia.ai/api/reference/)** and the
**[Stihia Python SDK](https://github.com/stihia-ai/stihia-sdk-python)**.

## Architecture

```
LibreChat  ──▶  Stihia Proxy (:4005)  ──▶  LLM Provider (OpenAI)
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

### Streaming vs non-streaming

- **Streaming**: Uses `SenseGuard.shield()` to wrap the upstream SSE stream.
  Input sensors gate the first chunk; output sensors run periodically every 30 chunks
  during streaming and once more on stream completion. If a threat is detected
  mid-stream, the proxy appends a block message and terminates the response.
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

### Resource sizing

This bundle runs more than the LibreChat web UI. The default Docker stack starts
LibreChat, MongoDB, Meilisearch, the RAG API, PostgreSQL with pgvector, and the
Stihia proxy.

Use the following as conservative starting points rather than hard limits:

| Scenario | CPU | RAM | Disk | Notes |
|---|---|---|---|---|
| Local evaluation / demo | 4 vCPU | 8 GB | 20 GB | Enough for trying the bundle with light chat usage |
| Small shared internal install | 4-8 vCPU | 16 GB | 50 GB | Better fit for multiple users, logs, and RAG data growth |
| Heavier document / RAG usage | 8+ vCPU | 16+ GB | 100+ GB | Increase disk and RAM as uploads, indexes, and histories grow |

Actual usage depends heavily on concurrent users, retained chat history,
uploaded files, and whether you use RAG heavily.

## What's included

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full LibreChat stack (MongoDB, Meilisearch, RAG API) + Stihia Proxy |
| `librechat.yaml` | Custom endpoints that route LLM requests through the proxy |
| `.env.example` | Template for API keys and other environment variables |
| `Dockerfile` | Multi-stage build for the proxy service |
| `src/stihia_librechat/` | FastAPI proxy source code |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `STIHIA_API_KEY` | *(empty)* | Stihia API key (guardrails disabled when empty) |
| `STIHIA_API_URL` | `https://api.stihia.ai` | Stihia API base URL |
| `STIHIA_PROJECT_KEY` | `librechat` | Stihia project key |
| `STIHIA_INPUT_SENSOR` | `default-input-think` | Stihia sensor used for prompt / input inspection |
| `STIHIA_OUTPUT_SENSOR` | `default-output` | Stihia sensor used for model output inspection |
| `STIHIA_SEND_FULL_HISTORY` | `true` | Send full conversation history to Stihia instead of only the system prompt and latest message |
| `ALLOWED_UPSTREAM_HOSTS` | `api.openai.com` | Comma-separated allowlist of upstream hostnames the proxy may contact |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `OPENAI_API_KEY` | — | OpenAI API key (passed through to provider) |
| `ALLOW_REGISTRATION` | `true` | Allow users to self-register a LibreChat account |
| `DOMAIN_CLIENT` | `http://localhost:3080` | Public browser-facing LibreChat URL for remote or reverse-proxied installs |
| `DOMAIN_SERVER` | `http://localhost:3080` | Server-side LibreChat base URL for remote or reverse-proxied installs |
| `TRUST_PROXY` | `1` | Proxy hop count when LibreChat runs behind Nginx, Caddy, Traefik, or a load balancer |
| `CREDS_KEY` | *(auto-generated if empty)* | 32-byte hex key (64 chars) for credential encryption |
| `CREDS_IV` | *(auto-generated if empty)* | 16-byte hex IV (32 chars) for credential encryption |
| `JWT_SECRET` | *(auto-generated if empty)* | 32-byte hex key (64 chars) for signing access tokens |
| `JWT_REFRESH_SECRET` | *(auto-generated if empty)* | 32-byte hex key (64 chars) for signing refresh tokens |
| `LIBRECHAT_RAG_POSTGRES_DB` | `librechat_rag` | Postgres database name for the RAG API pgvector store |
| `LIBRECHAT_RAG_POSTGRES_USER` | `librechat` | Postgres user for the RAG API pgvector store |
| `LIBRECHAT_RAG_POSTGRES_PASSWORD` | `librechat_dev_password_change_me` | Postgres password for the RAG API pgvector store |
| `LIBRECHAT_RAG_POSTGRES_PORT` | `5432` | Optional internal Postgres port that the RAG API uses when dialing `vectordb` |

For local onboarding, auto-generated/default values reduce setup friction.

For production, set unique values for all auth and database secrets through your
deployment environment.

When storing passwords in `.env`, escape each `$` as `$$`. Docker Compose
interpolates `.env` values, so an unescaped `$` can silently corrupt a strong password.

The bundled pgvector database image is pinned to `pgvector/pgvector:0.8.2-pg15`
to avoid drift from `latest` in production deployments while remaining compatible
with existing PostgreSQL 15 data volumes.

If you upgrade the pgvector image to a newer PostgreSQL major, migrate or rebuild
the `vectordb_data` volume first. Reusing a PostgreSQL 15 data directory with PostgreSQL 16+
or 17 will fail at container startup.

## LibreChat docs

- [Environment variables](https://www.librechat.ai/docs/configuration/dotenv)
- [Authentication](https://www.librechat.ai/docs/configuration/authentication)
- [Logging](https://www.librechat.ai/docs/configuration/logging)
- [Automated moderation and rate limiting](https://www.librechat.ai/docs/configuration/mod_system)
- [Custom endpoint configuration](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/custom_endpoint)

## Docker images

`docker compose up --build` pulls the following images:

| Image | Service | Purpose |
|---|---|---|
| `librechat/librechat:v0.8.4` | `librechat` | Chat web application ([Docker Hub](https://hub.docker.com/r/librechat/librechat)) |
| `mongo:7` | `mongodb` | Document database for LibreChat conversations, users, and settings |
| `getmeili/meilisearch:v1.12.8` | `meilisearch` | Full-text search engine for chat history |
| `pgvector/pgvector:0.8.2-pg15` | `vectordb` | PostgreSQL with pgvector extension for RAG embeddings |
| `ghcr.io/danny-avila/librechat-rag-api-dev-lite:v0.7.3` | `rag_api` | Retrieval-augmented generation API for file uploads and search |
| `python:3.14-slim` | `stihia-proxy` (build) | Base image for the Stihia security proxy |
| `ghcr.io/astral-sh/uv:latest` | `stihia-proxy` (build) | Provides the `uv` package manager binary during build |

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

## Scope

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

## License

This project is licensed under the [Apache License 2.0](LICENSE).

### Third-party licensing

This bundle is designed to run with the official LibreChat images. LibreChat is
a separate open-source project licensed under the [MIT License](https://github.com/danny-avila/LibreChat/blob/main/LICENSE).

This repository contains the Stihia integration and configuration for that
deployment and does not include LibreChat source code.
