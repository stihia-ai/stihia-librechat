"""Tests for provider-specific message adapters."""

import json

from stihia_librechat.adapters import (
    _parse_sse_data,
    anthropic_chunk_text,
    anthropic_messages,
    gemini_chunk_text,
    gemini_messages,
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


# -- Anthropic ---------------------------------------------------------------


class TestAnthropicMessages:
    def test_with_system(self):
        body = {
            "system": "You are a translator.",
            "messages": [{"role": "user", "content": "Hola"}],
        }
        result = anthropic_messages(body)
        assert result == [
            {"role": "system", "content": "You are a translator."},
            {"role": "user", "content": "Hola"},
        ]

    def test_no_system(self):
        body = {"messages": [{"role": "user", "content": "Hi"}]}
        result = anthropic_messages(body)
        assert result == [{"role": "user", "content": "Hi"}]

    def test_content_blocks(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Part A"},
                        {"type": "text", "text": "Part B"},
                    ],
                }
            ]
        }
        result = anthropic_messages(body)
        assert result[0]["content"] == "Part A\nPart B"

    def test_empty_body(self):
        assert anthropic_messages({}) == []

    def test_system_as_list_of_blocks(self):
        body = {
            "system": [
                {"type": "text", "text": "Rule 1."},
                {"type": "text", "text": "Rule 2."},
            ],
            "messages": [{"role": "user", "content": "Go"}],
        }
        result = anthropic_messages(body)
        assert result[0] == {"role": "system", "content": "Rule 1.\nRule 2."}

    def test_tool_use_block(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Searching..."},
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "search",
                            "input": {"query": "test"},
                        },
                    ],
                }
            ]
        }
        result = anthropic_messages(body)
        assert "Searching..." in result[0]["content"]
        assert "[tool_use: search(" in result[0]["content"]

    def test_tool_result_block(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "content": [{"type": "text", "text": "Found 3 results."}],
                        }
                    ],
                }
            ]
        }
        result = anthropic_messages(body)
        assert result[0]["content"] == "Found 3 results."

    def test_tool_result_string_content(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "content": "Plain result text",
                        }
                    ],
                }
            ]
        }
        result = anthropic_messages(body)
        assert result[0]["content"] == "Plain result text"


# -- Gemini ------------------------------------------------------------------


class TestGeminiMessages:
    def test_basic_contents(self):
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "Hello"}]},
                {"role": "model", "parts": [{"text": "Hi there!"}]},
            ]
        }
        result = gemini_messages(body)
        assert result == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

    def test_system_instruction(self):
        body = {
            "systemInstruction": {"parts": [{"text": "Be concise."}]},
            "contents": [{"role": "user", "parts": [{"text": "Sum"}]}],
        }
        result = gemini_messages(body)
        assert result[0] == {"role": "system", "content": "Be concise."}
        assert result[1] == {"role": "user", "content": "Sum"}

    def test_system_instruction_snake_case(self):
        body = {
            "system_instruction": {"parts": [{"text": "Be nice."}]},
            "contents": [],
        }
        result = gemini_messages(body)
        assert result == [{"role": "system", "content": "Be nice."}]

    def test_empty_body(self):
        assert gemini_messages({}) == []

    def test_multiple_parts(self):
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "A"}, {"text": "B"}],
                }
            ]
        }
        result = gemini_messages(body)
        assert len(result) == 2
        assert result[0]["content"] == "A"
        assert result[1]["content"] == "B"

    def test_function_call(self):
        body = {
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "get_weather",
                                "args": {"city": "Sofia"},
                            }
                        }
                    ],
                }
            ]
        }
        result = gemini_messages(body)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "[function_call: get_weather(" in result[0]["content"]
        assert '"city": "Sofia"' in result[0]["content"]

    def test_function_response(self):
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "get_weather",
                                "response": {"temp": 22},
                            }
                        }
                    ],
                }
            ]
        }
        result = gemini_messages(body)
        assert "[function_response: get_weather(" in result[0]["content"]

    def test_mixed_text_and_function_call(self):
        body = {
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {"text": "Let me check."},
                        {
                            "functionCall": {
                                "name": "lookup",
                                "args": {},
                            }
                        },
                    ],
                }
            ]
        }
        result = gemini_messages(body)
        assert len(result) == 2
        assert result[0]["content"] == "Let me check."
        assert "[function_call: lookup(" in result[1]["content"]


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


class TestAnthropicChunkText:
    def test_text_delta(self):
        data = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello"},
        }
        chunk = f"data: {json.dumps(data)}".encode()
        assert anthropic_chunk_text(chunk) == "Hello"

    def test_input_json_delta(self):
        data = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"key":'},
        }
        chunk = f"data: {json.dumps(data)}".encode()
        assert anthropic_chunk_text(chunk) == '{"key":'

    def test_non_content_block_event(self):
        data = {"type": "message_start", "message": {"id": "msg_1"}}
        chunk = f"data: {json.dumps(data)}".encode()
        assert anthropic_chunk_text(chunk) == ""

    def test_message_delta_ignored(self):
        data = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
        chunk = f"data: {json.dumps(data)}".encode()
        assert anthropic_chunk_text(chunk) == ""

    def test_content_block_start_ignored(self):
        data = {"type": "content_block_start", "content_block": {"type": "text"}}
        chunk = f"data: {json.dumps(data)}".encode()
        assert anthropic_chunk_text(chunk) == ""

    def test_done(self):
        assert anthropic_chunk_text(b"data: [DONE]") == ""

    def test_unknown_delta_type(self):
        data = {
            "type": "content_block_delta",
            "delta": {"type": "unknown_type", "data": "x"},
        }
        chunk = f"data: {json.dumps(data)}".encode()
        assert anthropic_chunk_text(chunk) == ""


class TestGeminiChunkText:
    def test_text_part(self):
        data = {"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]}
        chunk = f"data: {json.dumps(data)}".encode()
        assert gemini_chunk_text(chunk) == "Hi"

    def test_multiple_text_parts(self):
        data = {"candidates": [{"content": {"parts": [{"text": "A"}, {"text": "B"}]}}]}
        chunk = f"data: {json.dumps(data)}".encode()
        assert gemini_chunk_text(chunk) == "AB"

    def test_function_call_part(self):
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "get_weather",
                                    "args": {"city": "NYC"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
        chunk = f"data: {json.dumps(data)}".encode()
        result = gemini_chunk_text(chunk)
        assert "[function_call: get_weather(" in result

    def test_no_candidates(self):
        chunk = b'data: {"usageMetadata": {"totalTokenCount": 5}}'
        assert gemini_chunk_text(chunk) == ""

    def test_empty_candidates(self):
        chunk = b'data: {"candidates": []}'
        assert gemini_chunk_text(chunk) == ""

    def test_empty_parts(self):
        data = {"candidates": [{"content": {"parts": []}}]}
        chunk = f"data: {json.dumps(data)}".encode()
        assert gemini_chunk_text(chunk) == ""

    def test_done(self):
        assert gemini_chunk_text(b"data: [DONE]") == ""

    def test_mixed_text_and_function_call(self):
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Checking..."},
                            {"functionCall": {"name": "fn", "args": {}}},
                        ]
                    }
                }
            ]
        }
        chunk = f"data: {json.dumps(data)}".encode()
        result = gemini_chunk_text(chunk)
        assert "Checking..." in result
        assert "[function_call: fn(" in result
