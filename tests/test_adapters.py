"""Tests for provider-specific message adapters."""

import json

from stihia_librechat.adapters import (
    _parse_sse_data,
    openai_chunk_text,
    openai_messages,
)

# -- OpenAI ------------------------------------------------------------------


class TestOpenAIMessages:
    def test_basic_messages(self):
        body = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ]
        }
        result = openai_messages(body)
        assert result == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

    def test_empty_body(self):
        assert openai_messages({}) == []

    def test_multimodal_content_blocks(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {"type": "image_url", "image_url": {"url": "http://..."}},
                    ],
                }
            ]
        }
        result = openai_messages(body)
        assert len(result) == 1
        assert result[0]["content"] == "What's in this image?"

    def test_skips_empty_content(self):
        body = {"messages": [{"role": "user", "content": ""}]}
        assert openai_messages(body) == []

    def test_developer_role_mapped_to_system(self):
        body = {
            "messages": [
                {"role": "developer", "content": "Be concise."},
                {"role": "user", "content": "Hi"},
            ]
        }
        result = openai_messages(body)
        assert result[0] == {"role": "system", "content": "Be concise."}

    def test_tool_calls(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Let me search.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"q": "weather"}',
                            },
                        }
                    ],
                }
            ]
        }
        result = openai_messages(body)
        assert len(result) == 1
        assert "Let me search." in result[0]["content"]
        assert '[tool_call: search({"q": "weather"})]' in result[0]["content"]

    def test_tool_calls_only_no_text(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_time",
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            ]
        }
        result = openai_messages(body)
        assert len(result) == 1
        assert "[tool_call: get_time({})]" in result[0]["content"]

    def test_multiple_tool_calls(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": "fn_a", "arguments": "{}"}},
                        {"function": {"name": "fn_b", "arguments": '{"x":1}'}},
                    ],
                }
            ]
        }
        result = openai_messages(body)
        assert "[tool_call: fn_a({})]" in result[0]["content"]
        assert '[tool_call: fn_b({"x":1})]' in result[0]["content"]


# ============================================================================
# SSE chunk-to-text extractors
# ============================================================================


class TestParseSSEData:
    def test_valid_sse_line(self):
        data = _parse_sse_data(b'data: {"key": "value"}')
        assert data == {"key": "value"}

    def test_done_returns_none(self):
        assert _parse_sse_data(b"data: [DONE]") is None

    def test_empty_data(self):
        assert _parse_sse_data(b"data: ") is None
        assert _parse_sse_data(b"data:") is None

    def test_non_data_line(self):
        assert _parse_sse_data(b"event: message") is None
        assert _parse_sse_data(b": comment") is None
        assert _parse_sse_data(b"") is None

    def test_invalid_json(self):
        assert _parse_sse_data(b"data: {not json}") is None

    def test_whitespace_around_data(self):
        data = _parse_sse_data(b'  data:  {"ok": true}  ')
        assert data == {"ok": True}

    def test_data_with_extra_whitespace_after_colon(self):
        data = _parse_sse_data(b'data:   {"ok": true}')
        assert data == {"ok": True}

    def test_non_object_json_returns_none(self):
        assert _parse_sse_data(b"data: [1, 2, 3]") is None
        assert _parse_sse_data(b'data: "text"') is None


class TestOpenAIChunkText:
    def test_content_delta(self):
        chunk = b'data: {"choices": [{"delta": {"content": "Hello"}}]}'
        assert openai_chunk_text(chunk) == "Hello"

    def test_empty_delta(self):
        chunk = b'data: {"choices": [{"delta": {}}]}'
        assert openai_chunk_text(chunk) == ""

    def test_role_delta_no_content(self):
        chunk = b'data: {"choices": [{"delta": {"role": "assistant"}}]}'
        assert openai_chunk_text(chunk) == ""

    def test_done(self):
        assert openai_chunk_text(b"data: [DONE]") == ""

    def test_non_sse_line(self):
        assert openai_chunk_text(b"") == ""

    def test_tool_calls_delta_name(self):
        data = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "search", "arguments": ""}}]}}]}
        chunk = f"data: {json.dumps(data)}".encode()
        result = openai_chunk_text(chunk)
        assert "[tool_call: search" in result

    def test_tool_calls_delta_arguments(self):
        data = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "", "arguments": '{"q":'}}]}}]}
        chunk = f"data: {json.dumps(data)}".encode()
        result = openai_chunk_text(chunk)
        assert '{"q":' in result

    def test_content_plus_tool_calls(self):
        data = {
            "choices": [
                {
                    "delta": {
                        "content": "Searching",
                        "tool_calls": [{"function": {"name": "fn", "arguments": ""}}],
                    }
                }
            ]
        }
        chunk = f"data: {json.dumps(data)}".encode()
        result = openai_chunk_text(chunk)
        assert "Searching" in result
        assert "[tool_call: fn" in result

    def test_no_choices(self):
        chunk = b'data: {"id": "chatcmpl-1"}'
        assert openai_chunk_text(chunk) == ""

    def test_empty_choices(self):
        chunk = b'data: {"choices": []}'
        assert openai_chunk_text(chunk) == ""
