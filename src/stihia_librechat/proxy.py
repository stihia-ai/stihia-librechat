"""Core proxy logic: streaming and non-streaming upstream forwarding with sensors."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

from stihia import SenseGuard, StihiaClient
from stihia.exceptions import StihiaError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "content-encoding",
        # Proxy-specific headers (not needed by upstream providers)
        "x-upstream-base-url",
        # LibreChat metadata headers (internal identifiers)
        "x-user-id",
        "x-conversation-id",
        "x-message-id",
        "x-process-key",
    }
)


# ---------------------------------------------------------------------------
# OpenAI-compatible sensor block responses
# ---------------------------------------------------------------------------

_INPUT_BLOCK_MSG = "⚠️ This message was blocked by a safety guardrail."
_OUTPUT_BLOCK_MSG = "⚠️ The response was blocked by a safety guardrail."


def _openai_block_response(message: str) -> bytes:
    """Build an OpenAI ``/v1/chat/completions`` JSON response for a blocked request."""
    return json.dumps(
        {
            "id": "guardrail-block",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": message},
                    "finish_reason": "stop",
                }
            ],
        }
    ).encode()


def _openai_block_sse(message: str) -> list[bytes]:
    """Build OpenAI-format SSE events for a blocked streaming request.

    Returns a list of raw SSE byte lines that LibreChat (and any OpenAI-compatible
    client) can parse: a role chunk, a content chunk, a finish chunk, and ``[DONE]``.
    """
    role_chunk = json.dumps(
        {
            "id": "guardrail-block",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }
            ],
        }
    )
    content_chunk = json.dumps(
        {
            "id": "guardrail-block",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": message},
                    "finish_reason": None,
                }
            ],
        }
    )
    finish_chunk = json.dumps(
        {
            "id": "guardrail-block",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
    )
    return [
        f"data: {role_chunk}\n\n".encode(),
        f"data: {content_chunk}\n\n".encode(),
        f"data: {finish_chunk}\n\n".encode(),
        b"data: [DONE]\n\n",
    ]


# ---------------------------------------------------------------------------
# Anthropic-compatible sensor block responses
# ---------------------------------------------------------------------------


def _anthropic_block_response(message: str) -> bytes:
    """Build an Anthropic ``/v1/messages`` JSON response for a blocked request."""
    return json.dumps(
        {
            "id": "guardrail-block",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": message}],
            "model": "guardrail",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
    ).encode()


def _anthropic_block_sse(message: str) -> list[bytes]:
    """Build Anthropic-format SSE events for a blocked streaming request."""
    msg_start = json.dumps(
        {
            "type": "message_start",
            "message": {
                "id": "guardrail-block",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "guardrail",
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
    )
    block_start = json.dumps(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
    )
    block_delta = json.dumps(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": message},
        }
    )
    block_stop = json.dumps({"type": "content_block_stop", "index": 0})
    msg_delta = json.dumps(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        }
    )
    msg_stop = json.dumps({"type": "message_stop"})
    return [
        f"event: message_start\ndata: {msg_start}\n\n".encode(),
        f"event: content_block_start\ndata: {block_start}\n\n".encode(),
        f"event: content_block_delta\ndata: {block_delta}\n\n".encode(),
        f"event: content_block_stop\ndata: {block_stop}\n\n".encode(),
        f"event: message_delta\ndata: {msg_delta}\n\n".encode(),
        f"event: message_stop\ndata: {msg_stop}\n\n".encode(),
    ]


# ---------------------------------------------------------------------------
# Gemini-compatible sensor block responses
# ---------------------------------------------------------------------------


def _gemini_block_response(message: str) -> bytes:
    """Build a Gemini ``generateContent`` JSON response for a blocked request."""
    return json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": message}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
        }
    ).encode()


def _gemini_block_sse(message: str) -> list[bytes]:
    """Build Gemini-format SSE events for a blocked streaming request."""
    chunk = json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": message}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
        }
    )
    return [f"data: {chunk}\n\n".encode()]


def _forward_headers(raw_headers: dict[str, str]) -> dict[str, str]:
    """Strip hop-by-hop, proxy-specific, and metadata headers."""
    return {k: v for k, v in raw_headers.items() if k.lower() not in _HOP_BY_HOP}


def _build_upstream_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


# ---------------------------------------------------------------------------
# Response text extractors (for output sensors)
# ---------------------------------------------------------------------------


def _extract_assistant_text(
    response_body: bytes,
) -> str:
    """Best-effort extraction of assistant text from provider JSON.

    Tries OpenAI, Anthropic, and Gemini response shapes in order.
    Includes tool call content alongside text so the output sensor
    can evaluate the full assistant turn.
    Falls back to the raw response text if parsing fails.
    """
    try:
        data = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response_body.decode("utf-8", errors="replace")

    # OpenAI: choices[].message.content + tool_calls
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        parts: list[str] = []
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", "")
                parts.append(f"[tool_call: {name}({args})]")
        if parts:
            return "\n".join(parts)

    # Anthropic: content[].text + tool_use blocks
    blocks = data.get("content")
    if isinstance(blocks, list):
        parts = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif b.get("type") == "tool_use":
                name = b.get("name", "")
                inp = b.get("input", {})
                parts.append(f"[tool_use: {name}({json.dumps(inp)})]")
        if parts:
            return "\n".join(parts)

    # Gemini: candidates[].content.parts[].text + functionCall
    candidates = data.get("candidates")
    if isinstance(candidates, list) and candidates:
        c_parts = candidates[0].get("content", {}).get("parts", [])
        texts: list[str] = []
        for p in c_parts:
            if not isinstance(p, dict):
                continue
            text = p.get("text")
            if isinstance(text, str):
                texts.append(text)
            fc = p.get("functionCall")
            if isinstance(fc, dict):
                name = fc.get("name", "")
                args = fc.get("args", {})
                texts.append(f"[function_call: {name}({json.dumps(args)})]")
        if texts:
            return "\n".join(texts)

    return response_body.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# SSE byte-stream wrapper for SenseGuard
# ---------------------------------------------------------------------------


async def _byte_chunks_to_lines(
    response: httpx.Response,
) -> AsyncIterator[bytes]:
    """Yield raw byte lines from an upstream SSE response."""
    async for line in response.aiter_lines():
        yield (line + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Streaming proxy
# ---------------------------------------------------------------------------


async def _guarded_stream(
    response: httpx.Response,
    guard: SenseGuard,
    *,
    block_sse_events: Callable[[str], list[bytes]] = _openai_block_sse,
) -> AsyncIterator[bytes]:
    """Wrap an upstream SSE stream with SenseGuard.

    Yields raw bytes so FastAPI ``StreamingResponse`` can forward them
    as-is. When a sensor triggers (input or output), emits a
    provider-appropriate SSE error sequence instead of silently closing.
    Always closes the upstream ``httpx.Response`` when done.
    """
    try:
        yielded_any = False
        async for chunk in guard.shield(_byte_chunks_to_lines(response)):
            yielded_any = True
            yield chunk

        if not yielded_any and guard.input_triggered:
            for event in block_sse_events(_INPUT_BLOCK_MSG):
                yield event
        elif not yielded_any and guard.output_triggered:
            for event in block_sse_events(_OUTPUT_BLOCK_MSG):
                yield event
    finally:
        await response.aclose()


async def _plain_stream(
    response: httpx.Response,
) -> AsyncIterator[bytes]:
    """Forward raw bytes, ensuring the response is closed afterwards."""
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()


async def proxy_streaming(
    *,
    client: httpx.AsyncClient,
    stihia_client: StihiaClient | None,
    upstream_url: str,
    method: str,
    headers: dict[str, str],
    body: bytes,
    messages: list[dict[str, str]],
    sense_kwargs: dict[str, Any],
    chunk_to_text: Callable[[bytes], str] | None = None,
    block_sse_events: Callable[[str], list[bytes]] = _openai_block_sse,
) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
    """Forward a streaming request and apply guardrails.

    Returns ``(status_code, response_headers, body_iterator)``.
    """
    req = client.build_request(
        method,
        upstream_url,
        headers=_forward_headers(headers),
        content=body,
    )
    response = await client.send(req, stream=True)

    resp_headers = dict(response.headers)
    for h in (
        "transfer-encoding",
        "content-length",
        "content-encoding",
    ):
        resp_headers.pop(h, None)

    if stihia_client is None or not messages:
        return (
            response.status_code,
            resp_headers,
            _plain_stream(response),
        )

    guard = SenseGuard(
        stihia_client,
        messages=messages,
        input_sensor="default-input-think",
        output_sensor="default-output",
        output_check_interval=None,  # final-only
        chunk_to_text=chunk_to_text or (lambda c: c.decode("utf-8", errors="replace")),
        raise_on_trigger=False,
        fail_open=True,
        **sense_kwargs,
    )

    return (
        response.status_code,
        resp_headers,
        _guarded_stream(response, guard, block_sse_events=block_sse_events),
    )


# ---------------------------------------------------------------------------
# Non-streaming proxy
# ---------------------------------------------------------------------------


async def proxy_non_streaming(
    *,
    client: httpx.AsyncClient,
    stihia_client: StihiaClient | None,
    upstream_url: str,
    method: str,
    headers: dict[str, str],
    body: bytes,
    messages: list[dict[str, str]],
    sense_kwargs: dict[str, Any],
    block_response: Callable[[str], bytes] = _openai_block_response,
) -> tuple[int, dict[str, str], bytes]:
    """Forward a non-streaming request with parallel sensor checks.

    1. Sends LLM request and input sensor concurrently.
    2. If input triggers → discard LLM response, return error.
    3. Runs output sensor on LLM response body before returning.
    """
    if stihia_client is None or not messages:
        resp = await client.request(
            method,
            upstream_url,
            headers=_forward_headers(headers),
            content=body,
        )
        resp_headers = dict(resp.headers)
        for h in (
            "transfer-encoding",
            "content-length",
            "content-encoding",
        ):
            resp_headers.pop(h, None)
        return resp.status_code, resp_headers, resp.content

    # Run LLM request and input guard in parallel
    async def _llm_request() -> httpx.Response:
        return await client.request(
            method,
            upstream_url,
            headers=_forward_headers(headers),
            content=body,
        )

    async def _input_guard() -> bool:
        """Return True if input triggered (threat detected)."""
        try:
            op = await stihia_client.asense(
                messages=messages,
                sensor="default-input-think",
                **sense_kwargs,
            )
            if op.payload and op.payload.sense_result and op.payload.sense_result.aggregated_signal:
                sev = op.payload.sense_result.aggregated_signal.payload.severity
                return sev in ("high", "critical")
        except StihiaError:
            logger.exception("Stihia input guard error (fail-open)")
        except Exception:
            logger.exception("Unexpected error in input guard (fail-open)")
        return False

    llm_task = asyncio.create_task(_llm_request())
    input_task = asyncio.create_task(_input_guard())

    input_triggered = False
    llm_response: httpx.Response | None = None
    try:
        input_triggered, llm_response = await asyncio.gather(input_task, llm_task)
    except Exception:
        logger.exception("Error during parallel LLM/guard execution")
        # Cancel whichever task is still pending
        for t in (input_task, llm_task):
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t

        # If the LLM task completed successfully, use its result
        if llm_task.done() and not llm_task.cancelled() and llm_task.exception() is None:
            llm_response = llm_task.result()
            input_triggered = False
        else:
            raise

    if llm_response is None:
        raise RuntimeError("LLM response unavailable after parallel execution")

    resp_headers = dict(llm_response.headers)
    for h in (
        "transfer-encoding",
        "content-length",
        "content-encoding",
    ):
        resp_headers.pop(h, None)

    if input_triggered:
        return (
            200,
            {"content-type": "application/json"},
            block_response(_INPUT_BLOCK_MSG),
        )

    # Output guard
    try:
        assistant_text = _extract_assistant_text(llm_response.content)
        output_messages = [*messages, {"role": "assistant", "content": assistant_text}]
        op = await stihia_client.asense(
            messages=output_messages,
            sensor="default-output",
            **sense_kwargs,
        )
        if op.payload and op.payload.sense_result and op.payload.sense_result.aggregated_signal:
            sev = op.payload.sense_result.aggregated_signal.payload.severity
            if sev in ("high", "critical"):
                return (
                    200,
                    {"content-type": "application/json"},
                    block_response(_OUTPUT_BLOCK_MSG),
                )
    except StihiaError:
        logger.exception("Stihia output guard error (fail-open)")
    except Exception:
        logger.exception("Unexpected error in output guard (fail-open)")

    return (
        llm_response.status_code,
        resp_headers,
        llm_response.content,
    )
