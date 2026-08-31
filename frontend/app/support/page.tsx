"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useRouter } from "next/navigation";

import { EmployeeHeader, useMe } from "@/components/shell";
import { VoiceControl, type VoiceTranscript } from "@/components/voice-control";
import { Badge, Button, Card, Spinner } from "@/components/ui";
import { api, isAuthError } from "@/lib/api";
import { useSessionProgress } from "@/lib/sse";
import type { ChatMessage, ChatResult, PendingInteraction, SessionDetail } from "@/lib/types";

const EXAMPLES = [
  "My VPN keeps disconnecting.",
  "I’m locked out of my account.",
  "Install Docker Desktop on my laptop.",
];

function MessageBubble({ message }: { message: ChatMessage }) {
  const isEmployee = message.role === "employee";
  return (
    <div className={`flex ${isEmployee ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${isEmployee ? "bg-primary text-white" : "border border-border-token bg-surface text-foreground"}`}>
        {message.content}
      </div>
    </div>
  );
}

function PendingCard({ pending, onConfirm }: { pending: Extract<PendingInteraction, { type: "confirmation" }>; onConfirm: (value: boolean) => void }) {
  return (
    <Card className="border-amber-200 bg-amber-50/70 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-medium">Confirm this action</p><p className="mt-1 text-sm text-muted">{pending.action_summary}</p></div><Badge className="bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">{pending.risk_level} risk</Badge></div>
      <div className="mt-4 flex gap-2"><Button type="button" variant="success" onClick={() => onConfirm(true)}>Proceed</Button><Button type="button" variant="secondary" onClick={() => onConfirm(false)}>Not now</Button></div>
    </Card>
  );
}

export default function SupportPage() {
  const router = useRouter();
  const me = useMe();
  const reduceMotion = useReducedMotion();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<PendingInteraction | null>(null);
  const [terminalStatus, setTerminalStatus] = useState<ChatResult["terminal_status"]>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [voiceActive, setVoiceActive] = useState(false);
  useSessionProgress(sessionId, setProgress);

  const loadSession = useCallback(async (id: string) => {
    const detail = await api.get<SessionDetail>(`/api/chat/sessions/${id}`);
    setMessages(detail.messages);
    setPending(detail.pending);
    setTerminalStatus(detail.terminal_status as ChatResult["terminal_status"]);
  }, []);
  useEffect(() => {
    if (!sessionId) return;
    const timer = window.setTimeout(() => void loadSession(sessionId), 0);
    return () => window.clearTimeout(timer);
  }, [loadSession, sessionId]);

  // Voice transcript comes straight from the live ElevenLabs stream, so each
  // spoken turn appears immediately in the same chat — no polling, no lag.
  const handleVoiceTranscript = useCallback((turn: VoiceTranscript) => {
    setMessages((previous) => {
      const last = previous[previous.length - 1];
      // Guard against an identical repeated frame from the transport.
      if (last && last.role === turn.role && last.content === turn.text) return previous;
      return [...previous, { role: turn.role, content: turn.text, source: "voice", at: new Date().toISOString() }];
    });
  }, []);

  const handleVoiceActiveChange = useCallback((active: boolean) => {
    setVoiceActive(active);
    setProgress(active ? "Voice conversation is live." : null);
  }, []);

  const send = useCallback(async (text: string, confirmation?: boolean) => {
    const clean = text.trim();
    if (!clean && confirmation === undefined) return;
    setBusy(true); setError(null); setProgress(sessionId ? "Continuing your request…" : "Understanding your request…");
    try {
      let result: ChatResult;
      if (!sessionId) { result = await api.post<ChatResult>("/api/chat/sessions", { message: clean }); setSessionId(result.session_id); }
      else if (confirmation !== undefined) result = await api.post<ChatResult>(`/api/chat/sessions/${sessionId}/confirm`, { confirmed: confirmation });
      else result = await api.post<ChatResult>(`/api/chat/sessions/${sessionId}/messages`, { message: clean });
      setPending(result.pending);
      setTerminalStatus(result.terminal_status);
      // The backend persists both questions and final answers. Reloading that
      // transcript prevents an optimistic bubble and a pending card from
      // rendering the same agent message twice.
      await loadSession(result.session_id);
      setProgress(result.ticket_number ? `Request ${result.ticket_number} is being tracked.` : result.pending ? progress : null);
    } catch (cause) { if (isAuthError(cause)) router.push("/"); else setError(cause instanceof Error ? cause.message : "We couldn’t process that request."); }
    finally { setBusy(false); }
  }, [loadSession, progress, router, sessionId]);

  async function submit(event: FormEvent) {
    event.preventDefault(); const text = draft; setDraft("");
    setMessages((previous) => [...previous, { role: "employee", content: text, source: "web", at: new Date().toISOString() }]);
    await send(text);
  }
  function startNewRequest() {
    setSessionId(null); setMessages([]); setPending(null); setTerminalStatus(null); setDraft(""); setError(null); setProgress(null);
  }
  const greeting = `Hi${me?.profile?.name ? `, ${me.profile.name.split(" ")[0]}` : ""}. What can IT help with?`;

  return <><EmployeeHeader employeeName={me?.profile?.name} /><main className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-6">
    <section className="mb-5 flex items-start justify-between gap-4"><div><h1 className="text-xl font-semibold tracking-tight">{greeting}</h1><p className="mt-1 text-sm text-muted">Describe the issue in your own words, or start a voice conversation.</p></div><VoiceControl onTranscript={handleVoiceTranscript} onActiveChange={handleVoiceActiveChange} /></section>
    <section className="flex min-h-[420px] flex-1 flex-col rounded-2xl border border-border-token bg-surface shadow-sm"><div className="flex-1 space-y-3 p-4 sm:p-6" aria-live="polite">
      {messages.length === 0 ? <div className="flex h-full flex-col justify-center py-10 text-center"><div className="mx-auto max-w-md"><p className="text-sm text-muted">I can help with access, devices, network issues, security concerns, and existing IT requests.</p><div className="mt-5 flex flex-wrap justify-center gap-2">{EXAMPLES.map((example) => <button key={example} type="button" onClick={() => setDraft(example)} className="rounded-full border border-border-token px-3 py-1.5 text-sm text-muted transition-colors hover:border-indigo-300 hover:bg-surface-muted hover:text-foreground">{example}</button>)}</div></div></div> : messages.map((message, index) => <motion.div key={`${message.at}-${index}`} initial={reduceMotion ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}><MessageBubble message={message} /></motion.div>)}
      {progress && <div className="flex items-center gap-2 text-sm text-ai">{busy && <Spinner className="h-3.5 w-3.5" />}{progress}</div>}
      {pending?.type === "confirmation" && <PendingCard pending={pending} onConfirm={(value) => void send("", value)} />}{error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
    </div>{terminalStatus ? <div className="flex items-center justify-between gap-3 border-t border-border-token p-3 sm:p-4"><p className="text-sm text-muted">This request is {terminalStatus === "resolved" ? "complete" : "with the support team"}.</p><Button type="button" variant="secondary" onClick={startNewRequest}>Start a new request</Button></div> : <form onSubmit={submit} className="border-t border-border-token p-3 sm:p-4"><div className="flex items-end gap-2"><textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} disabled={busy || voiceActive || pending?.type === "confirmation"} placeholder={voiceActive ? "Voice conversation is active…" : pending?.type === "question" ? "Type your answer…" : "Tell us what’s happening…"} className="min-h-11 flex-1 resize-none rounded-xl border border-border-token bg-surface px-3 py-2 text-sm outline-none placeholder:text-muted focus:ring-2 focus:ring-indigo-400/60 disabled:opacity-50" /><Button type="submit" disabled={busy || voiceActive || !draft.trim() || pending?.type === "confirmation"}>{busy ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : "Send"}</Button></div></form>}
    </section></main></>;
}
