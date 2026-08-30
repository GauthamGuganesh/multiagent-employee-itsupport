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
# Optional: protects the Custom LLM adapter endpoint.
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

## Custom LLM adapter

`POST /v1/chat/completions` is an OpenAI-compatible adapter for an ElevenLabs
Custom LLM. It validates the request, reads only the newest `user` message,
and calls the same session dispatcher as web chat and the webhook tool. It
does not use ElevenLabs message history as support-session state.

Set its URL to:

```text
https://<temporary-host>/v1/chat/completions
```

If `IT_ELEVENLABS_CUSTOM_LLM_KEY` is set, configure a Bearer Authorization
header with that exact value. Configure the Custom LLM extra body with the
signed `voice_bridge_token` from the authenticated `/api/voice/signed-url`
response. Omit `session_id` on the first request; send the GA-VoiceAI support
session ID returned as `X-GA-VoiceAI-Session-Id` (or
`ga_voiceai_session_id` for a non-streaming response) on later requests. The
adapter then resumes the persisted LangGraph session rather than replaying the
external message history.

## Failure behavior

If microphone access, ElevenLabs, or the tunnel fails, the employee can keep
using text chat. Voice transcripts and responses that reach FastAPI are stored
in the same support session and audit stream as web interactions.
