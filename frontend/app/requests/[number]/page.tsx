"use client";

/** Employee ticket detail — status, description, approvals, history timeline. */
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { api, ApiError, isAuthError } from "@/lib/api";
import type { TicketDetail } from "@/lib/types";
import { Badge, Card, EmptyState, ErrorState, Skeleton, cx } from "@/components/ui";
import { EmployeeHeader, useMe } from "@/components/shell";
import { AGENT_LABELS, RISK_STYLES, STATUS_STYLES, formatDateTime } from "@/lib/format";

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status];
  return <Badge className={style?.className}>{style?.label ?? status}</Badge>;
}

function actorLabel(actor: string): string {
  return AGENT_LABELS[actor] ?? actor;
}

function BackLink() {
  return (
    <Link
      href="/requests"
      className="inline-flex items-center gap-1 rounded-md text-sm text-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
    >
      <span aria-hidden>←</span> Back to My requests
    </Link>
  );
}

function HistoryTimeline({ history }: { history: TicketDetail["history"] }) {
  if (history.length === 0) {
    return <p className="text-sm text-muted">No status changes recorded yet.</p>;
  }
  return (
    <ol className="space-y-0">
      {history.map((h, i) => {
        const isLast = i === history.length - 1;
        return (
          <li key={`${h.at}-${i}`} className="relative pl-6 pb-5 last:pb-0">
            {!isLast && (
              <span
                aria-hidden
                className="absolute left-[5px] top-4 bottom-0 w-px bg-border-token"
              />
            )}
            <span
              aria-hidden
              className={cx(
                "absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full border-2 border-surface",
                isLast ? "bg-primary" : "bg-slate-300 dark:bg-slate-600"
              )}
            />
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={h.to_status} />
              <span className="text-xs text-muted tabular-nums">{formatDateTime(h.at)}</span>
            </div>
            {h.reason && <p className="mt-1 text-sm text-foreground">{h.reason}</p>}
            <p className="mt-0.5 text-xs text-muted">by {actorLabel(h.changed_by)}</p>
          </li>
        );
      })}
    </ol>
  );
}

export default function RequestDetailPage() {
  const router = useRouter();
  const params = useParams<{ number: string }>();
  const ticketNumber = decodeURIComponent(params.number);
  const me = useMe();
  const reduceMotion = useReducedMotion();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    setNotFound(false);
    setTicket(null);
    api
      .get<TicketDetail>(`/api/tickets/${encodeURIComponent(ticketNumber)}`)
      .then(setTicket)
      .catch((e) => {
        if (isAuthError(e)) {
          router.push("/login");
          return;
        }
        if (e instanceof ApiError && e.status === 404) {
          setNotFound(true);
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to load this request");
      });
  }, [router, ticketNumber]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const waitingLong =
    ticket !== null &&
    (ticket.status === "pending" || ticket.status === "waiting_approval") &&
    ticket.pending_age_days !== null &&
    ticket.pending_age_days > 3;

  return (
    <>
      <EmployeeHeader employeeName={me?.profile?.name} />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
        <div className="mb-4">
          <BackLink />
        </div>

        {error ? (
          <Card>
            <ErrorState message={error} retry={load} />
          </Card>
        ) : notFound ? (
          <Card>
            <EmptyState
              title="We couldn't find that request"
              hint={`No request numbered ${ticketNumber} is linked to your account. It may have been removed, or the link may be out of date.`}
            />
            <div className="pb-8 text-center">
              <BackLink />
            </div>
          </Card>
        ) : ticket === null ? (
          <div className="space-y-4" aria-busy="true" aria-label="Loading request">
            <Skeleton className="h-24" />
            <Skeleton className="h-32" />
            <Skeleton className="h-48" />
          </div>
        ) : (
          <motion.div
            initial={reduceMotion ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-4"
          >
            {/* Header */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm text-muted tabular-nums">
                  {ticket.ticket_number}
                </span>
                <StatusBadge status={ticket.status} />
                {ticket.escalated && ticket.status !== "escalated" && (
                  <span className="text-xs font-medium text-red-600 dark:text-red-400">
                    Escalated
                  </span>
                )}
              </div>
              <h1 className="text-lg font-semibold tracking-tight">{ticket.title}</h1>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={RISK_STYLES[ticket.priority]}>
                  <span className="capitalize">{ticket.priority}</span>&nbsp;priority
                </Badge>
                <Badge className="bg-surface-muted text-muted capitalize">
                  {ticket.category.replace(/_/g, " ")}
                </Badge>
                <span className="text-xs text-muted tabular-nums">
                  Opened {formatDateTime(ticket.created_at)} · Updated{" "}
                  {formatDateTime(ticket.updated_at)}
                </span>
              </div>
            </div>

            {waitingLong && (
              <div
                role="status"
                className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
              >
                This has been waiting longer than usual — it has been flagged for
                escalation.
              </div>
            )}

            {/* Description */}
            <Card className="p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                Description
              </h2>
              <p className="whitespace-pre-wrap text-sm text-foreground">
                {ticket.description || "No description provided."}
              </p>
            </Card>

            {/* Approvals */}
            {ticket.approvals.length > 0 && (
              <Card className="p-4">
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">
                  Approvals
                </h2>
                <ul className="divide-y divide-border-token">
                  {ticket.approvals.map((a) => (
                    <li key={a.id} className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
                      <div className="min-w-0 space-y-1">
                        <p className="text-sm text-foreground">{a.action_summary}</p>
                        <p className="text-xs text-muted">
                          Approver: <span className="font-mono">{a.approver_employee_id}</span>
                          {" · "}
                          {a.decided_at
                            ? `Decided ${formatDateTime(a.decided_at)}`
                            : "Awaiting decision"}
                        </p>
                      </div>
                      <StatusBadge status={a.status} />
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {/* History */}
            <Card className="p-4">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">
                History
              </h2>
              <HistoryTimeline history={ticket.history} />
            </Card>
          </motion.div>
        )}
      </main>
    </>
  );
}
