"""Application settings and hard execution limits.

Every limit that bounds autonomous execution lives here as a configurable
constant. Guards import these values and enforce them in code — prompts never
carry enforcement responsibility.
"""
import json
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root .env (two levels up from this file: backend/app/config.py)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_prefix="IT_",
        extra="ignore",
        # Render commonly stores CORS_ORIGINS as a comma-separated string.
        # Decode it in _parse_cors_origins instead of Pydantic requiring JSON.
        enable_decoding=False,
    )

    # --- LLM ---
    llm_provider: str = "openai"  # openai | scripted | fake
    llm_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 2048
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")

    # --- Databases ---
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://itsupport:itsupport@localhost:5433/itsupport",
        validation_alias=AliasChoices("DATABASE_URL", "IT_POSTGRES_DSN"),
    )
    # Hosted Neo4j (such as Aura). Values must come from the provider portal;
    # no local Neo4j container is part of this project.
    neo4j_uri: str = Field(default="", validation_alias=AliasChoices("NEO4J_URI", "IT_NEO4J_URI"))
    neo4j_user: str = Field(
        default="", validation_alias=AliasChoices("NEO4J_USERNAME", "NEO4J_USER", "IT_NEO4J_USER")
    )
    neo4j_password: str = Field(
        default="", validation_alias=AliasChoices("NEO4J_PASSWORD", "IT_NEO4J_PASSWORD")
    )
    neo4j_database: str = "neo4j"

    # --- Cross-session memory ---
    memory_backend: str = "local"  # local | mem0 | off
    memory_store_path: str = "./.memstore"  # local backend storage
    memory_max_retrieved: int = 5
    mem0_api_key: str = Field(default="", validation_alias=AliasChoices("MEM0_API_KEY", "IT_MEM0_API_KEY"))

    # --- Hard execution limits (enforced in code) ---
    max_supervisor_cycles: int = 8
    max_specialist_tool_steps: int = 5
    max_agent_handoffs: int = 4
    max_structured_output_retries: int = 2
    loop_signature_repeat_limit: int = 2
    # A question is useful only when it unlocks a materially different next
    # step. This session-wide guard prevents an LLM from rephrasing the same
    # interview across employee replies.
    # Emergency ceiling only, not a conversational target. Evidence readiness
    # and repeated-question detection control normal conversations.
    max_information_requests: int = 20
    require_employee_resolution_confirmation: bool = True
    create_ticket_for_resolved_sessions: bool = False
    min_specialist_confidence: float = 0.35

    # --- Ticket aging ---
    pending_escalation_days: int = 3  # calendar days

    # --- Conversation compaction ---
    conversation_compaction_token_threshold: int = 12000
    recent_messages_to_retain: int = 8

    # --- API / auth (demo-grade) ---
    session_secret: str = "dev-only-change-me"
    demo_password_prefix: str = "gavoiceai-"
    admin_username: str = "admin"
    admin_password: str = "ga-voiceai-admin"
    app_env: str = Field(default="development", validation_alias=AliasChoices("APP_ENV", "IT_APP_ENV"))
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        validation_alias=AliasChoices("CORS_ORIGINS", "IT_CORS_ORIGINS"),
    )

    # --- Voice (optional) ---
    elevenlabs_api_key: str = Field(
        default="", validation_alias=AliasChoices("ELEVENLABS_API_KEY", "IT_ELEVENLABS_API_KEY")
    )
    elevenlabs_agent_id: str = Field(
        default="", validation_alias=AliasChoices("ELEVENLABS_AGENT_ID", "IT_ELEVENLABS_AGENT_ID")
    )
    elevenlabs_custom_llm_key: str = ""
    voice_bridge_token_max_age_seconds: int = 60 * 60

    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def _normalize_postgres_url(cls, value: str) -> str:
        """Accept Render's standard URL while keeping SQLAlchemy async."""
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Permit either a JSON array or a comma-separated Render variable."""
        if isinstance(value, list):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list) or not all(isinstance(origin, str) for origin in parsed):
                raise ValueError("CORS_ORIGINS must be a list of origin strings")
            return parsed
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
