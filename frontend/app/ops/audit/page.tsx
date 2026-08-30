"use client";

/** Command center — filterable audit event log with live SSE prepend. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { api, isAuthError } from "@/lib/api";
import { useOpsEvents } from "@/lib/sse";
import type { AuditEvent } from "@/lib/types";
import { Badge, Card, EmptyState, ErrorState, Input, Select, Skeleton, cx } from "@/components/ui";
import { formatDateTime } from "@/lib/format";

/* ------------------------------------------------------------------ */
/* Event taxonomy (mirrors backend/app/events/types.py)                */
/* ------------------------------------------------------------------ */

const EVENT_TYPES = [
  "SESSION_STARTED",
  "SUPERVISOR_DECISION",
  "AGENT_STARTED",
  "AGENT_COMPLETED",
  "TOOL_CALLED",
  "TOOL_SUCCEEDED",
  "TOOL_FAILED",
  "HANDOFF_REQUESTED",
  "HANDOFF_COMPLETED",
  "STRUCTURED_OUTPUT_RETRY",
  "STRUCTURED_OUTPUT_FAILED",
  "LOOP_GUARD_TRIGGERED",
  "USER_CONFIRMATION_REQUESTED",
  "USER_CONFIRMED",
  "USER_DECLINED",
  "INFO_REQUESTED",
  "EMPLOYEE_REPLIED",
  "ACTION_EXECUTED",
  "APPROVAL_REQUESTED",
  "APPROVAL_DECIDED",
  "TICKET_CREATED",
  "TICKET_STATUS_CHANGED",
  "ESCALATION_TRIGGERED",
  "HUMAN_INTERVENTION",
  "MEMORY_RETRIEVED",
  "MEMORY_WRITTEN",
  "SESSION_COMPLETED",
] as const;

/** Family colors — keep in sync with the session timeline page. */
const CHIP = {
  session: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300",
  ai: "bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-300",
  tool: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300",
  failure: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  retry: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  human: "bg-indigo-100 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-300",
  approval: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  ticket: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
};

const EVENT_CHIP: Record<string, string> = {
  SESSION_STARTED: CHIP.session,
  SESSION_COMPLETED: CHIP.session,
  SUPERVISOR_DECISION: CHIP.ai,
  AGENT_STARTED: CHIP.ai,
  AGENT_COMPLETED: CHIP.ai,
  HANDOFF_REQUESTED: CHIP.ai,
  HANDOFF_COMPLETED: CHIP.ai,
  MEMORY_RETRIEVED: CHIP.ai,
  MEMORY_WRITTEN: CHIP.ai,
  TOOL_CALLED: CHIP.tool,
  TOOL_SUCCEEDED: CHIP.tool,
  ACTION_EXECUTED: CHIP.tool,
  TOOL_FAILED: CHIP.failure,
  STRUCTURED_OUTPUT_FAILED: CHIP.failure,
  LOOP_GUARD_TRIGGERED: CHIP.failure,
  ESCALATION_TRIGGERED: CHIP.failure,
  STRUCTURED_OUTPUT_RETRY: CHIP.retry,
  USER_CONFIRMATION_REQUESTED: CHIP.human,
  USER_CONFIRMED: CHIP.human,
  USER_DECLINED: CHIP.human,
  INFO_REQUESTED: CHIP.human,
  EMPLOYEE_REPLIED: CHIP.human,
  HUMAN_INTERVENTION: CHIP.human,
  APPROVAL_REQUESTED: CHIP.approval,
  APPROVAL_DECIDED: CHIP.approval,
  TICKET_CREATED: CHIP.ticket,
  TICKET_STATUS_CHANGED: CHIP.ticket,
};

function eventLabel(type: string): string {
  return type.toLowerCase().replaceAll("_", " ");
}

function payloadPreview(payload: Record<string, unknown>): string {
  let json: string;
  try {
    json = JSON.stringify(payload);
  } catch {
    json = "{…}";
  }
  if (!json || json === "{}") return "—";
  return json.length > 80 ? `${json.slice(0, 80)}…` : json;
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function AuditPage() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();

  // Filters. Text inputs are debounced before triggering a refetch.
  const [eventType, setEventType] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [limit, setLimit] = useState(200);
  const [debounced, setDebounced] = useState({ sessionId: "", ticketId: "" });

  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [liveIds, setLiveIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const t = setTimeout(
      () => setDebounced({ sessionId: sessionId.trim(), ticketId: ticketId.trim() }),
      350
    );
    return () => clearTimeout(t);
  }, [sessionId, ticketId]);

  const load = useCallback(() => {
    setError(null);
    setEvents(null);
    const params = new URLSearchParams();
    if (eventType) params.set("event_type", eventType);
    if (debounced.sessionId) params.set("session_id", debounced.sessionId);
    if (debounced.ticketId) params.set("ticket_id", debounced.ticketId);
    params.set("limit", String(limit));
    api
      .get<{ events: AuditEvent[] }>(`/api/ops/audit?${params.toString()}`)
      .then((res) => {
        setEvents(res.events);
        setLiveIds(new Set());
      })
      .catch((e) => {
        if (isAuthError(e)) {
          router.push("/admin/login");
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to load audit events");
      });
  }, [eventType, debounced, limit, router]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Live-prepend firehose events that match the current filters.
  useOpsEvents((ev) => {
    if (eventType && ev.event_type !== eventType) return;
    if (debounced.sessionId && ev.session_id !== debounced.sessionId) return;
    if (debounced.ticketId && ev.ticket_id !== debounced.ticketId) return;
    setEvents((prev) => {
      if (prev === null) return prev; // initial load in flight
      if (prev.some((p) => p.id === ev.id)) return prev;
      return [ev, ...prev].slice(0, limit);
    });
    setLiveIds((prev) => new Set(prev).add(ev.id));
  });

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const loading = events === null && error === null;

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4">
        <h1 className="text-lg font-semibold tracking-tight">Audit log</h1>
        <p className="mt-0.5 text-sm text-muted">
          Persisted observability events — new events stream in live when they match your filters.
        </p>
      </div>

      <Card className="mb-4 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted">
            Event type
            <Select
              aria-label="Filter by event type"
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            >
              <option value="">All events</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex w-56 flex-col gap-1 text-xs text-muted">
            Session ID
            <Input
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              placeholder="ses_…"
              className="font-mono text-xs"
            />
          </label>
          <label className="flex w-56 flex-col gap-1 text-xs text-muted">
            Ticket ID
            <Input
              value={ticketId}
              onChange={(e) => setTicketId(e.target.value)}
              placeholder="tik_…"
              className="font-mono text-xs"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            Limit
            <Select
              aria-label="Result limit"
              value={String(limit)}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              <option value="50">50</option>
              <option value="200">200</option>
              <option value="500">500</option>
            </Select>
          </label>
          {events && (
            <span className="ml-auto pb-1.5 text-xs tabular-nums text-muted">
              {events.length} event{events.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </Card>

      {error && <ErrorState message={error} retry={load} />}

      {loading && (
        <Card className="p-4" aria-busy="true">
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        </Card>
      )}

      {events && events.length === 0 && (
        <Card>
          <EmptyState
            title="No events match these filters"
            hint="Try clearing the event type or ID filters, or raise the limit. New matching events will appear here live."
          />
        </Card>
      )}

      {events && events.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border-token text-left text-xs text-muted">
                <th className="w-8 px-2 py-2.5" aria-label="Expand" />
                <th className="px-3 py-2.5 font-medium">Time</th>
                <th className="px-3 py-2.5 font-medium">Event</th>
                <th className="px-3 py-2.5 font-medium">Actor</th>
                <th className="px-3 py-2.5 font-medium">Session</th>
                <th className="px-3 py-2.5 font-medium">Ticket</th>
                <th className="px-3 py-2.5 font-medium">Payload</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const isOpen = expanded.has(ev.id);
                const isLive = liveIds.has(ev.id);
                return (
                  <Fragment key={ev.id}>
                    <motion.tr
                      initial={reduceMotion || !isLive ? false : { opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={cx(
                        "border-b border-border-token",
                        isOpen ? "bg-surface-muted/60" : "hover:bg-surface-muted/40"
                      )}
                    >
                      <td className="px-2 py-2">
                        <button
                          onClick={() => toggleExpanded(ev.id)}
                          aria-expanded={isOpen}
                          aria-label={isOpen ? "Collapse payload" : "Expand payload"}
                          className="rounded-md p-1 text-muted hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
                        >
                          <svg
                            viewBox="0 0 16 16"
                            className={cx("h-3.5 w-3.5 transition-transform", isOpen && "rotate-90")}
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.8"
                            aria-hidden
                          >
                            <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs tabular-nums text-muted" title={ev.created_at}>
                        {formatDateTime(ev.created_at)}
                        {isLive && (
                          <span
                            className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-violet-500 align-middle"
                            title="Received live"
                            aria-label="Received live"
                          />
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <Badge className={EVENT_CHIP[ev.event_type] ?? CHIP.session}>
                          {eventLabel(ev.event_type)}
                        </Badge>
                      </td>
                      <td className="max-w-[10rem] truncate whitespace-nowrap px-3 py-2 font-mono text-xs" title={ev.actor}>
                        {ev.actor || <span className="text-muted">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                        {ev.session_id ? (
                          <Link
                            href={`/ops/sessions/${ev.session_id}`}
                            className="text-primary hover:underline"
                            title={ev.session_id}
                          >
                            {ev.session_id.slice(0, 10)}…
                          </Link>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs" title={ev.ticket_id ?? undefined}>
                        {ev.ticket_id ? `${ev.ticket_id.slice(0, 10)}…` : <span className="text-muted">—</span>}
                      </td>
                      <td className="max-w-md px-3 py-2">
                        <button
                          onClick={() => toggleExpanded(ev.id)}
                          className="block w-full truncate text-left font-mono text-xs text-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60 rounded"
                          title="Toggle full payload"
                        >
                          {payloadPreview(ev.payload)}
                        </button>
                      </td>
                    </motion.tr>
                    {isOpen && (
                      <tr className="border-b border-border-token bg-surface-muted/60">
                        <td />
                        <td colSpan={6} className="px-3 pb-3 pt-0">
                          <pre className="max-h-80 overflow-auto rounded-lg border border-border-token bg-surface p-3 font-mono text-xs leading-relaxed">
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </main>
  );
}
