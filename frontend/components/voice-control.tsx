"use client";

import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { Spinner, cx } from "@/components/ui";

type VoiceBootstrap = {
  signed_url: string;
  dynamic_variables: Record<string, string>;
};

export type VoiceTranscript = { role: "employee" | "assistant"; text: string };

type VoiceControlProps = {
  /** Fires for each finalized turn (employee speech-to-text and agent reply)
   *  so the page can render them live in the same chat transcript. */
  onTranscript?: (turn: VoiceTranscript) => void;
  /** Fires when a voice conversation starts/ends so the page can disable text. */
  onActiveChange?: (active: boolean) => void;
};

type Phase = "idle" | "connecting" | "connected" | "error";

function VoiceSession({ onTranscript, onActiveChange }: VoiceControlProps) {
  // Keep parent callbacks in refs so registering them with the SDK doesn't
  // depend on referential stability from the parent.
  const transcriptRef = useRef(onTranscript);
  const activeRef = useRef(onActiveChange);
  transcriptRef.current = onTranscript;
  activeRef.current = onActiveChange;

  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  const conversation = useConversation({
    onConnect: () => {
      setPhase("connected");
      activeRef.current?.(true);
    },
    onDisconnect: () => {
      setPhase("idle");
      activeRef.current?.(false);
    },
    onError: (message: unknown) => {
      setError(
        typeof message === "string" && message
          ? message
          : "The voice connection dropped. You can keep going by text."
      );
      setPhase("error");
      activeRef.current?.(false);
    },
    // The one signal that makes voice meaningful on screen: each finalized turn.
    onMessage: ({ message, source }: { message: string; source: "user" | "ai" }) => {
      const text = message?.trim();
      if (!text) return;
      transcriptRef.current?.({ role: source === "ai" ? "assistant" : "employee", text });
    },
  });

  const { status, isSpeaking, isListening, startSession, endSession } = conversation;
  const active = status === "connected" || phase === "connecting";

  const label =
    phase === "connecting"
      ? "Connecting…"
      : phase === "error"
        ? "Voice unavailable"
        : status === "connected"
          ? isSpeaking
            ? "Assistant speaking…"
            : isListening
              ? "Listening…"
              : "Connected"
          : "Talk";

  const start = useCallback(async () => {
    setError(null);
    setPhase("connecting");
    try {
      // Fail fast and clearly if the mic is blocked — the most common failure.
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const bootstrap = await api.get<VoiceBootstrap>("/api/voice/signed-url");
      startSession({
        signedUrl: bootstrap.signed_url,
        dynamicVariables: bootstrap.dynamic_variables,
      });
    } catch (cause) {
      const message =
        cause instanceof DOMException && cause.name === "NotAllowedError"
          ? "Microphone access is blocked. Allow it in your browser to use voice."
          : cause instanceof Error && cause.message
            ? cause.message
            : "Voice couldn't start. You can keep going by text.";
      setError(message);
      setPhase("error");
    }
  }, [startSession]);

  const stop = useCallback(() => {
    endSession();
    setPhase("idle");
  }, [endSession]);

  return (
    <div className="flex flex-col items-end gap-1.5">
      <button
        type="button"
        onClick={() => (active ? stop() : void start())}
        aria-pressed={active}
        aria-label={active ? "End voice conversation" : "Start voice conversation"}
        className={cx(
          "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1",
          active
            ? "bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-400"
            : "bg-ai text-white hover:opacity-90 focus-visible:ring-violet-400"
        )}
      >
        {phase === "connecting" ? (
          <Spinner className="h-4 w-4 border-white/40 border-t-white" />
        ) : (
          <MicRing active={status === "connected"} speaking={isSpeaking} />
        )}
        {active ? "End voice" : "Talk"}
      </button>
      <span
        className={cx("text-xs", phase === "error" ? "text-red-600 dark:text-red-400" : "text-muted")}
        aria-live="polite"
      >
        {label}
      </span>
      {error && (
        <span className="max-w-56 text-right text-xs text-red-600 dark:text-red-400">{error}</span>
      )}
    </div>
  );
}

/** A small mic glyph that pulses violet while connected, brighter while the
 *  assistant speaks — the at-a-glance "it's live" affordance. */
function MicRing({ active, speaking }: { active: boolean; speaking: boolean }) {
  return (
    <span className="relative flex h-4 w-4 items-center justify-center">
      {active && (
        <span
          className={cx(
            "absolute inline-flex h-full w-full rounded-full opacity-60",
            speaking ? "animate-ping bg-white/70" : "animate-pulse bg-white/40"
          )}
          aria-hidden
        />
      )}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden className="relative">
        <rect x="9" y="2" width="6" height="12" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
    </span>
  );
}

export function VoiceControl(props: VoiceControlProps) {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ enabled: boolean }>("/api/voice/config")
      .then((r) => !cancelled && setEnabled(r.enabled))
      .catch(() => !cancelled && setEnabled(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // While we don't yet know, reserve the space to avoid a layout jump.
  if (enabled === null) return <div className="h-[46px] w-24" aria-hidden />;

  // Voice not configured (or backend unreachable): a clear, non-broken cue.
  if (!enabled) {
    return (
      <div
        className="flex items-center gap-2 rounded-full border border-border-token px-3.5 py-2 text-sm text-muted"
        title="Voice isn't available right now — please continue by text."
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3M3 3l18 18" />
        </svg>
        Voice off
      </div>
    );
  }

  return (
    <ConversationProvider>
      <VoiceSession {...props} />
    </ConversationProvider>
  );
}
