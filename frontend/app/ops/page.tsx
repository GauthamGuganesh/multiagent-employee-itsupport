"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Card, ErrorState, Skeleton } from "@/components/ui";
import { api, isAuthError } from "@/lib/api";
import type { OpsMetrics } from "@/lib/types";
import { useRouter } from "next/navigation";

const CARDS: { key: keyof OpsMetrics; label: string; href: string; tone: string }[] = [
  { key: "active_sessions", label: "Active sessions", href: "/ops/sessions", tone: "text-ai" },
  { key: "open_tickets", label: "Open tickets", href: "/ops/tickets", tone: "text-foreground" },
  { key: "pending_approvals", label: "Pending approvals", href: "/ops/approvals", tone: "text-amber-700 dark:text-amber-400" },
  { key: "escalated_tickets", label: "Escalated", href: "/ops/escalations", tone: "text-red-600 dark:text-red-400" },
  { key: "pending_over_threshold", label: "Pending over 3d", href: "/ops/tickets?pending_over_threshold=true", tone: "text-amber-700 dark:text-amber-400" },
  { key: "resolved_today", label: "Resolved today", href: "/ops/tickets?status=resolved", tone: "text-emerald-700 dark:text-emerald-400" },
  { key: "agent_failures", label: "Agent failures", href: "/ops/audit?event_type=STRUCTURED_OUTPUT_FAILED", tone: "text-red-600 dark:text-red-400" },
  { key: "loop_guard_activations", label: "Loop guards", href: "/ops/audit?event_type=LOOP_GUARD_TRIGGERED", tone: "text-red-600 dark:text-red-400" },
];

export default function OpsOverviewPage() {
  const router = useRouter();
  const [metrics, setMetrics] = useState<OpsMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    api.get<OpsMetrics>("/api/ops/metrics").then(setMetrics).catch((cause) => {
      if (isAuthError(cause)) router.push("/admin/login"); else setError(cause instanceof Error ? cause.message : "Unable to load operations metrics.");
    });
  }, [router]);
  useEffect(() => { const timer = window.setTimeout(load, 0); return () => window.clearTimeout(timer); }, [load]);
  return <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6"><div className="mb-6"><h1 className="text-xl font-semibold tracking-tight">Operations Command Center</h1><p className="mt-1 text-sm text-muted">Persisted activity across support, approvals, and human intervention.</p></div>{error ? <ErrorState message={error} retry={load} /> : !metrics ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} className="h-28" />)}</div> : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{CARDS.map((card) => <Link key={card.key} href={card.href}><Card className="p-4 transition-colors hover:bg-surface-muted"><p className="text-sm text-muted">{card.label}</p><p className={`mt-2 text-3xl font-semibold tabular-nums ${card.tone}`}>{metrics[card.key]}</p></Card></Link>)}</div>}</main>;
}
