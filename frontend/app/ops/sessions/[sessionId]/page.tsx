"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Card, ErrorState, Skeleton } from "@/components/ui";
import { api, isAuthError } from "@/lib/api";
import type { OpsTimeline, TimelineEntry } from "@/lib/types";
import { formatDateTime } from "@/lib/format";

function label(value: string | undefined | null) {
  return (value ?? "Activity").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function targetLabel(target: unknown) {
  const value = record(target);
  if (!value) return null;
  const name = typeof value.employee_name === "string" ? value.employee_name : null;
  const title = typeof value.employee_title === "string" ? value.employee_title : null;
  const team = typeof value.team_name === "string" ? value.team_name : null;
  if (!name) return team;
  return [name, title, team ? `${team} team` : null].filter(Boolean).join(" · ");
}

function eventCopy(entry: TimelineEntry): { title: string; body: string } {
  const payload = entry.payload ?? {};
  const event = entry.event_type;
  if (event === "SESSION_STARTED") {
    return { title: "Session started", body: "The employee's request was received and queued for triage." };
  }
  if (event === "SUPERVISOR_DECISION") {
    const decision = record(payload.decision);
    const route = typeof decision?.target_specialist === "string"
      ? `Routed to ${label(decision.target_specialist)}`
      : typeof decision?.workflow === "string"
        ? `Started ${label(decision.workflow)} workflow`
        : label(typeof decision?.decision === "string" ? decision.decision : null);
    const reason = typeof decision?.reason === "string" ? decision.reason : "";
    const cycle = typeof payload.cycle === "number" ? `Cycle ${payload.cycle}: ` : "";
    return {
      title: "Supervisor decision audit",
      body: `${cycle}${route}.${reason ? ` ${reason}` : ""} This is the persisted audit record for the supervisor run shown above.`,
    };
  }
  if (event === "AGENT_STARTED") {
    return { title: `${label(entry.actor)} investigation started`, body: "The specialist began its bounded evidence-gathering run." };
  }
  if (event === "AGENT_COMPLETED") {
    const result = record(payload.result);
    const outcome = typeof result?.outcome === "string" ? label(result.outcome) : "completed";
    return { title: `${label(entry.actor)} investigation ${outcome}`, body: "The specialist's structured result was saved for supervisor review." };
  }
  if (event === "TICKET_CREATED") {
    const number = typeof payload.ticket_number === "string" ? payload.ticket_number : "A support ticket";
    return { title: "Ticket created", body: `${number} was created with status ${String(payload.status ?? "open")}.` };
  }
  if (event === "ESCALATION_TRIGGERED") {
    const contact = targetLabel(payload.target) ?? "the appropriate support team";
    const reason = typeof payload.reason === "string" ? payload.reason : "Human intervention was required.";
    return { title: "Human escalation triggered", body: `Assigned to ${contact}. Reason: ${reason}` };
  }
  if (event === "SESSION_COMPLETED") {
    const response = typeof payload.final_response === "string" ? payload.final_response : null;
    return { title: "Session completed", body: response ?? `Final status: ${String(payload.terminal_status ?? "completed")}.` };
  }
  if (event === "STRUCTURED_OUTPUT_RETRY") {
    return { title: "Structured response retry", body: "The agent response did not validate, so the platform retried within its safe retry budget." };
  }
  if (event === "STRUCTURED_OUTPUT_FAILED") {
    return { title: "Structured response failed", body: "The agent exhausted its validation retries. The supervisor will choose a safe fallback." };
  }
  return { title: label(event), body: "Recorded in the operational audit trail." };
}

function Entry({ entry }: { entry: TimelineEntry }) {
  const presentation = entry.kind === "event" ? eventCopy(entry) : null;
  const title = presentation?.title ?? (entry.kind === "agent_run"
    ? `${label(entry.agent_name)} · ${label(entry.outcome ?? entry.status)}`
    : label(entry.tool_name));
  const body = presentation?.body ?? (entry.kind === "agent_run"
    ? entry.status === "failed"
      ? `${entry.failure_detail ?? "The specialist could not produce a usable structured result."}${entry.structured_output_retries ? ` Validation retries used: ${entry.structured_output_retries}.` : ""}`
      : entry.reasoning_summary
    : entry.error || (entry.status === "failed" ? "Tool call failed." : "Tool call completed."));
  return <li className="relative border-l border-border-token pb-5 pl-5 last:pb-0"><span className="absolute -left-1.5 top-1 h-3 w-3 rounded-full bg-primary" /><p className="text-xs text-muted">{entry.at ? formatDateTime(entry.at) : "—"}</p><p className="mt-0.5 text-sm font-medium">{title}</p>{body && <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted">{body}</p>}</li>;
}

export default function SessionTimelinePage() {
  const params = useParams<{ sessionId: string }>(); const router = useRouter(); const [data, setData] = useState<OpsTimeline | null>(null); const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { setError(null); api.get<OpsTimeline>(`/api/ops/sessions/${encodeURIComponent(params.sessionId)}/timeline`).then(setData).catch((cause) => { if (isAuthError(cause)) router.push("/admin/login"); else setError(cause instanceof Error ? cause.message : "Unable to load the session timeline."); }); }, [params.sessionId, router]);
  useEffect(() => { const timer = window.setTimeout(load, 0); return () => window.clearTimeout(timer); }, [load]);
  return <main className="mx-auto max-w-4xl px-4 py-6"><Link href="/ops/sessions" className="text-sm text-primary hover:underline">← Live sessions</Link>{error ? <ErrorState message={error} retry={load} /> : !data ? <div className="mt-5 space-y-2">{Array.from({ length: 7 }).map((_, index) => <Skeleton key={index} className="h-16" />)}</div> : <><section className="mt-4 mb-6"><h1 className="text-xl font-semibold tracking-tight">Session timeline</h1><p className="mt-1 text-sm text-muted">{data.session.original_request}</p></section><Card className="mb-4 p-4"><dl className="grid gap-3 text-sm sm:grid-cols-3"><div><dt className="text-xs text-muted">Employee</dt><dd className="font-mono">{data.session.employee_id}</dd></div><div><dt className="text-xs text-muted">Status</dt><dd className="capitalize">{data.session.status.replaceAll("_", " ")}</dd></div><div><dt className="text-xs text-muted">Risk</dt><dd className="capitalize">{data.session.risk_level ?? "—"}</dd></div></dl></Card><Card className="p-5"><ol>{data.timeline.map((entry, index) => <Entry key={`${entry.kind}-${entry.at}-${index}`} entry={entry} />)}</ol></Card></>}</main>;
}
