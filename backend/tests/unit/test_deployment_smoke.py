"""Deployment wiring checks that never contact external production services."""
import pytest

from app.api.routes_voice import OpenAICompletionRequest, OpenAIMessage, custom_llm_echo
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
async def test_custom_llm_smoke_adapter_streams_done_marker():
    response = await custom_llm_echo(
        OpenAICompletionRequest(
            stream=True,
            messages=[OpenAIMessage(role="user", content="hello from a transport smoke test")],
        )
    )
    body = "".join([chunk async for chunk in response.body_iterator])

    assert response.media_type == "text/event-stream"
    assert "data: [DONE]" in body
