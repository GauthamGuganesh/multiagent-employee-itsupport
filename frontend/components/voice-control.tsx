"use client";

import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { useState } from "react";

import { api } from "@/lib/api";
import { Button, Spinner } from "@/components/ui";

type VoiceBootstrap = {
  signed_url: string;
  dynamic_variables: Record<string, string>;
};

function VoiceSession() {
  const { startSession, endSession, status, isListening, isSpeaking } = useConversation({
    onError: () => undefined,
  });
  const [error, setError] = useState<string | null>(null);

  const active = status === "connected" || status === "connecting";
  const label = isSpeaking ? "Speaking…" : isListening ? "Listening…" : active ? "Connected" : "Voice";

  async function toggleVoice() {
    setError(null);
    if (active) {
      endSession();
      return;
    }
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const bootstrap = await api.get<VoiceBootstrap>("/api/voice/signed-url");
      startSession({
        signedUrl: bootstrap.signed_url,
        dynamicVariables: bootstrap.dynamic_variables,
        onError: (message) => setError(message || "Voice connection failed. You can keep typing below."),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Microphone access was unavailable.");
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        variant={active ? "danger" : "secondary"}
        onClick={() => void toggleVoice()}
        aria-pressed={active}
      >
        {status === "connecting" && <Spinner className="h-3.5 w-3.5" />}
        <span aria-hidden>◉</span> {active ? "End voice" : "Talk"}
      </Button>
      <span className="text-xs text-muted" aria-live="polite">{label}</span>
      {error && <span className="max-w-48 text-right text-xs text-red-600 dark:text-red-400">{error}</span>}
    </div>
  );
}

export function VoiceControl() {
  return (
    <ConversationProvider>
      <VoiceSession />
    </ConversationProvider>
  );
}
