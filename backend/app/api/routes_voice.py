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
from pydantic import BaseModel, Field

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

    pending = result.get("pending")
    if pending and pending.get("type") == "confirmation":
        text = (
            f"I need your confirmation: {pending.get('action_summary')} "
            "Say yes to proceed or no to cancel."
        )
    elif pending:
        text = pending.get("question", "Could you tell me a bit more?")
    else:
        text = result.get("assistant_message") or "I've handled that. Anything else?"
    return {"session_id": result.get("session_id"), "response": text}


# ---- Optional local Custom LLM transport smoke test ----------------------

class OpenAIMessage(BaseModel):
    role: str
    content: str | list[object]


class OpenAICompletionRequest(BaseModel):
    model: str = "gavoiceai-echo"
    messages: list[OpenAIMessage] = Field(min_length=1)
    stream: bool = False


def _latest_transcript(messages: list[OpenAIMessage]) -> str:
    for message in reversed(messages):
        if message.role != "user":
            continue
        if isinstance(message.content, str):
            return message.content.strip()
    return ""


def _check_custom_llm_key(authorization: str | None) -> None:
    key = get_settings().elevenlabs_custom_llm_key
    if key and authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="invalid custom LLM credential")


@custom_llm_router.post("/v1/chat/completions", include_in_schema=False)
async def custom_llm_echo(
    body: OpenAICompletionRequest,
    authorization: str | None = Header(default=None),
):
    """OpenAI-compatible echo endpoint for testing an ElevenLabs Custom LLM.

    It intentionally never invokes LangGraph or business tools. Production
    voice uses the signed-agent route above, which preserves app auth and the
    existing dispatcher/session model.
    """
    _check_custom_llm_key(authorization)
    response_text = f"I heard you say: {_latest_transcript(body.messages) or 'nothing yet'}."
    created = int(time.time())
    if not body.stream:
        return {
            "id": f"chatcmpl-gavoiceai-{created}",
            "object": "chat.completion",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
        }

    async def stream() -> AsyncIterator[str]:
        chunk = {
            "id": f"chatcmpl-gavoiceai-{created}",
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "delta": {"content": response_text}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
