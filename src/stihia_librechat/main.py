"""Stihia LibreChat proxy — FastAPI application.

A lightweight reverse proxy that sits between LibreChat and OpenAI.
It transparently forwards requests while applying Stihia guardrails
in parallel.

Meta-request detection: LibreChat custom endpoints send title generation
as regular chat completions. The proxy detects these via literal substring
matching and segregates them onto a separate ``thread_key``
(``{thread_key}:meta:title``) to keep thread histories clean.
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from stihia import StihiaClient
from stihia_librechat import adapters
from stihia_librechat.proxy import (
    proxy_non_streaming,
    proxy_streaming,
)
from stihia_librechat.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_settings: Settings | None = None
_http_client: httpx.AsyncClient | None = None
_stihia_client: StihiaClient | None = None

_allowed_hosts: frozenset[str] = frozenset()


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared HTTP client, raising if the app hasn't started."""
    if _http_client is None:
        raise RuntimeError("HTTP client not initialised (app not started)")
    return _http_client


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _http_client, _stihia_client, _allowed_hosts

    settings = _get_settings()
    logging.getLogger().setLevel(settings.LOG_LEVEL.upper())

    _http_client = httpx.AsyncClient(timeout=300.0, follow_redirects=True)

    if settings.STIHIA_API_KEY:
        _stihia_client = StihiaClient(
            api_key=settings.STIHIA_API_KEY,
            base_url=settings.STIHIA_API_URL,
            project_key=settings.STIHIA_PROJECT_KEY,
        )
        logger.info(
            "Stihia guardrails enabled (project=%s)",
            settings.STIHIA_PROJECT_KEY,
        )
    else:
        logger.warning("STIHIA_API_KEY not set — guardrails disabled")

    _allowed_hosts = frozenset(h.strip().lower() for h in settings.ALLOWED_UPSTREAM_HOSTS.split(",") if h.strip())

    yield

    if _http_client:
        await _http_client.aclose()
        _http_client = None
    if _stihia_client:
        await _stihia_client.aclose()
        _stihia_client = None


_boot_settings = _get_settings()

app = FastAPI(
    title="Stihia LibreChat Proxy",
    description="API for the Stihia Security and Compliance Platform.",
    version=_boot_settings.STIHIA_LIBRECHAT_VERSION,
    docs_url="/docs" if _boot_settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if _boot_settings.ENVIRONMENT != "production" else None,
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Known LibreChat title-generation prompt fingerprints (literal substrings).
# Uses plain ``in`` checks instead of regex to guarantee O(n) matching with
# zero backtracking risk on arbitrarily large conversation payloads.
#
# Sources (commit 8e0ff93b in danny-avila/agents, 7e2b5169 in LibreChat):
#   1. Structured method (default): agents/src/utils/title.ts L10-13
#   2. Completion method:           agents/src/utils/title.ts L125-129
#   3. Assistants endpoint:         api/server/services/.../title.js L17-21
_STRUCTURED_FINGERPRINTS = (
    "analyze this conversation and provide:",
    "concise title",
    "5 words or less",
)
_COMPLETION_FINGERPRINT = "5-word-or-less title for the conversation"
_ASSISTANTS_FINGERPRINT = "please generate a concise title (max 40 characters) for a conversation that starts with:"


def _is_title_request(messages: list[dict[str, str]]) -> bool:
    """Detect LibreChat title generation requests via literal substring matching.

    Custom ``titlePrompt`` overrides in librechat.yaml are intentionally
    NOT matched — we cannot predict arbitrary user-defined prompts.
    """
    if not messages:
        return False

    content = messages[-1].get("content", "")
    if not content:
        return False

    lower = content.lower()

    if all(fp in lower for fp in _STRUCTURED_FINGERPRINTS):
        return True
    if _COMPLETION_FINGERPRINT in lower:
        return True

    return _ASSISTANTS_FINGERPRINT in lower


def _extract_sense_kwargs(
    request: Request,
    *,
    process_key: str = "unknown",
    messages: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    """Build Stihia key kwargs from request headers and the parsed body.

    ``process_key`` is the model name (for direct model conversations) or
    agent identifier (for agent conversations). Callers extract it from the
    request body (``body["model"]``) or URL path parameter and pass it in
    explicitly.

    When ``messages`` are provided and match a known meta-request pattern
    (e.g. LibreChat title generation), the ``thread_key`` is suffixed with
    ``:meta:title`` to segregate meta traffic from real conversation threads.
    """
    thread_key = request.headers.get("x-conversation-id", "unknown")

    if messages and _is_title_request(messages):
        thread_key = f"{thread_key}:meta:title"
        logger.debug("Title generation detected — thread_key=%s", thread_key)

    return {
        "user_key": request.headers.get("x-user-id", "unknown"),
        "process_key": process_key,
        "thread_key": thread_key,
        "run_key": request.headers.get("x-message-id", "unknown"),
    }


def _is_streaming(body: dict) -> bool:
    """Check if the request asks for SSE streaming."""
    return bool(body.get("stream"))


def _raw_headers(request: Request) -> dict[str, str]:
    return {k: v for k, v in request.headers.items()}


def _upstream_base(request: Request) -> str | None:
    return request.headers.get("x-upstream-base-url")


def _validate_upstream(base_url: str) -> str | None:
    """Validate that the upstream URL points to an allowed host.

    Returns an error message if the host is not in the allowlist,
    or ``None`` if the URL is acceptable.
    """
    try:
        parsed = urlparse(base_url)
    except Exception:
        return "Invalid X-Upstream-Base-URL"

    host = (parsed.hostname or "").lower()
    if host not in _allowed_hosts:
        return f"Upstream host {host!r} is not in the allowlist. Allowed: {sorted(_allowed_hosts)}"
    return None


def _parse_json(raw_body: bytes) -> tuple[dict | None, str | None]:
    """Parse JSON from raw bytes, returning ``(body, error)``."""
    try:
        return json.loads(raw_body), None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"Invalid JSON body: {exc}"


def _warn_if_skipping_guardrails(
    *,
    provider: str,
    process_key: str,
    body: dict,
    messages: list[dict[str, str]],
) -> None:
    if _stihia_client is not None and not messages:
        logger.warning(
            "Skipping Stihia guardrails due to empty parsed messages (provider=%s, model=%s, body_keys=%s)",
            provider,
            process_key,
            sorted(body.keys()),
        )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# OpenAI  /v1/chat/completions
# ---------------------------------------------------------------------------


@app.api_route("/v1/chat/completions", methods=["POST"])
async def openai_proxy(request: Request) -> Response:
    """Proxy OpenAI-compatible chat completion requests."""
    base = _upstream_base(request)
    if not base:
        return JSONResponse(
            {"error": {"message": "Missing X-Upstream-Base-URL header"}},
            status_code=400,
        )
    err = _validate_upstream(base)
    if err:
        return JSONResponse({"error": {"message": err}}, status_code=403)

    raw_body = await request.body()
    body, parse_err = _parse_json(raw_body)
    if body is None:
        return JSONResponse(
            {"error": {"message": parse_err}},
            status_code=400,
        )

    messages = adapters.openai_messages(body)
    settings = _get_settings()
    stihia_messages = messages if settings.STIHIA_SEND_FULL_HISTORY else adapters.latest_with_system(messages)
    process_key = body.get("model", "unknown")
    _warn_if_skipping_guardrails(
        provider="openai",
        process_key=process_key,
        body=body,
        messages=stihia_messages,
    )
    sense_kwargs = _extract_sense_kwargs(
        request,
        process_key=process_key,
        messages=messages,
    )
    upstream_url = base.rstrip("/") + "/v1/chat/completions"

    client = _get_http_client()

    if _is_streaming(body):
        status, headers, stream = await proxy_streaming(
            client=client,
            stihia_client=_stihia_client,
            upstream_url=upstream_url,
            method="POST",
            headers=_raw_headers(request),
            body=raw_body,
            messages=stihia_messages,
            sense_kwargs=sense_kwargs,
            chunk_to_text=adapters.openai_chunk_text,
        )
        return StreamingResponse(
            stream,
            status_code=status,
            headers=headers,
            media_type="text/event-stream",
        )

    status, headers, content = await proxy_non_streaming(
        client=client,
        stihia_client=_stihia_client,
        upstream_url=upstream_url,
        method="POST",
        headers=_raw_headers(request),
        body=raw_body,
        messages=stihia_messages,
        sense_kwargs=sense_kwargs,
    )
    return Response(content=content, status_code=status, headers=headers)
