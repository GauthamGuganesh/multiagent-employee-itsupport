"""Deployment wiring checks that never contact external production services."""
import pytest

from app.api import dispatcher
from app.db import repos
from app.api.routes_voice import (
    ElevenLabsExtraBody,
    OpenAICompletionRequest,
    OpenAIMessage,
    create_bridge_token,
    custom_llm_completion,
)
from app.config import Settings
from app.main import create_app


def test_render_environment_aliases_and_postgres_normalization():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://user:password@example.com:5432/support",
        NEO4J_URI="neo4j+s://example.databases.neo4j.io",
        NEO4J_USERNAME="neo4j",
        NEO4J_PASSWORD="secret",
        APP_ENV="production",
        CORS_ORIGINS="https://app.example.com,https://preview.example.com",
    )

    assert settings.postgres_dsn == "postgresql+asyncpg://user:password@example.com:5432/support"
    assert settings.neo4j_user == "neo4j"
    assert settings.is_production is True
    assert settings.cors_origins == ["https://app.example.com", "https://preview.example.com"]


def test_render_comma_separated_cors_environment_value(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://preview.example.com")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://app.example.com", "https://preview.example.com"]


def test_render_health_and_voice_token_routes_are_registered():
    paths = set(create_app().openapi()["paths"])

    assert "/health" in paths
    assert "/api/voice/token" in paths


@pytest.mark.asyncio
async def test_custom_llm_adapter_uses_only_newest_message_and_streams_done(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    async def start(employee_id: str, message: str, channel: str, **_kwargs):
        calls.append(("start", employee_id, message))
        assert channel == "voice"
        return {
            "session_id": "session-from-dispatcher",
            "pending": None,
            "assistant_message": "I have opened your support request.",
        }

    monkeypatch.setattr(dispatcher, "start_session", start)

    async def no_existing_session(*_args):
        return None

    monkeypatch.setattr(repos, "find_active_voice_session", no_existing_session)
    response = await custom_llm_completion(
        OpenAICompletionRequest(
            stream=True,
            voice_bridge_token=create_bridge_token("EMP-032"),
            messages=[
                OpenAIMessage(role="system", content="provider prompt"),
                OpenAIMessage(role="user", content="old replayed message"),
                OpenAIMessage(role="assistant", content="old assistant reply"),
                OpenAIMessage(role="user", content="my newest spoken request"),
            ],
        )
    )
    body = "".join([chunk async for chunk in response.body_iterator])

    assert response.media_type == "text/event-stream"
    assert response.headers["X-GA-VoiceAI-Session-Id"] == "session-from-dispatcher"
    assert calls == [("start", "EMP-032", "my newest spoken request")]
    assert "I have opened your support request." in body
    assert "data: [DONE]" in body


@pytest.mark.asyncio
async def test_custom_llm_adapter_resumes_explicit_support_session(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    async def resume(session_id: str, employee_id: str, message: str, channel: str):
        calls.append((session_id, employee_id, message))
        assert channel == "voice"
        return {
            "session_id": session_id,
            "pending": {"type": "question", "question": "What error do you see?"},
            "assistant_message": "What error do you see?",
        }

    monkeypatch.setattr(dispatcher, "continue_session", resume)
    response = await custom_llm_completion(
        OpenAICompletionRequest(
            stream=False,
            messages=[OpenAIMessage(role="user", content="It disconnects after a minute.")],
            elevenlabs_extra_body=ElevenLabsExtraBody(
                voice_bridge_token=create_bridge_token("EMP-014"), session_id="support-session-7"
            ),
        )
    )

    assert calls == [("support-session-7", "EMP-014", "It disconnects after a minute.")]
    assert response["choices"][0]["message"]["content"] == "What error do you see?"
    assert response["ga_voiceai_session_id"] == "support-session-7"


@pytest.mark.asyncio
async def test_custom_llm_adapter_accepts_secret_dynamic_variable_header(monkeypatch):
    async def start(employee_id: str, message: str, channel: str, **_kwargs):
        assert (employee_id, message, channel) == ("EMP-032", "Help with VPN", "voice")
        return {"session_id": "session-8", "pending": None, "assistant_message": "Let's check it."}

    monkeypatch.setattr(dispatcher, "start_session", start)

    async def no_existing_session(*_args):
        return None

    monkeypatch.setattr(repos, "find_active_voice_session", no_existing_session)
    response = await custom_llm_completion(
        OpenAICompletionRequest(
            messages=[OpenAIMessage(role="user", content="Help with VPN")],
        ),
        voice_bridge_token_header=create_bridge_token("EMP-032"),
    )

    assert response["ga_voiceai_session_id"] == "session-8"
