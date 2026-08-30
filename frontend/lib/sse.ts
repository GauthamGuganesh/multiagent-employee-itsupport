"use client";

/** EventSource hooks for the two SSE feeds. */
import { useEffect, useRef } from "react";

import type { AuditEvent } from "@/lib/types";

/** Employee-facing progress copy for one session. */
export function useSessionProgress(
  sessionId: string | null,
  onProgress: (text: string) => void
) {
  const handler = useRef(onProgress);

  useEffect(() => {
    handler.current = onProgress;
  }, [onProgress]);

  useEffect(() => {
    if (!sessionId) return;
    const source = new EventSource(`/api/stream/session/${sessionId}`);
    source.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data);
        if (data.text) handler.current(data.text);
      } catch {
        /* ignore malformed frames */
      }
    });
    return () => source.close();
  }, [sessionId]);
}

/** Full audit event firehose for the command center. */
export function useOpsEvents(onEvent: (event: AuditEvent) => void) {
  const handler = useRef(onEvent);

  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    const source = new EventSource(`/api/stream/ops`);
    source.addEventListener("audit", (e) => {
      try {
        handler.current(JSON.parse((e as MessageEvent).data));
      } catch {
        /* ignore malformed frames */
      }
    });
    return () => source.close();
  }, []);
}
