"""Tests for the FastAPI proxy endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from stihia_librechat.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _DummyAsyncClient:
    """Fake HTTP client that refuses real outbound requests."""

    async def request(self, *args, **kwargs):
        raise RuntimeError("Dummy HTTP client — override in individual tests")

    build_request = MagicMock()

    async def send(self, *args, **kwargs):
        raise RuntimeError("Dummy HTTP client — override in individual tests")

    async def aclose(self):
        pass


@pytest.fixture
def client():
    """Test client with mocked startup dependencies."""
    import stihia_librechat.main as mod

    mod._http_client = _DummyAsyncClient()
    mod._stihia_client = None  # guardrails disabled
    mod._settings = mod.Settings(
        STIHIA_API_KEY="",
        STIHIA_PROJECT_KEY="test",
    )
    # Ensure the default hosts are in the allowlist
    mod._allowed_hosts = frozenset(
        h.strip().lower() for h in mod._settings.ALLOWED_UPSTREAM_HOSTS.split(",") if h.strip()
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    mod._http_client = None
    mod._stihia_client = None
    mod._settings = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Missing / invalid upstream
# ---------------------------------------------------------------------------


class TestMissingUpstream:
    """All endpoints return 400 when X-Upstream-Base-URL is absent."""

    def test_openai_missing_upstream(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 400
        assert "X-Upstream-Base-URL" in resp.json()["error"]["message"]


class TestUpstreamAllowlist:
    """Disallowed upstream hosts should be rejected with 403."""

    def test_disallowed_host(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Upstream-Base-URL": "http://evil.example.com"},
        )
        assert resp.status_code == 403
        assert "allowlist" in resp.json()["error"]["message"]

    def test_allowed_host(self, client):
        """Allowed hosts pass the check (will fail later at HTTP layer)."""
        # Mock the HTTP client so it doesn't actually connect
        import httpx

        import stihia_librechat.main as mod

        fake = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

        async def _mock(*a, **kw):
            return fake

        mod._http_client.request = _mock  # type: ignore[assignment]

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200


class TestInvalidJson:
    """Malformed JSON body should return 400, not 500."""

    def test_invalid_json_body(self, client):
        resp = client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={
                "Content-Type": "application/json",
                "X-Upstream-Base-URL": "https://api.openai.com",
            },
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Stihia key extraction
# ---------------------------------------------------------------------------


class TestSenseKwargs:
    """Validate Stihia key extraction from headers and body."""

    def test_extract_from_headers_and_body(self, client):
        from starlette.datastructures import Headers

        from stihia_librechat.main import _extract_sense_kwargs

        class FakeRequest:
            def __init__(self, h):
                self.headers = Headers(h)

        req = FakeRequest(
            {
                "x-user-id": "u-123",
                "x-conversation-id": "conv-abc",
                "x-message-id": "msg-001",
            }
        )
        kwargs = _extract_sense_kwargs(req, process_key="gpt-4o")
        assert kwargs == {
            "user_key": "u-123",
            "process_key": "gpt-4o",
            "thread_key": "conv-abc",
            "run_key": "msg-001",
        }

    def test_fallback_to_unknown(self, client):
        from starlette.datastructures import Headers

        from stihia_librechat.main import _extract_sense_kwargs

        class FakeRequest:
            def __init__(self):
                self.headers = Headers({})

        kwargs = _extract_sense_kwargs(FakeRequest())
        assert kwargs == {
            "user_key": "unknown",
            "process_key": "unknown",
            "thread_key": "unknown",
            "run_key": "unknown",
        }

    def test_agent_uuid_as_process_key(self, client):
        from starlette.datastructures import Headers

        from stihia_librechat.main import _extract_sense_kwargs

        class FakeRequest:
            def __init__(self, h):
                self.headers = Headers(h)

        req = FakeRequest({"x-user-id": "u-456"})
        kwargs = _extract_sense_kwargs(
            req,
            process_key="550e8400-e29b-41d4-a716-446655440000",
        )
        assert kwargs["process_key"] == "550e8400-e29b-41d4-a716-446655440000"
        assert kwargs["user_key"] == "u-456"


# ---------------------------------------------------------------------------
# Non-streaming proxy (no guardrails)
# ---------------------------------------------------------------------------


class TestNonStreamingProxy:
    """Non-streaming forwarding without guardrails."""

    def test_forwards_to_upstream(self, client):
        """Without guardrails, the proxy forwards requests as-is."""
        import httpx

        import stihia_librechat.main as mod

        fake_response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello!"}}]},
        )

        async def mock_request(*args, **kwargs):
            return fake_response

        mod._http_client.request = mock_request  # type: ignore[assignment]

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello!"


# ---------------------------------------------------------------------------
# Guardrail-enabled paths
# ---------------------------------------------------------------------------


def _make_sense_operation(severity: str = "low"):
    """Build a minimal mock SenseOperation."""
    payload = MagicMock()
    payload.severity = severity
    agg = MagicMock()
    agg.payload = payload
    result = MagicMock()
    result.aggregated_signal = agg
    op_payload = MagicMock()
    op_payload.sense_result = result
    op = MagicMock()
    op.payload = op_payload
    return op


class TestGuardrailInputBlock:
    """Input guardrail triggers → 200 with OpenAI-format block response."""

    def test_input_triggered_returns_block_response(self, client):
        import httpx

        import stihia_librechat.main as mod

        # Mock Stihia client
        mock_stihia = AsyncMock()
        mock_stihia.asense = AsyncMock(return_value=_make_sense_operation("high"))
        mod._stihia_client = mock_stihia

        # Mock LLM response
        fake_llm = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "I will help"}}]},
        )

        async def mock_request(*a, **kw):
            return fake_llm

        mod._http_client.request = mock_request  # type: ignore[assignment]

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "bad input"}],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert (
            "blocked" in data["choices"][0]["message"]["content"].lower()
            or "guardrail" in data["choices"][0]["message"]["content"].lower()
        )
        assert mock_stihia.asense.await_args.kwargs["sensor"] == "default-input-think"
        mod._stihia_client = None


class TestGuardrailOutputBlock:
    """Output guardrail triggers → 200 with OpenAI-format block response."""

    def test_output_triggered_returns_block_response(self, client):
        import httpx

        import stihia_librechat.main as mod

        # First asense call (input) returns low, second (output) returns high
        input_op = _make_sense_operation("low")
        output_op = _make_sense_operation("high")

        mock_stihia = AsyncMock()
        mock_stihia.asense = AsyncMock(side_effect=[input_op, output_op])
        mod._stihia_client = mock_stihia

        fake_llm = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "bad output"}}]},
        )

        async def mock_request(*a, **kw):
            return fake_llm

        mod._http_client.request = mock_request  # type: ignore[assignment]

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "normal"}],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert (
            "blocked" in data["choices"][0]["message"]["content"].lower()
            or "guardrail" in data["choices"][0]["message"]["content"].lower()
        )
        assert mock_stihia.asense.await_args_list[0].kwargs["sensor"] == "default-input-think"
        assert mock_stihia.asense.await_args_list[1].kwargs["sensor"] == "default-output"
        mod._stihia_client = None


class TestGuardrailSensorConfiguration:
    """Custom Stihia sensor names should be read from settings."""

    def test_custom_sensor_names_are_used(self, client):
        import httpx

        import stihia_librechat.main as mod

        mock_stihia = AsyncMock()
        mock_stihia.asense = AsyncMock(side_effect=[_make_sense_operation("low"), _make_sense_operation("low")])
        mod._stihia_client = mock_stihia

        fake_llm = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "safe output"}}]},
        )

        async def mock_request(*a, **kw):
            return fake_llm

        mod._http_client.request = mock_request  # type: ignore[assignment]
        mod._settings = mod.Settings(
            STIHIA_API_KEY="test",
            STIHIA_PROJECT_KEY="test",
            STIHIA_INPUT_SENSOR="org-input-policy",
            STIHIA_OUTPUT_SENSOR="org-output-policy",
        )

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200
        assert mock_stihia.asense.await_args_list[0].kwargs["sensor"] == "org-input-policy"
        assert mock_stihia.asense.await_args_list[1].kwargs["sensor"] == "org-output-policy"

        mod._stihia_client = None
        mod._settings = None


class TestGuardrailFailOpen:
    """Stihia API errors should not block the LLM response."""

    def test_stihia_error_passes_through(self, client):
        import httpx

        import stihia_librechat.main as mod
        from stihia.exceptions import StihiaError

        mock_stihia = AsyncMock()
        mock_stihia.asense = AsyncMock(side_effect=StihiaError("API unreachable"))
        mod._stihia_client = mock_stihia

        fake_llm = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello!"}}]},
        )

        async def mock_request(*a, **kw):
            return fake_llm

        mod._http_client.request = mock_request  # type: ignore[assignment]

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        # Fail-open: LLM response goes through despite guard error
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Hello!"
        mod._stihia_client = None


# ---------------------------------------------------------------------------
# STIHIA_SEND_FULL_HISTORY toggle
# ---------------------------------------------------------------------------


class TestSendFullHistory:
    """STIHIA_SEND_FULL_HISTORY controls whether the full message history is sent."""

    def test_default_sends_filtered_messages(self, client):
        """When false: only system + latest message are sent to Stihia."""
        import httpx

        import stihia_librechat.main as mod

        mock_stihia = AsyncMock()
        mock_stihia.asense = AsyncMock(return_value=_make_sense_operation("low"))
        mod._stihia_client = mock_stihia

        fake_llm = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

        async def mock_request(*a, **kw):
            return fake_llm

        mod._http_client.request = mock_request  # type: ignore[assignment]
        mod._settings = mod.Settings(
            STIHIA_API_KEY="test",
            STIHIA_PROJECT_KEY="test",
            STIHIA_SEND_FULL_HISTORY=False,
        )

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": "Be helpful."},
                    {"role": "user", "content": "First"},
                    {"role": "assistant", "content": "Reply"},
                    {"role": "user", "content": "Second"},
                ],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200

        # Input guard receives filtered messages (system + latest only)
        input_call = mock_stihia.asense.call_args_list[0]
        sent_messages = input_call.kwargs["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[1]["content"] == "Second"

        mod._stihia_client = None
        mod._settings = None

    def test_full_history_sends_all_messages(self, client):
        """STIHIA_SEND_FULL_HISTORY=true: full conversation sent to Stihia."""
        import httpx

        import stihia_librechat.main as mod

        mock_stihia = AsyncMock()
        mock_stihia.asense = AsyncMock(return_value=_make_sense_operation("low"))
        mod._stihia_client = mock_stihia

        fake_llm = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

        async def mock_request(*a, **kw):
            return fake_llm

        mod._http_client.request = mock_request  # type: ignore[assignment]
        mod._settings = mod.Settings(
            STIHIA_API_KEY="test",
            STIHIA_PROJECT_KEY="test",
            STIHIA_SEND_FULL_HISTORY=True,
        )

        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": "Be helpful."},
                    {"role": "user", "content": "First"},
                    {"role": "assistant", "content": "Reply"},
                    {"role": "user", "content": "Second"},
                ],
                "stream": False,
            },
            headers={"X-Upstream-Base-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 200

        # Input guard receives all 4 messages
        input_call = mock_stihia.asense.call_args_list[0]
        sent_messages = input_call.kwargs["messages"]
        assert len(sent_messages) == 4
        assert sent_messages[0] == {"role": "system", "content": "Be helpful."}
        assert sent_messages[1] == {"role": "user", "content": "First"}
        assert sent_messages[2] == {"role": "assistant", "content": "Reply"}
        assert sent_messages[3] == {"role": "user", "content": "Second"}

        mod._stihia_client = None
        mod._settings = None


# ---------------------------------------------------------------------------
# Title request detection
# ---------------------------------------------------------------------------


class TestIsTitleRequest:
    """Detect LibreChat title generation requests via known prompt fingerprints."""

    # -- True positives: known LibreChat title prompts -----------------------

    def test_structured_method_default(self):
        """Default titleMethod='structured' from @librechat/agents."""
        from stihia_librechat.main import _is_title_request

        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {
                "role": "user",
                "content": (
                    "Analyze this conversation and provide:\n"
                    "1. The detected language of the conversation\n"
                    "2. A concise title in the detected language "
                    "(5 words or less, no punctuation or quotation)\n\n"
                    "User: Hello, how are you?\nAssistant: I'm doing well!"
                ),
            },
        ]
        assert _is_title_request(messages) is True

    def test_completion_method(self):
        """titleMethod='completion' from @librechat/agents."""
        from stihia_librechat.main import _is_title_request

        messages = [
            {
                "role": "user",
                "content": (
                    "Provide a concise, 5-word-or-less title for the conversation, "
                    "using title case conventions. Only return the title itself.\n\n"
                    "Conversation:\nUser: What is Python?\nAssistant: It's a language."
                ),
            },
        ]
        assert _is_title_request(messages) is True

    def test_completion_method_without_comma(self):
        """Comma after 'concise' is optional in some LibreChat versions."""
        from stihia_librechat.main import _is_title_request

        messages = [
            {
                "role": "user",
                "content": (
                    "Provide a concise 5-word-or-less title for the conversation, using title case conventions."
                ),
            },
        ]
        assert _is_title_request(messages) is True

    def test_assistants_method(self):
        """Assistants endpoint hardcoded prompt (Azure/OpenAI assistants)."""
        from stihia_librechat.main import _is_title_request

        messages = [
            {
                "role": "user",
                "content": (
                    "Please generate a concise title (max 40 characters) "
                    "for a conversation that starts with:\n"
                    "User: Tell me about dogs\n"
                    "Assistant: Dogs are great companions!\n\n"
                    "Title:"
                ),
            },
        ]
        assert _is_title_request(messages) is True

    # -- True negatives: normal user messages --------------------------------

    def test_normal_conversation_not_detected(self):
        from stihia_librechat.main import _is_title_request

        messages = [
            {"role": "user", "content": "What is the title of the book 1984?"},
        ]
        assert _is_title_request(messages) is False

    def test_user_asking_about_titles_not_detected(self):
        from stihia_librechat.main import _is_title_request

        messages = [
            {"role": "user", "content": "Can you suggest a title for my blog post about cooking?"},
        ]
        assert _is_title_request(messages) is False

    def test_generate_title_generic_not_detected(self):
        from stihia_librechat.main import _is_title_request

        messages = [
            {"role": "user", "content": "Generate a title for my essay about climate change."},
        ]
        assert _is_title_request(messages) is False

    def test_create_title_with_word_limit_not_detected(self):
        """Generic 'create a title in max N words' should NOT match."""
        from stihia_librechat.main import _is_title_request

        messages = [
            {"role": "user", "content": "Create a title in max 6 words for my presentation."},
        ]
        assert _is_title_request(messages) is False

    def test_write_title_with_char_limit_not_detected(self):
        """Generic 'write a title (maximum 50 characters)' should NOT match."""
        from stihia_librechat.main import _is_title_request

        messages = [
            {
                "role": "user",
                "content": "Write a title (maximum 50 characters) summarizing this chat.",
            },
        ]
        assert _is_title_request(messages) is False

    def test_empty_messages(self):
        from stihia_librechat.main import _is_title_request

        assert _is_title_request([]) is False

    def test_no_content(self):
        from stihia_librechat.main import _is_title_request

        assert _is_title_request([{"role": "user", "content": ""}]) is False


# ---------------------------------------------------------------------------
# Thread key segregation for meta requests
# ---------------------------------------------------------------------------


class TestThreadKeySegregation:
    """_extract_sense_kwargs segregates thread_key for title requests."""

    def test_title_request_gets_meta_thread_key(self):
        from starlette.datastructures import Headers

        from stihia_librechat.main import _extract_sense_kwargs

        class FakeRequest:
            def __init__(self, h):
                self.headers = Headers(h)

        req = FakeRequest(
            {
                "x-user-id": "u-1",
                "x-conversation-id": "conv-42",
                "x-message-id": "msg-7",
            }
        )
        messages = [
            {"role": "user", "content": "Hi"},
            {
                "role": "user",
                "content": (
                    "Please generate a concise title (max 40 characters) "
                    "for a conversation that starts with:\n"
                    "User: Hi\nAssistant: Hello!\n\nTitle:"
                ),
            },
        ]
        kwargs = _extract_sense_kwargs(req, process_key="gpt-4o", messages=messages)
        assert kwargs["thread_key"] == "conv-42:meta:title"
        assert kwargs["user_key"] == "u-1"
        assert kwargs["process_key"] == "gpt-4o"
        assert kwargs["run_key"] == "msg-7"

    def test_normal_request_keeps_original_thread_key(self):
        from starlette.datastructures import Headers

        from stihia_librechat.main import _extract_sense_kwargs

        class FakeRequest:
            def __init__(self, h):
                self.headers = Headers(h)

        req = FakeRequest({"x-conversation-id": "conv-42"})
        messages = [{"role": "user", "content": "What is Python?"}]
        kwargs = _extract_sense_kwargs(req, process_key="gpt-4o", messages=messages)
        assert kwargs["thread_key"] == "conv-42"

    def test_no_messages_keeps_original_thread_key(self):
        from starlette.datastructures import Headers

        from stihia_librechat.main import _extract_sense_kwargs

        class FakeRequest:
            def __init__(self, h):
                self.headers = Headers(h)

        req = FakeRequest({"x-conversation-id": "conv-42"})
        kwargs = _extract_sense_kwargs(req, process_key="gpt-4o")
        assert kwargs["thread_key"] == "conv-42"
