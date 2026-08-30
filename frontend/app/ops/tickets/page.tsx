"use client";

/** Command center — ticket queue. Dense filterable table over /api/ops/tickets.
 * All filters live in the URL search params so views are shareable. */
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  InputHTMLAttributes,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  Badge,
  Button,
  Drawer,
  EmptyState,
  ErrorState,
  Input,
  Select,
  Skeleton,
  Spinner,
  cx,
} from "@/components/ui";
import { api, isAuthError } from "@/lib/api";
import { AGENT_LABELS, STATUS_STYLES, formatDateTime, formatRelative } from "@/lib/format";
import type { Ticket, TicketDetail } from "@/lib/types";

const STATUS_OPTIONS = [
  "open",
  "pending",
  "in_progress",
  "waiting_approval",
  "resolved",
  "closed",
  "escalated",
] as const;

const CATEGORY_OPTIONS = ["identity", "endpoint", "network", "security", "ticketing", "other"] as const;

const AGENT_OPTIONS = [
  "supervisor",
  "identity",
  "endpoint",
  "network",
  "security",
  "dispatcher",
  "approval_workflow",
  "escalation_workflow",
] as const;

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "longest_pending", label: "Longest pending" },
  { value: "recently_updated", label: "Recently updated" },
];

/** Params that count as active filters (sort excluded). */
const FILTER_KEYS = [
  "status",
  "category",
  "team",
  "owner",
  "originating_agent",
  "security_related",
  "escalated",
  "approval_pending",
  "pending_over_threshold",
  "search",
  "created_after",
  "created_before",
] as const;

const PRIORITY_STYLES: Record<string, string> = {
  low: "text-muted",
  medium: "text-foreground",
  high: "text-amber-700 dark:text-amber-400",
  urgent: "text-red-600 dark:text-red-400",
  critical: "text-red-600 dark:text-red-400",
};

function agentLabel(key: string | null | undefined): string {
  if (!key) return "—";
  return AGENT_LABELS[key] ?? key.replace(/_/g, " ");
}

function statusBadge(status: string) {
  const s = STATUS_STYLES[status] ?? { label: status, className: undefined };
  return <Badge className={s.className}>{s.label}</Badge>;
}

function ShieldGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className={cx("h-4 w-4", className)} aria-hidden>
      <path
        fillRule="evenodd"
        d="M9.661 2.237a.531.531 0 0 1 .678 0 11.947 11.947 0 0 0 7.078 2.749.5.5 0 0 1 .479.425c.069.52.104 1.05.104 1.59 0 5.162-3.26 9.563-7.834 11.256a.48.48 0 0 1-.332 0C5.26 16.564 2 12.163 2 7c0-.538.035-1.069.104-1.589a.5.5 0 0 1 .48-.425 11.947 11.947 0 0 0 7.077-2.75Z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function FlagGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className={cx("h-4 w-4", className)} aria-hidden>
      <path d="M3.5 2.75a.75.75 0 0 0-1.5 0v14.5a.75.75 0 0 0 1.5 0v-4.392l1.657-.348a6.45 6.45 0 0 1 4.271.572 7.95 7.95 0 0 0 5.965.524l2.078-.64A.75.75 0 0 0 18 12.25v-8.5a.75.75 0 0 0-.904-.734l-2.38.501a7.25 7.25 0 0 1-4.186-.363l-.502-.2a8.75 8.75 0 0 0-5.053-.439L3.5 2.825V2.75Z" />
    </svg>
  );
}

/** Text input that commits its value to the URL after a 300ms pause. */
function DebouncedInput({
  value,
  onCommit,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: string;
  onCommit: (next: string) => void;
}) {
  const [text, setText] = useState(value);
  const lastCommitted = useRef(value);

  // Sync from the URL when it changes externally (e.g. Clear all).
  useEffect(() => {
    if (value !== lastCommitted.current) {
      lastCommitted.current = value;
      setText(value);
    }
  }, [value]);

  useEffect(() => {
    if (text === lastCommitted.current) return;
    const t = setTimeout(() => {
      lastCommitted.current = text;
      onCommit(text);
    }, 300);
    return () => clearTimeout(t);
  }, [text, onCommit]);

  return <Input {...rest} value={text} onChange={(e) => setText(e.target.value)} />;
}

function FilterCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-1.5 whitespace-nowrap rounded-lg border border-border-token bg-surface px-2.5 py-1.5 text-sm text-foreground hover:bg-surface-muted">
      <input
        type="checkbox"
        className="h-3.5 w-3.5 accent-indigo-600"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

function MetaItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function buildApiQuery(sp: URLSearchParams): string {
  const q = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = sp.get(key);
    if (v) q.set(key, v);
  }
  // A date-only "before" bound should include the whole selected day.
  const before = sp.get("created_before");
  if (before) q.set("created_before", `${before}T23:59:59`);
  const sort = sp.get("sort");
  if (sort) q.set("sort", sort);
  q.set("limit", "200");
  return q.toString();
}

function TicketsInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Ticket | null>(null);
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [note, setNote] = useState("");
  const [intervening, setIntervening] = useState<"takeover" | "resolve" | null>(null);
  const [interveneResult, setInterveneResult] = useState<string | null>(null);
  const [interveneError, setInterveneError] = useState<string | null>(null);

  const apiQuery = useMemo(() => buildApiQuery(new URLSearchParams(searchParams.toString())), [searchParams]);

  const seq = useRef(0);
  const load = useCallback(async () => {
    const mySeq = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<{ tickets: Ticket[] }>(`/api/ops/tickets?${apiQuery}`);
      if (seq.current !== mySeq) return;
      setTickets(res.tickets);
      setLoading(false);
    } catch (e) {
      if (isAuthError(e)) {
        router.push("/admin/login");
        return;
      }
      if (seq.current !== mySeq) return;
      setError(e instanceof Error ? e.message : "Failed to load tickets");
      setLoading(false);
    }
  }, [apiQuery, router]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const setParam = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(searchParams.toString());
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, pathname, router]
  );

  const activeFilterCount = FILTER_KEYS.filter((k) => searchParams.get(k)).length;

  // Drawer detail enrichment: the employee endpoint carries the description +
  // history; it 404s for tickets the operator did not request, so degrade
  // gracefully to the list-row fields.
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    api
      .get<TicketDetail>(`/api/tickets/${selected.ticket_number}`)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        /* detail restricted to requester — show list-row fields only */
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id, selected?.ticket_number]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectTicket = useCallback((ticket: Ticket | null) => {
    setDetail(null);
    setNote("");
    setInterveneResult(null);
    setInterveneError(null);
    setSelected(ticket);
  }, []);

  async function intervene(resolve: boolean) {
    if (!selected) return;
    setIntervening(resolve ? "resolve" : "takeover");
    setInterveneError(null);
    setInterveneResult(null);
    try {
      const res = await api.post<{ ok: boolean; status: string }>(
        `/api/ops/tickets/${selected.id}/intervene`,
        { note, resolve }
      );
      setSelected((prev) => (prev ? { ...prev, status: res.status } : prev));
      setInterveneResult(
        resolve
          ? "Ticket resolved — the requester has been notified."
          : "You have taken this ticket over — it is now in progress under your name."
      );
      setNote("");
      void load();
    } catch (e) {
      if (isAuthError(e)) {
        router.push("/admin/login");
        return;
      }
      setInterveneError(e instanceof Error ? e.message : "Intervention failed");
    } finally {
      setIntervening(null);
    }
  }

  const showSkeleton = loading && tickets === null;

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Tickets</h1>
          <p className="text-sm text-muted">
            Every ticket the agents have opened, with the levers to step in.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {loading && tickets !== null && <Spinner />}
          {tickets !== null && (
            <span className="text-xs tabular-nums text-muted">
              {tickets.length} ticket{tickets.length === 1 ? "" : "s"}
            </span>
          )}
          <Button variant="secondary" onClick={() => void load()} aria-label="Refresh tickets">
            Refresh
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="mb-4 rounded-xl border border-border-token bg-surface p-3">
        <div className="flex flex-wrap items-center gap-2">
          <DebouncedInput
            type="search"
            aria-label="Search tickets"
            placeholder="Search title, description, number, requester…"
            className="w-64 flex-none"
            value={searchParams.get("search") ?? ""}
            onCommit={(v) => setParam("search", v || null)}
          />
          <Select
            aria-label="Filter by status"
            value={searchParams.get("status") ?? ""}
            onChange={(e) => setParam("status", e.target.value || null)}
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {STATUS_STYLES[s]?.label ?? s}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Filter by category"
            value={searchParams.get("category") ?? ""}
            onChange={(e) => setParam("category", e.target.value || null)}
          >
            <option value="">All categories</option>
            {CATEGORY_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Filter by originating agent"
            value={searchParams.get("originating_agent") ?? ""}
            onChange={(e) => setParam("originating_agent", e.target.value || null)}
          >
            <option value="">All agents</option>
            {AGENT_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {agentLabel(a)}
              </option>
            ))}
          </Select>
          <DebouncedInput
            aria-label="Filter by team key"
            placeholder="Team key"
            className="w-32 flex-none"
            value={searchParams.get("team") ?? ""}
            onCommit={(v) => setParam("team", v || null)}
          />
          <DebouncedInput
            aria-label="Filter by owner id"
            placeholder="Owner id"
            className="w-32 flex-none"
            value={searchParams.get("owner") ?? ""}
            onCommit={(v) => setParam("owner", v || null)}
          />
          <FilterCheckbox
            label="Security"
            checked={searchParams.get("security_related") === "true"}
            onChange={(c) => setParam("security_related", c ? "true" : null)}
          />
          <FilterCheckbox
            label="Escalated"
            checked={searchParams.get("escalated") === "true"}
            onChange={(c) => setParam("escalated", c ? "true" : null)}
          />
          <FilterCheckbox
            label="Approval pending"
            checked={searchParams.get("approval_pending") === "true"}
            onChange={(c) => setParam("approval_pending", c ? "true" : null)}
          />
          <FilterCheckbox
            label="Pending &gt; 3d"
            checked={searchParams.get("pending_over_threshold") === "true"}
            onChange={(c) => setParam("pending_over_threshold", c ? "true" : null)}
          />
          <label className="inline-flex items-center gap-1.5 text-sm text-muted">
            From
            <Input
              type="date"
              aria-label="Created after"
              className="w-36 flex-none"
              value={searchParams.get("created_after") ?? ""}
              onChange={(e) => setParam("created_after", e.target.value || null)}
            />
          </label>
          <label className="inline-flex items-center gap-1.5 text-sm text-muted">
            To
            <Input
              type="date"
              aria-label="Created before"
              className="w-36 flex-none"
              value={searchParams.get("created_before") ?? ""}
              onChange={(e) => setParam("created_before", e.target.value || null)}
            />
          </label>
          <label className="inline-flex items-center gap-1.5 text-sm text-muted">
            Sort
            <Select
              aria-label="Sort tickets"
              value={searchParams.get("sort") ?? "newest"}
              onChange={(e) => setParam("sort", e.target.value === "newest" ? null : e.target.value)}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </label>
          {activeFilterCount > 0 && (
            <span className="ml-auto flex items-center gap-2">
              <Badge className="bg-indigo-100 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-300">
                {activeFilterCount} filter{activeFilterCount === 1 ? "" : "s"}
              </Badge>
              <Button variant="ghost" onClick={() => router.replace(pathname, { scroll: false })}>
                Clear all
              </Button>
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      {showSkeleton ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-9 w-full" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error} retry={() => void load()} />
      ) : tickets && tickets.length === 0 ? (
        <EmptyState
          title="No tickets match these filters"
          hint="Try clearing a filter, widening the date range, or removing the search term."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border-token bg-surface">
          <table className="w-full min-w-[1100px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-token bg-surface-muted/60 text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-3 py-2.5 font-medium">Number</th>
                <th className="px-3 py-2.5 font-medium">Requester</th>
                <th className="px-3 py-2.5 font-medium">Title</th>
                <th className="px-3 py-2.5 font-medium">Category</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Priority</th>
                <th className="px-3 py-2.5 font-medium">Owner / team</th>
                <th className="px-3 py-2.5 font-medium">Agent</th>
                <th className="px-3 py-2.5 text-right font-medium">Age</th>
                <th className="px-2 py-2.5 font-medium">
                  <span className="sr-only">Security</span>
                  <ShieldGlyph className="h-3.5 w-3.5 text-muted" />
                </th>
                <th className="px-2 py-2.5 font-medium">
                  <span className="sr-only">Escalated</span>
                  <FlagGlyph className="h-3.5 w-3.5 text-muted" />
                </th>
                <th className="px-3 py-2.5 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {(tickets ?? []).map((t) => (
                <tr
                  key={t.id}
                  tabIndex={0}
                  onClick={() => selectTicket(t)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      selectTicket(t);
                    }
                  }}
                  aria-label={`Open ticket ${t.ticket_number}`}
                  className="cursor-pointer border-b border-border-token/60 last:border-b-0 hover:bg-surface-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-400"
                >
                  <td className="px-3 py-2 font-mono text-xs text-foreground">{t.ticket_number}</td>
                  <td className="px-3 py-2 text-xs text-muted">{t.requester_employee_id ?? "—"}</td>
                  <td className="max-w-[300px] truncate px-3 py-2" title={t.title}>
                    {t.title}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted">{t.category}</td>
                  <td className="px-3 py-2">{statusBadge(t.status)}</td>
                  <td className="px-3 py-2">
                    <span className={cx("text-xs font-medium", PRIORITY_STYLES[t.priority] ?? "text-foreground")}>
                      {t.priority}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-muted">
                    {t.current_owner_id ?? "—"}
                    {t.current_team_key && (
                      <span className="text-muted/80"> · {t.current_team_key}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-xs font-medium text-ai">{agentLabel(t.originating_agent)}</span>
                  </td>
                  <td
                    className={cx(
                      "px-3 py-2 text-right text-xs tabular-nums",
                      t.pending_age_days !== null && t.pending_age_days > 3
                        ? "font-semibold text-amber-700 dark:text-amber-400"
                        : "text-muted"
                    )}
                  >
                    {t.pending_age_days !== null ? `${t.pending_age_days}d` : "—"}
                  </td>
                  <td className="px-2 py-2">
                    {t.security_related && (
                      <span title="Security related" aria-label="Security related" role="img">
                        <ShieldGlyph className="text-red-500" />
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {t.escalated && (
                      <span title="Escalated" aria-label="Escalated" role="img">
                        <FlagGlyph className="text-amber-600 dark:text-amber-400" />
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs tabular-nums text-muted">
                    {formatRelative(t.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail drawer */}
      <Drawer
        open={selected !== null}
        onClose={() => selectTicket(null)}
        title={
          selected ? (
            <span>
              <span className="font-mono text-xs text-muted">{selected.ticket_number}</span>{" "}
              {selected.title}
            </span>
          ) : (
            ""
          )
        }
        wide
      >
        {selected && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              {statusBadge(selected.status)}
              <Badge>
                <span className={PRIORITY_STYLES[selected.priority] ?? undefined}>
                  {selected.priority} priority
                </span>
              </Badge>
              {selected.security_related && (
                <Badge className="bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300">
                  Security
                </Badge>
              )}
              {selected.escalated && (
                <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                  Escalated
                </Badge>
              )}
            </div>

            {detail?.description ? (
              <section>
                <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
                  Description
                </h3>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                  {detail.description}
                </p>
              </section>
            ) : (
              <p className="text-xs text-muted">
                Full description is only exposed on the requester-facing API for this ticket.
              </p>
            )}

            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Details</h3>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
                <MetaItem label="Requester">{selected.requester_employee_id ?? "—"}</MetaItem>
                <MetaItem label="Category">{selected.category}</MetaItem>
                <MetaItem label="Originating agent">
                  <span className="text-ai">{agentLabel(selected.originating_agent)}</span>
                </MetaItem>
                <MetaItem label="Owner">{selected.current_owner_id ?? "Unassigned"}</MetaItem>
                <MetaItem label="Team">{selected.current_team_key ?? "—"}</MetaItem>
                <MetaItem label="Pending age">
                  {selected.pending_age_days !== null ? (
                    <span
                      className={cx(
                        "tabular-nums",
                        selected.pending_age_days > 3 &&
                          "font-semibold text-amber-700 dark:text-amber-400"
                      )}
                    >
                      {selected.pending_age_days} day{selected.pending_age_days === 1 ? "" : "s"}
                    </span>
                  ) : (
                    "—"
                  )}
                </MetaItem>
                <MetaItem label="Created">
                  <span className="tabular-nums">{formatDateTime(selected.created_at)}</span>
                </MetaItem>
                <MetaItem label="Updated">
                  <span className="tabular-nums">{formatDateTime(selected.updated_at)}</span>
                </MetaItem>
                <MetaItem label="Session">
                  {selected.session_id ? (
                    <Link
                      href={`/ops/sessions/${selected.session_id}`}
                      className="font-medium text-primary hover:underline"
                    >
                      Open session timeline
                    </Link>
                  ) : (
                    "—"
                  )}
                </MetaItem>
              </dl>
            </section>

            {detail && detail.history.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  Status history
                </h3>
                <ol className="space-y-1.5">
                  {detail.history.map((h, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-x-2 text-xs">
                      <span className="tabular-nums text-muted">{formatDateTime(h.at)}</span>
                      <span className="font-medium text-foreground">
                        {h.from_status ? `${h.from_status} → ${h.to_status}` : h.to_status}
                      </span>
                      <span className="text-muted">by {h.changed_by}</span>
                      {h.reason && <span className="text-muted">— {h.reason}</span>}
                    </li>
                  ))}
                </ol>
              </section>
            )}

            <section className="rounded-xl border border-border-token bg-surface-muted/50 p-4">
              <h3 className="mb-1 text-sm font-semibold text-foreground">Intervene</h3>
              <p className="mb-3 text-xs text-muted">
                Take the ticket out of the automation loop. Your note is relayed to the requester.
              </p>
              <div className="space-y-3">
                <Input
                  aria-label="Intervention note"
                  placeholder="Note for the requester (optional)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={intervening !== null}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => void intervene(false)}
                    disabled={intervening !== null}
                  >
                    {intervening === "takeover" ? <Spinner className="h-3.5 w-3.5" /> : null}
                    Take over
                  </Button>
                  <Button
                    variant="success"
                    onClick={() => void intervene(true)}
                    disabled={intervening !== null}
                  >
                    {intervening === "resolve" ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : null}
                    Resolve
                  </Button>
                </div>
                {interveneResult && (
                  <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400" role="status">
                    {interveneResult}
                  </p>
                )}
                {interveneError && (
                  <p className="text-sm font-medium text-red-600 dark:text-red-400" role="alert">
                    {interveneError}
                  </p>
                )}
              </div>
            </section>
          </div>
        )}
      </Drawer>
    </div>
  );
}

export default function OpsTicketsPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6" aria-hidden>
          <Skeleton className="mb-4 h-8 w-48" />
          <Skeleton className="mb-4 h-14 w-full" />
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        </div>
      }
    >
      <TicketsInner />
    </Suspense>
  );
}
