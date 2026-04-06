"""OpenAI message adapter.

Extracts ``messages`` from an OpenAI request body and normalises them into
the ``list[dict[str, str]]`` format expected by the Stihia SDK
(``{"role": ..., "content": ...}``).

Also provides an SSE (Server-Sent Events) chunk-to-text extractor for streaming output guardrails.
"""

from __future__ import annotations

import json
from typing import Any, cast


def _text_content(content: Any) -> str:
    """Extract plain text from content that may be a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif "text" in block:
                    parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content)


def _tool_calls_text(tool_calls: list[dict[str, Any]]) -> str:
    """Serialise OpenAI tool_calls into a text representation."""
    parts: list[str] = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", "")
        parts.append(f"[tool_call: {name}({args})]")
    return "\n".join(parts)


# -- OpenAI ----------------------------------------------------------------


def latest_with_system(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return only the system prompt(s) and the latest non-system message.

    Used to send minimal context to the Stihia API instead of the full
    chat history.  The upstream LLM still receives the complete payload.
    """
    if not messages:
        return []
    system = [m for m in messages if m["role"] == "system"]
    for m in reversed(messages):
        if m["role"] != "system":
            return [*system, m]
    return system


def openai_messages(body: dict[str, Any]) -> list[dict[str, str]]:
    """Extract messages from an OpenAI ``/v1/chat/completions`` request."""
    out: list[dict[str, str]] = []
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        if role == "developer":
            role = "system"

        parts: list[str] = []

        content = _text_content(msg.get("content", ""))
        if content:
            parts.append(content)

        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            parts.append(_tool_calls_text(tool_calls))

        if parts:
            out.append({"role": role, "content": "\n".join(parts)})
    return out


# ---------------------------------------------------------------------------
# SSE chunk-to-text extractors (for streaming output guardrails)
# ---------------------------------------------------------------------------


def _parse_sse_data(raw: bytes) -> dict[str, Any] | None:
    """Parse a single SSE line into JSON, or return None.

    Expects lines like ``data: {"choices": ...}`` or ``data: [DONE]``.
    """
    line = raw.decode("utf-8", errors="replace").strip()
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        result = json.loads(payload)
        if not isinstance(result, dict):
            return None
        return cast("dict[str, Any]", result)
    except (json.JSONDecodeError, ValueError):
        return None


def openai_chunk_text(chunk: bytes) -> str:
    """Extract content text from an OpenAI SSE stream chunk.

    Stream format::

        data: {"choices": [{"delta": {"content": "Hi"}}]}

    Also handles ``tool_calls`` deltas.
    """
    data = _parse_sse_data(chunk)
    if data is None:
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    delta = choices[0].get("delta", {})
    parts: list[str] = []
    content = delta.get("content")
    if isinstance(content, str):
        parts.append(content)
    tool_calls = delta.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", "")
            if name:
                parts.append(f"[tool_call: {name}")
            if args:
                parts.append(args)
    return "".join(parts)
