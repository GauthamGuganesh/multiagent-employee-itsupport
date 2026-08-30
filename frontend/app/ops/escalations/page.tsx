"use client";

/** Command center — escalations grouped by trigger family. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { api, isAuthError } from "@/lib/api";
import { useOpsEvents } from "@/lib/sse";
import type { Escalation } from "@/lib/types";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, cx } from "@/components/ui";
import { STATUS_STYLES, formatRelative } from "@/lib/format";

/* ------------------------------------------------------------------ */
/* Trigger families                                                    */
/* ------------------------------------------------------------------ */

type FamilyKey = "agent" | "limits" | "aging" | "other";

const FAMILY_OF: Record<string, FamilyKey> = {
  agent_recommendation: "agent",
  security: "agent",
  budget_exhausted: "limits",
  loop_guard: "limits",
  structured_output_failure: "limits",
  pending_age: "aging",
  out_of_scope: "other",
  infrastructure: "other",
};

const FAMILIES: {
  key: FamilyKey;
  title: string;
  hint: string;
  chip: string;
  dot: string;
}[] = [
  {
    key: "agent",
    title: "Agent recommended",
    hint: "The AI judged a human should take over (including security recommendations).",
    chip: "bg-indigo-100 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-300",
    dot: "bg-indigo-500",
  },
  {
    key: "limits",
    title: "Automation limits",
    hint: "Cycle budget exhausted, loop guard tripped, or structured output failed.",
    chip: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
    dot: "bg-red-500",
  },
  {
    key: "aging",
    title: "Aging",
    hint: "Tickets pending past the age threshold.",
    chip: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
    dot: "bg-amber-500",
  },
  {
    key: "other",
    title: "Other",
    hint: "Out-of-scope requests and infrastructure fail-safes.",
    chip: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300",
    dot: "bg-slate-400",
  },
];

const TRIGGER_LABELS: Record<string, string> = {
  agent_recommendation: "Agent recommendation",
  security: "Security",
  budget_exhausted: "Budget exhausted",
  loop_guard: "Loop guard",
  structured_output_failure: "Structured output",
  pending_age: "Pending age",
  out_of_scope: "Out of scope",
  infrastructure: "Infrastructure",
};

function familyOf(trigger: string): FamilyKey {
  return FAMILY_OF[trigger] ?? "other";
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function EscalationsPage() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [escalations, setEscalations] = useState<Escalation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .get<{ escalations: Escalation[] }>("/api/ops/escalations")
      .then((res) => setEscalations(res.escalations))
      .catch((e) => {
        if (isAuthError(e)) {
          router.push("/admin/login");
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to load escalations");
      });
  }, [router]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Refetch when a new escalation is broadcast on the ops firehose.
  useOpsEvents((ev) => {
    if (ev.event_type === "ESCALATION_TRIGGERED") load();
  });

  const loading = escalations === null && error === null;

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Escalations</h1>
          <p className="mt-0.5 text-sm text-muted">
            Every hand-off from automation to humans, grouped by what triggered it.
          </p>
        </div>
        <Button variant="secondary" onClick={load} disabled={loading}>
          Refresh
        </Button>
      </div>

      {error && <ErrorState message={error} retry={load} />}

      {loading && (
        <div className="space-y-4" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <Card key={i} className="p-4">
              <Skeleton className="mb-3 h-5 w-48" />
              <Skeleton className="mb-2 h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </Card>
          ))}
        </div>
      )}

      {escalations && escalations.length === 0 && (
        <Card>
          <EmptyState
            title="No escalations recorded"
            hint="When the AI hands a session or ticket to a human — by recommendation, automation limit, or ticket age — it will appear here."
          />
        </Card>
      )}

      {escalations && escalations.length > 0 && (
        <div className="space-y-6">
          {FAMILIES.map((family) => {
            const rows = escalations.filter((e) => familyOf(e.trigger) === family.key);
            if (rows.length === 0) return null;
            return (
              <section key={family.key} aria-label={family.title}>
                <div className="mb-2 flex items-baseline gap-2.5">
                  <span className={cx("h-2 w-2 self-center rounded-full", family.dot)} aria-hidden />
                  <h2 className="text-sm font-semibold">{family.title}</h2>
                  <span className="text-xs tabular-nums text-muted">{rows.length}</span>
                  <span className="hidden truncate text-xs text-muted sm:inline">— {family.hint}</span>
                </div>
                <Card className="overflow-x-auto">
                  <table className="w-full min-w-[860px] text-sm">
                    <thead>
                      <tr className="border-b border-border-token text-left text-xs text-muted">
                        <th className="px-4 py-2.5 font-medium">Trigger</th>
                        <th className="px-4 py-2.5 font-medium">Reason</th>
                        <th className="px-4 py-2.5 font-medium">Ticket</th>
                        <th className="px-4 py-2.5 font-medium">Status</th>
                        <th className="px-4 py-2.5 font-medium">Routed</th>
                        <th className="px-4 py-2.5 font-medium">When</th>
                        <th className="px-4 py-2.5 font-medium">Session</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((esc) => {
                        const status = esc.ticket_status ? STATUS_STYLES[esc.ticket_status] : null;
                        return (
                          <motion.tr
                            key={esc.id}
                            initial={reduceMotion ? false : { opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="border-b border-border-token align-top last:border-b-0"
                          >
                            <td className="px-4 py-3 whitespace-nowrap">
                              <Badge className={family.chip}>
                                {TRIGGER_LABELS[esc.trigger] ?? esc.trigger}
                              </Badge>
                            </td>
                            <td className="min-w-[16rem] max-w-md px-4 py-3 text-foreground">
                              {esc.reason || <span className="text-muted">—</span>}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              {esc.ticket_number ? (
                                <Link
                                  href={`/ops/tickets?search=${encodeURIComponent(esc.ticket_number)}`}
                                  className="font-mono text-xs text-primary hover:underline"
                                >
                                  {esc.ticket_number}
                                </Link>
                              ) : (
                                <span className="text-muted">—</span>
                              )}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              {status ? (
                                <Badge className={status.className}>{status.label}</Badge>
                              ) : esc.ticket_status ? (
                                <Badge>{esc.ticket_status}</Badge>
                              ) : (
                                <span className="text-muted">—</span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <span className="flex items-center gap-1.5 whitespace-nowrap font-mono text-xs">
                                <span className={esc.from_owner_id ? "" : "text-muted"}>
                                  {esc.from_owner_id ?? "unassigned"}
                                </span>
                                <span className="text-muted" aria-hidden>
                                  →
                                </span>
                                <span>
                                  {esc.to_target_id ??
                                    (esc.to_team_key ? (
                                      <Badge className="bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300 font-sans">
                                        {esc.to_team_key}
                                      </Badge>
                                    ) : (
                                      <span className="text-muted">unrouted</span>
                                    ))}
                                </span>
                              </span>
                            </td>
                            <td
                              className="px-4 py-3 whitespace-nowrap text-xs tabular-nums text-muted"
                              title={esc.created_at}
                            >
                              {formatRelative(esc.created_at)}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              {esc.session_id ? (
                                <Link
                                  href={`/ops/sessions/${esc.session_id}`}
                                  className="text-xs text-primary hover:underline"
                                >
                                  Open session
                                </Link>
                              ) : (
                                <span className="text-xs text-muted">—</span>
                              )}
                            </td>
                          </motion.tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Card>
              </section>
            );
          })}
        </div>
      )}
    </main>
  );
}
