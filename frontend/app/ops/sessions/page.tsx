"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Card, ErrorState, Select, Skeleton } from "@/components/ui";
import { api, isAuthError } from "@/lib/api";
import type { OpsSession } from "@/lib/types";
import { formatRelative } from "@/lib/format";

export default function SessionsPage() {
  const router = useRouter(); const [status, setStatus] = useState(""); const [sessions, setSessions] = useState<OpsSession[] | null>(null); const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { setError(null); api.get<{ sessions: OpsSession[] }>(`/api/ops/sessions?limit=100${status ? `&status=${status}` : ""}`).then((result) => setSessions(result.sessions)).catch((cause) => { if (isAuthError(cause)) router.push("/admin/login"); else setError(cause instanceof Error ? cause.message : "Unable to load sessions."); }); }, [router, status]);
  useEffect(() => { const timer = window.setTimeout(load, 0); return () => window.clearTimeout(timer); }, [load]);
  return <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6"><div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-xl font-semibold tracking-tight">Live sessions</h1><p className="mt-1 text-sm text-muted">Open a session to inspect its persisted decisions, tools, and human handoffs.</p></div><label className="text-xs text-muted">Status<Select aria-label="Filter sessions by status" value={status} onChange={(event) => setStatus(event.target.value)} className="ml-2"><option value="">All</option><option value="active">Active</option><option value="waiting_employee">Waiting employee</option><option value="waiting_approval">Waiting approval</option><option value="completed">Completed</option><option value="escalated">Escalated</option><option value="failed">Failed</option></Select></label></div>{error ? <ErrorState message={error} retry={load} /> : !sessions ? <div className="space-y-2">{Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} className="h-14" />)}</div> : <Card className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-border-token text-left text-xs text-muted"><th className="px-4 py-3">Request</th><th className="px-4 py-3">Employee</th><th className="px-4 py-3">Channel</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Updated</th></tr></thead><tbody>{sessions.map((session) => <tr key={session.id} className="border-b border-border-token/60 last:border-0 hover:bg-surface-muted/60"><td className="max-w-lg px-4 py-3"><Link href={`/ops/sessions/${session.id}`} className="block truncate font-medium hover:text-primary hover:underline">{session.original_request}</Link></td><td className="px-4 py-3 font-mono text-xs">{session.employee_id}</td><td className="px-4 py-3 capitalize">{session.channel}</td><td className="px-4 py-3 capitalize">{session.status.replaceAll("_", " ")}</td><td className="px-4 py-3 text-muted">{formatRelative(session.updated_at)}</td></tr>)}</tbody></table></Card>}</main>;
}
