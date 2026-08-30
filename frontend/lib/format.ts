/** Status → label/color maps and small formatting helpers. */

export const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  open: { label: "Open", className: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300" },
  pending: { label: "Pending", className: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  in_progress: { label: "In progress", className: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300" },
  waiting_approval: { label: "Waiting approval", className: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  resolved: { label: "Resolved", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300" },
  closed: { label: "Closed", className: "bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-400" },
  escalated: { label: "Escalated", className: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300" },
  active: { label: "Active", className: "bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-300" },
  waiting_employee: { label: "Waiting on employee", className: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  completed: { label: "Completed", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300" },
  failed: { label: "Failed", className: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300" },
  approved: { label: "Approved", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300" },
  rejected: { label: "Rejected", className: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300" },
  cancelled: { label: "Cancelled", className: "bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-400" },
  approval_pending: { label: "Approval pending", className: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  succeeded: { label: "Succeeded", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300" },
  started: { label: "Running", className: "bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-300" },
};

export const RISK_STYLES: Record<string, string> = {
  low: "bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-400",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  critical: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
};

export const AGENT_LABELS: Record<string, string> = {
  supervisor: "Supervisor",
  identity: "Identity & Access",
  endpoint: "Endpoint Support",
  network: "Network",
  security: "Security",
};

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const delta = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
