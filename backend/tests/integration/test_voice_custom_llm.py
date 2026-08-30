"""Custom LLM transport must delegate to the real LangGraph dispatcher."""
from sqlalchemy import select

from app.api.routes_voice import OpenAICompletionRequest, OpenAIMessage, create_bridge_token, custom_llm_completion
from app.db.base import db_session
from app.db.models import SupportSession
from tests.conftest import specialist_finish, supervisor_decision


async def test_custom_llm_adapter_runs_the_persisted_voice_graph(graph, provider, org_stub):
    provider.enqueue(
        supervisor_decision(
            decision="close_session",
            target_specialist=None,
            category="other",
            intent="simple voice question",
            message_to_employee="I can help with that through the support desk.",
        )
    )

    response = await custom_llm_completion(
        OpenAICompletionRequest(
            stream=True,
            voice_bridge_token=create_bridge_token("EMP-032"),
            messages=[OpenAIMessage(role="user", content="What kinds of IT help can you provide?")],
        )
    )
    body = "".join([chunk async for chunk in response.body_iterator])
    session_id = response.headers["X-GA-VoiceAI-Session-Id"]

    assert "I can help with that through the support desk." in body
    assert "data: [DONE]" in body

    async with db_session() as session:
        support_session = await session.scalar(select(SupportSession).where(SupportSession.id == session_id))
    assert support_session is not None
    assert support_session.channel == "voice"
    assert support_session.final_response == "I can help with that through the support desk."


async def test_custom_llm_reuses_one_session_for_multiple_utterances(graph, provider, org_stub):
    token = create_bridge_token("EMP-032")
    provider.enqueue(
        supervisor_decision(
            decision="ask_employee",
            target_specialist=None,
            category="network",
            intent="unclear VPN issue",
            question_for_employee="Is the VPN failing to connect or disconnecting after it connects?",
        )
    )
    first = await custom_llm_completion(
        OpenAICompletionRequest(
            voice_bridge_token=token,
            messages=[OpenAIMessage(role="user", content="My VPN is not working")],
        )
    )
    session_id = first["ga_voiceai_session_id"]

    provider.enqueue(
        supervisor_decision(target_specialist="network", category="network", intent="VPN drops"),
        specialist_finish(agent="network", resolution_summary="The VPN profile was refreshed."),
        supervisor_decision(
            decision="run_workflow", target_specialist=None, workflow="resolution", category="network"
        ),
    )
    second = await custom_llm_completion(
        OpenAICompletionRequest(
            voice_bridge_token=token,
            messages=[OpenAIMessage(role="user", content="It connects, then drops after a minute.")],
        )
    )

    assert second["ga_voiceai_session_id"] == session_id
    assert "VPN profile was refreshed" in second["choices"][0]["message"]["content"]
