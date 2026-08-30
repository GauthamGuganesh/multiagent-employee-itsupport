# ElevenLabs Voice Setup

Voice is an optional transport layer. The browser keeps the employee’s
authenticated application session; FastAPI creates a short-lived signed bridge
token before the ElevenLabs conversation starts. Do not add IT tools, Neo4j
queries, or privileged actions directly to ElevenLabs.

## Local configuration

Add these values to `.env`:

```env
ELEVENLABS_API_KEY=<server-side-api-key>
ELEVENLABS_AGENT_ID=<private-agent-id>
# Optional: protects the echo-only Custom LLM smoke-test endpoint.
IT_ELEVENLABS_CUSTOM_LLM_KEY=<long-random-secret>
```

Start FastAPI on port 8000, then expose only that server through one tunnel:

```powershell
ngrok http 8000
# or
cloudflared tunnel --url http://localhost:8000
```

Use the generated HTTPS address in the ElevenLabs dashboard webhook URL:

```text
https://<temporary-host>/api/voice/agent-tool
```

## Private Agent configuration

1. Create a private Conversational AI agent in ElevenLabs.
2. Add a server webhook tool named `it_support` with inputs:
   `voice_bridge_token` (string), `message` (string), and optional `session_id`
   (string).
3. Point it to the HTTPS URL above. Its response field is `response`; retain
   `session_id` in the agent’s conversation context and send it on subsequent
   calls.
4. Configure dynamic variables `employee_id` and `voice_bridge_token`. The
   frontend receives them only from authenticated `GET /api/voice/signed-url`.
5. Do not use an ElevenLabs field as the authority for employee identity. The
   backend validates the signed bridge token and calls the shared dispatcher.

## Custom LLM transport smoke test

`POST /v1/chat/completions` is an OpenAI-compatible, echo-only endpoint for
testing a Custom LLM connection. It returns “I heard you say: …” and never
touches LangGraph, tools, tickets, or organization data. Set its URL to:

```text
https://<temporary-host>/v1/chat/completions
```

If `IT_ELEVENLABS_CUSTOM_LLM_KEY` is set, configure a Bearer Authorization
header with that exact value. Keep this endpoint for transport testing only;
the employee app’s signed-agent flow is the production integration.

## Failure behavior

If microphone access, ElevenLabs, or the tunnel fails, the employee can keep
using text chat. Voice transcripts and responses that reach FastAPI are stored
in the same support session and audit stream as web interactions.
