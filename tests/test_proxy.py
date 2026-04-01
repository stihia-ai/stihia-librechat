"""Tests for proxy module helpers."""

import json

import pytest

from stihia_librechat.proxy import (
    _INPUT_BLOCK_MSG,
    _OUTPUT_BLOCK_MSG,
    _build_upstream_url,
    _extract_assistant_text,
    _forward_headers,
    _guarded_stream,
    _openai_block_response,
    _openai_block_sse,
)


class TestForwardHeaders:
    def test_strips_hop_by_hop(self):
        headers = {
            "authorization": "Bearer sk-...",
            "content-type": "application/json",
            "host": "localhost",
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "x-upstream-base-url": "https://api.openai.com",
        }
        result = _forward_headers(headers)
        assert "authorization" in result
        assert "content-type" in result
        assert "host" not in result
        assert "connection" not in result
        assert "transfer-encoding" not in result
        assert "x-upstream-base-url" not in result

    def test_strips_librechat_metadata_headers(self):
        headers = {
            "authorization": "Bearer sk-...",
            "x-user-id": "u-123",
            "x-conversation-id": "conv-abc",
            "x-message-id": "msg-001",
            "x-process-key": "gpt-4o",
        }
        result = _forward_headers(headers)
        assert "authorization" in result
        assert "x-user-id" not in result
        assert "x-conversation-id" not in result
        assert "x-message-id" not in result
        assert "x-process-key" not in result

    def test_strips_trailer_singular(self):
        headers = {"trailer": "Expires", "trailers": "x"}
        result = _forward_headers(headers)
        assert "trailer" not in result
        assert "trailers" not in result

    def test_preserves_custom_headers(self):
        headers = {
            "x-api-key": "sk-ant-...",
            "anthropic-version": "2024-01-01",
        }
        result = _forward_headers(headers)
        assert result == headers


class TestBuildUpstreamUrl:
    def test_basic(self):
        assert (
            _build_upstream_url(
                "https://api.openai.com",
                "/v1/chat/completions",
            )
            == "https://api.openai.com/v1/chat/completions"
        )

    def test_strips_trailing_slash(self):
        assert (
            _build_upstream_url(
                "https://api.openai.com/",
                "/v1/messages",
            )
            == "https://api.openai.com/v1/messages"
        )


class TestExtractAssistantText:
    def test_openai_response(self):
        body = json.dumps({"choices": [{"message": {"content": "Hello there!"}}]}).encode()
        assert _extract_assistant_text(body) == "Hello there!"

    def test_anthropic_response(self):
        body = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "Part A"},
                    {"type": "text", "text": "Part B"},
                ]
            }
        ).encode()
        assert _extract_assistant_text(body) == "Part A\nPart B"

    def test_gemini_response(self):
        body = json.dumps({"candidates": [{"content": {"parts": [{"text": "Gemini says hi"}]}}]}).encode()
        assert _extract_assistant_text(body) == "Gemini says hi"

    def test_invalid_json_returns_raw(self):
        assert _extract_assistant_text(b"not json") == "not json"

    def test_unknown_shape_returns_raw(self):
        body = json.dumps({"foo": "bar"}).encode()
        result = _extract_assistant_text(body)
        assert "foo" in result

    def test_openai_with_tool_calls(self):
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Let me check.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search",
                                        "arguments": '{"q": "test"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ).encode()
        result = _extract_assistant_text(body)
        assert "Let me check." in result
        assert '[tool_call: search({"q": "test"})]' in result

    def test_openai_tool_calls_only(self):
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "get_time",
                                        "arguments": "{}",
                                    }
                                }
                            ],
                        }
                    }
                ]
            }
        ).encode()
        result = _extract_assistant_text(body)
        assert "[tool_call: get_time({})]" in result

    def test_anthropic_with_tool_use(self):
        body = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "Searching..."},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "web_search",
                        "input": {"query": "weather"},
                    },
                ]
            }
        ).encode()
        result = _extract_assistant_text(body)
        assert "Searching..." in result
        assert "[tool_use: web_search(" in result

    def test_gemini_with_function_call(self):
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Checking"},
                                {
                                    "functionCall": {
                                        "name": "get_info",
                                        "args": {"id": 1},
                                    }
                                },
                            ]
                        }
                    }
                ]
            }
        ).encode()
        result = _extract_assistant_text(body)
        assert "Checking" in result
        assert "[function_call: get_info(" in result


class TestOpenaiBlockResponse:
    def test_has_choices_with_role_and_content(self):
        body = _openai_block_response("blocked")
        data = json.loads(body)
        msg = data["choices"][0]["message"]
        assert msg["role"] == "assistant"
        assert msg["content"] == "blocked"
        assert data["choices"][0]["finish_reason"] == "stop"

    def test_input_block_message(self):
        body = _openai_block_response(_INPUT_BLOCK_MSG)
        data = json.loads(body)
        assert _INPUT_BLOCK_MSG in data["choices"][0]["message"]["content"]

    def test_output_block_message(self):
        body = _openai_block_response(_OUTPUT_BLOCK_MSG)
        data = json.loads(body)
        assert _OUTPUT_BLOCK_MSG in data["choices"][0]["message"]["content"]


class TestOpenaiBlockSse:
    def test_produces_four_events(self):
        events = _openai_block_sse("blocked")
        assert len(events) == 4

    def test_role_chunk_has_assistant_role(self):
        events = _openai_block_sse("blocked")
        role_data = json.loads(events[0].decode().removeprefix("data: ").strip())
        delta = role_data["choices"][0]["delta"]
        assert delta["role"] == "assistant"

    def test_content_chunk_has_message(self):
        events = _openai_block_sse("test msg")
        content_data = json.loads(events[1].decode().removeprefix("data: ").strip())
        assert content_data["choices"][0]["delta"]["content"] == "test msg"

    def test_finish_chunk_has_stop(self):
        events = _openai_block_sse("blocked")
        finish_data = json.loads(events[2].decode().removeprefix("data: ").strip())
        assert finish_data["choices"][0]["finish_reason"] == "stop"

    def test_last_event_is_done(self):
        events = _openai_block_sse("blocked")
        assert events[3] == b"data: [DONE]\n\n"


class TestGuardedStreamBlocked:
    @pytest.mark.asyncio
    async def test_emits_sse_on_input_trigger(self):
        class FakeResponse:
            async def aclose(self):
                pass

        class FakeGuard:
            input_triggered = True
            output_triggered = False

            async def shield(self, stream):
                return
                yield

        chunks = []
        async for chunk in _guarded_stream(FakeResponse(), FakeGuard()):
            chunks.append(chunk)

        assert len(chunks) == 4
        role_data = json.loads(chunks[0].decode().removeprefix("data: ").strip())
        assert role_data["choices"][0]["delta"]["role"] == "assistant"
        assert chunks[3] == b"data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_emits_sse_on_output_trigger(self):
        class FakeResponse:
            async def aclose(self):
                pass

        class FakeGuard:
            input_triggered = False
            output_triggered = True

            async def shield(self, stream):
                return
                yield

        chunks = []
        async for chunk in _guarded_stream(FakeResponse(), FakeGuard()):
            chunks.append(chunk)

        assert len(chunks) == 4
        content_data = json.loads(chunks[1].decode().removeprefix("data: ").strip())
        assert _OUTPUT_BLOCK_MSG in content_data["choices"][0]["delta"]["content"]

    @pytest.mark.asyncio
    async def test_passes_through_when_no_trigger(self):
        class FakeResponse:
            async def aclose(self):
                pass

        class FakeGuard:
            input_triggered = False
            output_triggered = False

            async def shield(self, stream):
                yield b"data: chunk1\n\n"
                yield b"data: chunk2\n\n"

        chunks = []
        async for chunk in _guarded_stream(FakeResponse(), FakeGuard()):
            chunks.append(chunk)

        assert chunks == [b"data: chunk1\n\n", b"data: chunk2\n\n"]
