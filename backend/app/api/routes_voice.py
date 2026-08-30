"""ElevenLabs voice integration.

The browser uses @elevenlabs/react with a signed URL minted here (the API key
never reaches the client). The ElevenLabs agent calls back into the same
session dispatcher through a webhook tool, so voice and text share one
pipeline. Voice confirms INTENT only — identity comes from the authenticated
web session that requested the signed URL.
"""
import json
import time
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field

from app.api import dispatcher
from app.api.deps import get_current_employee
from app.config import get_settings

router = APIRouter(prefix="/api/voice", tags=["voice"])
custom_llm_router = APIRouter(tags=["voice"])

SIGNED_URL_ENDPOINT = "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"


def _bridge_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="it-support-voice-bridge")


def create_bridge_token(employee_id: str) -> str:
    """A short-lived, signed mapping from an ElevenLabs call to app identity."""
    return _bridge_serializer().dumps({"employee_id": employee_id})


def resolve_bridge_token(token: str) -> str:
    try:
        data = _bridge_serializer().loads(
            token, max_age=get_settings().voice_bridge_token_max_age_seconds
        )
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=401, detail="invalid or expired voice bridge token") from exc
    employee_id = data.get("employee_id")
    if not isinstance(employee_id, str):
        raise HTTPException(status_code=401, detail="invalid voice bridge token")
    return employee_id


@router.get("/config")
async def voice_config(_: str = Depends(get_current_employee)):
    settings = get_settings()
    return {"enabled": bool(settings.elevenlabs_api_key and settings.elevenlabs_agent_id)}


async def _issue_voice_token(employee_id: str) -> dict:
    settings = get_settings()
    if not (settings.elevenlabs_api_key and settings.elevenlabs_agent_id):
        raise HTTPException(status_code=503, detail="voice is not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            SIGNED_URL_ENDPOINT,
            params={"agent_id": settings.elevenlabs_agent_id},
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="could not obtain signed url")
    signed_url_value = resp.json().get("signed_url")
    if not signed_url_value:
        raise HTTPException(status_code=502, detail="ElevenLabs returned no signed URL")
    return {
        "signed_url": signed_url_value,
        # The frontend passes these only as ElevenLabs dynamic variables. The
        # callback authenticates with the signed bridge token, never the id.
        "dynamic_variables": {
            "employee_id": employee_id,
            "voice_bridge_token": create_bridge_token(employee_id),
        },
    }


@router.get("/signed-url")
async def signed_url(employee_id: str = Depends(get_current_employee)):
    return await _issue_voice_token(employee_id)


@router.get("/token")
async def voice_token(employee_id: str = Depends(get_current_employee)):
    """Deployment-friendly alias for the existing signed ElevenLabs session URL."""
    return await _issue_voice_token(employee_id)


class AgentToolRequest(BaseModel):
    """Payload of the ElevenLabs `it_support` webhook tool.

    Configure the agent tool to pass `voice_bridge_token` from the dynamic
    variables returned by /signed-url. Its employee id is deliberately not
    accepted from ElevenLabs, because voice metadata is not authentication.
    """

    voice_bridge_token: str = Field(min_length=16)
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


@router.post("/agent-tool")
async def agent_tool(body: AgentToolRequest):
    employee_id = resolve_bridge_token(body.voice_bridge_token)
    if body.session_id:
        result = await dispatcher.continue_session(
            body.session_id, body.employee_id, body.message, channel="voice"
        )
    else:
        result = await dispatcher.start_session(body.employee_id, body.message, channel="voice")
    return {"session_id": result.get("session_id"), "response": _voice_response_text(result)}


# ---- ElevenLabs Custom LLM adapter --------------------------------------

# ElevenLabs' Custom LLM integration calls an OpenAI-compatible chat
# completions endpoint. `elevenlabs_extra_body` is deliberately a small,
# typed extension: external conversation metadata is useful for transport, but
# it never supplies identity or the authoritative conversation transcript.


class OpenAIContentPart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "text"
    text: str | None = None


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = Field(min_length=1, max_length=32)
    content: str | list[OpenAIContentPart] | None = None


class ElevenLabsExtraBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voice_bridge_token: str | None = Field(default=None, min_length=16)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class OpenAICompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "ga-voiceai-support"
    messages: list[OpenAIMessage] = Field(min_length=1)
    stream: bool = False
    # Custom LLM extra parameters are configured in ElevenLabs. These fields
    # are also accepted at the top level for compatible clients and local
    # transport tests.
    voice_bridge_token: str | None = Field(default=None, min_length=16)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    elevenlabs_extra_body: ElevenLabsExtraBody | None = None


def _latest_employee_message(messages: list[OpenAIMessage]) -> str:
    """Extract only the newest employee turn from the provider request.

    ElevenLabs may replay its own transcript on every request. It is transport
    context only; PostgreSQL/LangGraph retain the authoritative conversation.
    """
    for message in reversed(messages):
        if message.role != "user":
            continue
        if isinstance(message.content, str):
            text = message.content.strip()
        elif isinstance(message.content, list):
            text = "\n".join(
                part.text.strip()
                for part in message.content
                if part.type in {"text", "input_text"} and part.text and part.text.strip()
            )
        else:
            text = ""
        if text:
            return text
        raise HTTPException(status_code=422, detail="newest user message must contain text")
    raise HTTPException(status_code=422, detail="messages must include an employee user message")


def _bridge_context(body: OpenAICompletionRequest) -> tuple[str, str | None]:
    extra = body.elevenlabs_extra_body
    token = body.voice_bridge_token or (extra.voice_bridge_token if extra else None)
    session_id = body.session_id or (extra.session_id if extra else None)
    if not token:
        raise HTTPException(status_code=401, detail="voice bridge token is required")
    return resolve_bridge_token(token), session_id


def _voice_response_text(result: dict) -> str:
    """Render dispatcher state for speech without recreating agent logic."""
    if result.get("error"):
        raise HTTPException(status_code=result.get("status_code", 404), detail=result["error"])
    pending = result.get("pending")
    if pending and pending.get("type") == "confirmation":
        return (
            f"I need your confirmation: {pending.get('action_summary')} "
            "Say yes to proceed or no to cancel."
        )
    if pending:
        return pending.get("question", "Could you tell me a bit more?")
    return result.get("assistant_message") or "I've handled that. Anything else?"


def _check_custom_llm_key(authorization: str | None) -> None:
    key = get_settings().elevenlabs_custom_llm_key
    if key and authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="invalid custom LLM credential")


@custom_llm_router.post("/v1/chat/completions", include_in_schema=False)
async def custom_llm_completion(
    body: OpenAICompletionRequest,
    authorization: str | None = Header(default=None),
):
    """Thin OpenAI-compatible bridge from ElevenLabs to the session dispatcher.

    The adapter validates the request, uses only its newest employee message,
    resolves the signed app identity, and delegates all support behavior to
    LangGraph through `dispatcher`. It intentionally owns no routing, agent,
    or tool logic.
    """
    _check_custom_llm_key(authorization)
    employee_id, session_id = _bridge_context(body)
    message = _latest_employee_message(body.messages)
    if session_id:
        result = await dispatcher.continue_session(session_id, employee_id, message, channel="voice")
    else:
        result = await dispatcher.start_session(employee_id, message, channel="voice")
    response_text = _voice_response_text(result)
    created = int(time.time())
    support_session_id = result.get("session_id")
    completion_id = f"chatcmpl-gavoiceai-{support_session_id or created}"
    if not body.stream:
        response = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
        }
        if support_session_id:
            response["ga_voiceai_session_id"] = support_session_id
        return response

    async def stream() -> AsyncIterator[str]:
        role_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
        content_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "delta": {"content": response_text}, "finish_reason": None}],
        }
        finish_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(role_chunk)}\n\n"
        yield f"data: {json.dumps(content_chunk)}\n\n"
        yield f"data: {json.dumps(finish_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    headers = {"X-GA-VoiceAI-Session-Id": str(support_session_id)} if support_session_id else None
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)
