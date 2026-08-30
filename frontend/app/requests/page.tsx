"use client";

/** Employee "My requests" — card list of the signed-in employee's tickets. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { api, isAuthError } from "@/lib/api";
import type { Ticket } from "@/lib/types";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { EmployeeHeader, useMe } from "@/components/shell";
import { STATUS_STYLES, formatRelative } from "@/lib/format";

const NEEDS_ATTENTION = new Set(["pending", "waiting_approval", "escalated"]);

function formatCategory(category: string): string {
  return category.replace(/_/g, " ");
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status];
  return <Badge className={style?.className}>{style?.label ?? status}</Badge>;
}

function TicketRow({ ticket, index }: { ticket: Ticket; index: number }) {
  const reduceMotion = useReducedMotion();
  const waitingDays =
    ticket.pending_age_days !== null && ticket.pending_age_days >= 1
      ? Math.floor(ticket.pending_age_days)
      : null;

  return (
    <motion.li
      initial={reduceMotion ? false : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, delay: Math.min(index, 8) * 0.03 }}
    >
      <Link
        href={`/requests/${ticket.ticket_number}`}
        className="block rounded-xl border border-border-token bg-surface px-4 py-3 transition-colors hover:border-indigo-300 hover:bg-surface-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:hover:border-indigo-500/50"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted tabular-nums">
                {ticket.ticket_number}
              </span>
              <StatusBadge status={ticket.status} />
              {ticket.escalated && ticket.status !== "escalated" && (
                <span className="text-xs font-medium text-red-600 dark:text-red-400">
                  Escalated
                </span>
              )}
            </div>
            <p className="truncate text-sm font-medium text-foreground">{ticket.title}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="bg-surface-muted text-muted capitalize">
                {formatCategory(ticket.category)}
              </Badge>
              {waitingDays !== null && (
                <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                  Waiting {waitingDays}d
                </Badge>
              )}
            </div>
          </div>
          <span className="shrink-0 text-xs text-muted tabular-nums">
            {formatRelative(ticket.updated_at)}
          </span>
        </div>
      </Link>
    </motion.li>
  );
}

function Section({ title, tickets }: { title: string; tickets: Ticket[] }) {
  if (tickets.length === 0) return null;
  return (
    <section aria-label={title} className="space-y-2.5">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
        {title}
        <span className="ml-1.5 font-normal tabular-nums">({tickets.length})</span>
      </h2>
      <ul className="space-y-2">
        {tickets.map((t, i) => (
          <TicketRow key={t.id} ticket={t} index={i} />
        ))}
      </ul>
    </section>
  );
}

export default function MyRequestsPage() {
  const router = useRouter();
  const me = useMe();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    setTickets(null);
    api
      .get<{ tickets: Ticket[] }>("/api/tickets/mine")
      .then((r) => setTickets(r.tickets))
      .catch((e) => {
        if (isAuthError(e)) {
          router.push("/login");
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to load your requests");
      });
  }, [router]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const grouped = useMemo(() => {
    if (!tickets) return null;
    const needsAttention = tickets.filter(
      (t) => NEEDS_ATTENTION.has(t.status) || t.escalated
    );
    const recent = tickets.filter((t) => !needsAttention.includes(t));
    return { needsAttention, recent };
  }, [tickets]);

  return (
    <>
      <EmployeeHeader employeeName={me?.profile?.name} />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
        <div className="mb-5">
          <h1 className="text-lg font-semibold tracking-tight">My requests</h1>
          <p className="text-sm text-muted">
            Everything you&apos;ve asked IT support for, and where it stands.
          </p>
        </div>

        {error ? (
          <Card>
            <ErrorState message={error} retry={load} />
          </Card>
        ) : grouped === null ? (
          <div className="space-y-2" aria-busy="true" aria-label="Loading requests">
            <Skeleton className="h-[88px]" />
            <Skeleton className="h-[88px]" />
            <Skeleton className="h-[88px]" />
          </div>
        ) : grouped.needsAttention.length === 0 && grouped.recent.length === 0 ? (
          <Card>
            <EmptyState
              title="No requests yet"
              hint="Ask for help on the Support tab — anything that needs tracking will show up here."
            />
          </Card>
        ) : (
          <div className="space-y-7">
            <Section title="Needs attention" tickets={grouped.needsAttention} />
            <Section title="Recent" tickets={grouped.recent} />
          </div>
        )}
      </main>
    </>
  );
}
