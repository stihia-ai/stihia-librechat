"""Provider-specific message adapters.

Each adapter extracts ``messages`` from a provider's native request body and
normalises them into the ``list[dict[str, str]]`` format expected by the
Stihia SDK (``{"role": ..., "content": ...}``).

Also provides SSE (Server-Sent Events) chunk-to-text extractors for streaming output guardrails.
"""

from __future__ import annotations

import json
from typing import Any


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
                elif block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    parts.append(f"[tool_use: {name}({json.dumps(inp)})]")
                elif block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    parts.append(_text_content(result_content))
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


# -- Anthropic -------------------------------------------------------------


def anthropic_messages(body: dict[str, Any]) -> list[dict[str, str]]:
    """Extract messages from an Anthropic ``/v1/messages`` request."""
    out: list[dict[str, str]] = []

    # Anthropic sends the system prompt as a top-level ``system`` field.
    system = body.get("system")
    if system:
        text = _text_content(system)
        if text:
            out.append({"role": "system", "content": text})

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = _text_content(msg.get("content", ""))
        if content:
            out.append({"role": role, "content": content})
    return out


# -- Google Gemini ---------------------------------------------------------


def gemini_messages(body: dict[str, Any]) -> list[dict[str, str]]:
    """Extract messages from a Google Gemini ``generateContent`` request."""
    out: list[dict[str, str]] = []

    # System instruction
    sys_inst = body.get("systemInstruction") or body.get("system_instruction")
    if isinstance(sys_inst, dict):
        for part in sys_inst.get("parts", []):
            text = part.get("text", "")
            if text:
                out.append({"role": "system", "content": text})

    for content_block in body.get("contents", []):
        role = content_block.get("role", "user")
        # Gemini uses "model" for the assistant role.
        if role == "model":
            role = "assistant"
        for part in content_block.get("parts", []):
            text = part.get("text", "")
            if text:
                out.append({"role": role, "content": text})
                continue
            fc = part.get("functionCall")
            if isinstance(fc, dict):
                name = fc.get("name", "")
                args = fc.get("args", {})
                out.append(
                    {
                        "role": role,
                        "content": f"[function_call: {name}({json.dumps(args)})]",
                    }
                )
                continue
            fr = part.get("functionResponse")
            if isinstance(fr, dict):
                name = fr.get("name", "")
                resp = fr.get("response", {})
                out.append(
                    {
                        "role": role,
                        "content": f"[function_response: {name}({json.dumps(resp)})]",
                    }
                )
    return out


# ---------------------------------------------------------------------------
# SSE chunk-to-text extractors (for streaming output guardrails)
# ---------------------------------------------------------------------------


def _parse_sse_data(raw: bytes) -> dict | None:
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
        return result
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


def anthropic_chunk_text(chunk: bytes) -> str:
    """Extract content text from an Anthropic SSE stream chunk.

    Stream events::

        event: content_block_delta
        data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}

        event: content_block_delta
        data: {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "..."}}
    """
    data = _parse_sse_data(chunk)
    if data is None:
        return ""
    if data.get("type") != "content_block_delta":
        return ""
    delta = data.get("delta", {})
    delta_type = delta.get("type", "")
    if delta_type == "text_delta":
        return str(delta.get("text", ""))
    if delta_type == "input_json_delta":
        return str(delta.get("partial_json", ""))
    return ""


def gemini_chunk_text(chunk: bytes) -> str:
    """Extract content text from a Gemini SSE stream chunk.

    Stream format (JSON array elements or individual objects)::

        data: {"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]}

    Also handles ``functionCall`` parts.
    """
    data = _parse_sse_data(chunk)
    if data is None:
        return ""
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    parts_list = candidates[0].get("content", {}).get("parts", [])
    texts: list[str] = []
    for part in parts_list:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            texts.append(text)
        fc = part.get("functionCall")
        if isinstance(fc, dict):
            name = fc.get("name", "")
            args = fc.get("args", {})
            texts.append(f"[function_call: {name}({json.dumps(args)})]")
    return "".join(texts)
