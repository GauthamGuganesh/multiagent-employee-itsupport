"""Application settings and hard execution limits.

Every limit that bounds autonomous execution lives here as a configurable
constant. Guards import these values and enforce them in code — prompts never
carry enforcement responsibility.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root .env (two levels up from this file: backend/app/config.py)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_prefix="IT_",
        extra="ignore",
    )

    # --- LLM ---
    llm_provider: str = "openai"  # openai | scripted | fake
    llm_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 2048
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")

    # --- Databases ---
    postgres_dsn: str = "postgresql+asyncpg://itsupport:itsupport@localhost:5433/itsupport"
    # Hosted Neo4j (such as Aura). Values must come from the provider portal;
    # no local Neo4j container is part of this project.
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # --- Cross-session memory ---
    memory_backend: str = "local"  # local | mem0 | off
    memory_store_path: str = "./.memstore"  # local backend storage
    memory_max_retrieved: int = 5
    mem0_api_key: str = Field(default="", validation_alias="MEM0_API_KEY")

    # --- Hard execution limits (enforced in code) ---
    max_supervisor_cycles: int = 8
    max_specialist_tool_steps: int = 5
    max_agent_handoffs: int = 4
    max_structured_output_retries: int = 2
    loop_signature_repeat_limit: int = 2
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
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Voice (optional) ---
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_custom_llm_key: str = ""
    voice_bridge_token_max_age_seconds: int = 60 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
