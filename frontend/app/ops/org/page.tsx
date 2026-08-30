"use client";

/** Command center — organization explorer: reporting graph, teams, systems. */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiError, isAuthError } from "@/lib/api";
import type { OrgGraph } from "@/lib/types";
import { OrganizationGraph } from "@/components/organization-graph";
import {
  Badge,
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
  cx,
} from "@/components/ui";

type Employee = OrgGraph["employees"][number];
type Team = OrgGraph["teams"][number];
type System = OrgGraph["systems"][number];

interface EmployeeContext {
  name: string;
  email: string;
  title: string;
  location: string | null;
  remote: boolean | null;
  team: { key: string; name: string } | null;
  department: { key: string; name: string } | null;
  roles: string[];
  manager: { id: string; name: string } | null;
}

const TEAM_CHIP = "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300";

export default function OrgPage() {
  const router = useRouter();
  const [graph, setGraph] = useState<OrgGraph | null>(null);
  const [error, setError] = useState<{ kind: "unavailable" | "other"; message: string } | null>(null);

  // Panel linking + graph focus state.
  const [selectedTeam, setSelectedTeam] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  // Employee drawer state.
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [drawerCtx, setDrawerCtx] = useState<EmployeeContext | null>(null);
  const [drawerError, setDrawerError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    setGraph(null);
    api
      .get<OrgGraph>("/api/ops/org/graph")
      .then(setGraph)
      .catch((e) => {
        if (isAuthError(e)) {
          router.push("/admin/login");
          return;
        }
        if (e instanceof ApiError && e.status === 503) {
          setError({
            kind: "unavailable",
            message: "Organization directory unavailable — is Neo4j running?",
          });
        } else {
          setError({
            kind: "other",
            message: e instanceof Error ? e.message : "Failed to load organization graph",
          });
        }
      });
  }, [router]);

  useEffect(() => {
    // Schedule the initial request after mount so state updates happen in the async callback.
    const request = window.setTimeout(load, 0);
    return () => window.clearTimeout(request);
  }, [load]);

  const teamNames = useMemo(() => {
    const m = new Map<string, string>();
    graph?.teams.forEach((t) => m.set(t.key, t.name));
    return m;
  }, [graph]);

  const memberCounts = useMemo(() => {
    const m = new Map<string, number>();
    graph?.employees.forEach((e) => {
      if (e.team_key) m.set(e.team_key, (m.get(e.team_key) ?? 0) + 1);
    });
    return m;
  }, [graph]);

  const teamsByDepartment = useMemo(() => {
    const groups = new Map<string, Team[]>();
    graph?.teams.forEach((t) => {
      const list = groups.get(t.department_name) ?? [];
      list.push(t);
      groups.set(t.department_name, list);
    });
    return [...groups.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([dept, teams]) => ({
        dept,
        teams: teams.sort((a, b) => a.name.localeCompare(b.name)),
      }));
  }, [graph]);

  /** When searching, show matches plus every ancestor so the chain reads. */
  const visibleIds = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !graph) return null;
    const byId = new Map(graph.employees.map((e) => [e.id, e]));
    const visible = new Set<string>();
    for (const e of graph.employees) {
      const hit =
        e.name.toLowerCase().includes(q) ||
        e.title.toLowerCase().includes(q) ||
        e.id.toLowerCase().includes(q);
      if (!hit) continue;
      let cur: Employee | undefined = e;
      while (cur && !visible.has(cur.id)) {
        visible.add(cur.id);
        cur = cur.manager_id ? byId.get(cur.manager_id) : undefined;
      }
    }
    return visible;
  }, [query, graph]);

  function selectTeam(key: string | null) {
    setSelectedTeam((prev) => (prev === key ? null : key));
  }

  const openEmployee = useCallback(
    (id: string) => {
      setDrawerId(id);
      setDrawerCtx(null);
      setDrawerError(null);
      api
        .get<EmployeeContext>(`/api/ops/org/employee/${id}`)
        .then(setDrawerCtx)
        .catch((e) => {
          if (isAuthError(e)) {
            router.push("/admin/login");
            return;
          }
          setDrawerError(
            e instanceof ApiError && e.status === 503
              ? "Organization directory unavailable — is Neo4j running?"
              : e instanceof Error
                ? e.message
                : "Failed to load employee"
          );
        });
    },
    [router]
  );

  const loading = graph === null && error === null;

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Organization</h1>
          <p className="mt-0.5 text-sm text-muted">
            Reporting lines, teams, and the systems they own — straight from the directory graph.
          </p>
        </div>
        {graph && (
          <p className="text-xs tabular-nums text-muted">
            {graph.employees.length} people · {graph.teams.length} teams · {graph.systems.length}{" "}
            systems
          </p>
        )}
      </div>

      {error && (
        <Card>
          <ErrorState message={error.message} retry={load} />
        </Card>
      )}

      {loading && (
        <div className="grid gap-4 lg:grid-cols-3" aria-busy="true">
          <Card className="p-4 lg:col-span-2">
            <Skeleton className="mb-3 h-5 w-40" />
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="mb-2 h-8 w-full" />
            ))}
          </Card>
          <div className="space-y-4">
            <Card className="p-4">
              <Skeleton className="mb-3 h-5 w-24" />
              <Skeleton className="mb-2 h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </Card>
            <Card className="p-4">
              <Skeleton className="mb-3 h-5 w-24" />
              <Skeleton className="mb-2 h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </Card>
          </div>
        </div>
      )}

      {graph && (
        <div className="grid items-start gap-4 lg:grid-cols-3">
          {/* ------------------------ Reporting graph ------------------------ */}
          <Card className="lg:col-span-2">
            <div className="flex flex-wrap items-center gap-2 border-b border-border-token px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">Reporting graph</h2>
                <p className="mt-0.5 text-xs text-muted">Connected reporting lines from the live directory.</p>
              </div>
              <div className="ml-auto flex items-center gap-2">
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Find a person…"
                  aria-label="Find a person in the reporting graph"
                  className="w-44 py-1.5 text-xs"
                />
                {query && (
                  <Button variant="ghost" className="px-2 py-1.5 text-xs" onClick={() => setQuery("")}>
                    Clear focus
                  </Button>
                )}
              </div>
            </div>
            {selectedTeam && (
              <div className="flex items-center gap-2 border-b border-border-token bg-indigo-50/60 px-4 py-2 text-xs dark:bg-indigo-500/10">
                <span className="text-muted">Highlighting members of</span>
                <Badge className="bg-indigo-100 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-300">
                  {teamNames.get(selectedTeam) ?? selectedTeam}
                </Badge>
                <button
                  onClick={() => setSelectedTeam(null)}
                  className="ml-auto rounded-md px-1.5 py-0.5 text-muted hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
                >
                  Clear
                </button>
              </div>
            )}
            {graph.employees.length === 0 ? (
              <EmptyState
                title="No employees in the directory"
                hint="Seed the organization graph to populate the reporting graph."
              />
            ) : (
              <OrganizationGraph
                employees={graph.employees}
                selectedTeam={selectedTeam}
                focusedEmployeeIds={visibleIds}
                onEmployeeSelect={openEmployee}
              />
            )}
          </Card>

          <div className="space-y-4">
            {/* ---------------------------- Teams ---------------------------- */}
            <Card>
              <div className="border-b border-border-token px-4 py-3">
                <h2 className="text-sm font-semibold">Teams</h2>
                <p className="mt-0.5 text-xs text-muted">
                  Grouped by department — select a team to highlight its members.
                </p>
              </div>
              <div className="max-h-72 overflow-y-auto p-2">
                {teamsByDepartment.length === 0 ? (
                  <EmptyState title="No teams" hint="The directory has no team nodes yet." />
                ) : (
                  teamsByDepartment.map(({ dept, teams }) => (
                    <div key={dept} className="mb-2 last:mb-0">
                      <p className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted">
                        {dept}
                      </p>
                      <ul className="m-0 list-none p-0">
                        {teams.map((t) => (
                          <li key={t.key}>
                            <button
                              onClick={() => selectTeam(t.key)}
                              aria-pressed={selectedTeam === t.key}
                              className={cx(
                                "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60",
                                selectedTeam === t.key
                                  ? "bg-indigo-50 text-indigo-900 dark:bg-indigo-500/10 dark:text-indigo-200"
                                  : "hover:bg-surface-muted/60"
                              )}
                            >
                              <span className="truncate">{t.name}</span>
                              <span className="font-mono text-xs text-muted">{t.key}</span>
                              <span className="ml-auto text-xs tabular-nums text-muted">
                                {memberCounts.get(t.key) ?? 0}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))
                )}
              </div>
            </Card>

            {/* --------------------------- Systems --------------------------- */}
            <Card>
              <div className="border-b border-border-token px-4 py-3">
                <h2 className="text-sm font-semibold">Systems</h2>
                <p className="mt-0.5 text-xs text-muted">
                  Who owns and supports each system — team chips link to the graph.
                </p>
              </div>
              <div className="max-h-80 overflow-y-auto p-2">
                {graph.systems.length === 0 ? (
                  <EmptyState title="No systems" hint="The directory has no system nodes yet." />
                ) : (
                  <ul className="m-0 list-none p-0">
                    {[...graph.systems]
                      .sort((a, b) => a.name.localeCompare(b.name))
                      .map((s: System) => (
                        <li
                          key={s.key}
                          className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2 py-2 hover:bg-surface-muted/40"
                        >
                          <span className="text-sm font-medium">{s.name}</span>
                          <span className="font-mono text-xs text-muted">{s.key}</span>
                          {s.category && <Badge className={TEAM_CHIP}>{s.category}</Badge>}
                          <span className="ml-auto flex items-center gap-1.5">
                            {s.owner_team_key && (
                              <button
                                onClick={() => selectTeam(s.owner_team_key)}
                                title={`Owner: ${teamNames.get(s.owner_team_key) ?? s.owner_team_key}`}
                                className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
                              >
                                <Badge className="bg-indigo-100 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-300">
                                  owns · {teamNames.get(s.owner_team_key) ?? s.owner_team_key}
                                </Badge>
                              </button>
                            )}
                            {s.support_team_key && (
                              <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300">
                                support · {s.support_team_key}
                              </Badge>
                            )}
                          </span>
                        </li>
                      ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ------------------------- Employee drawer ------------------------- */}
      <Drawer
        open={drawerId !== null}
        onClose={() => setDrawerId(null)}
        title={drawerCtx?.name ?? drawerId ?? "Employee"}
      >
        {drawerError ? (
          <ErrorState message={drawerError} retry={() => drawerId && openEmployee(drawerId)} />
        ) : drawerCtx === null ? (
          <div className="space-y-3" aria-busy="true">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <div className="space-y-5">
            <div>
              <p className="text-base font-semibold">{drawerCtx.name}</p>
              <p className="text-sm text-muted">{drawerCtx.title}</p>
              <p className="mt-1 font-mono text-xs text-muted">{drawerId}</p>
            </div>
            <dl className="grid grid-cols-[7rem_1fr] gap-y-2.5 text-sm">
              <dt className="text-muted">Email</dt>
              <dd className="break-all">{drawerCtx.email || "—"}</dd>
              <dt className="text-muted">Team</dt>
              <dd>
                {drawerCtx.team ? (
                  <span className="inline-flex items-center gap-1.5">
                    {drawerCtx.team.name}
                    <span className="font-mono text-xs text-muted">{drawerCtx.team.key}</span>
                  </span>
                ) : (
                  "—"
                )}
              </dd>
              <dt className="text-muted">Department</dt>
              <dd>{drawerCtx.department?.name ?? "—"}</dd>
              <dt className="text-muted">Location</dt>
              <dd>
                {drawerCtx.location ?? "—"}
                {drawerCtx.remote ? <span className="ml-1.5 text-xs text-muted">(remote)</span> : null}
              </dd>
              <dt className="text-muted">Manager</dt>
              <dd>
                {drawerCtx.manager ? (
                  <button
                    onClick={() => openEmployee(drawerCtx.manager!.id)}
                    className="text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60 rounded"
                  >
                    {drawerCtx.manager.name}
                  </button>
                ) : (
                  "— (top of the reporting tree)"
                )}
              </dd>
            </dl>
            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Roles</p>
              {drawerCtx.roles.length === 0 ? (
                <p className="text-sm text-muted">No roles assigned.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {drawerCtx.roles.map((role) => (
                    <Badge key={role} className={TEAM_CHIP}>
                      {role}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </main>
  );
}
