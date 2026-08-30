"use client";

import { useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";

import type { OrgGraph } from "@/lib/types";
import { Button, cx } from "@/components/ui";

type Employee = OrgGraph["employees"][number];

type PositionedEmployee = {
  employee: Employee;
  x: number;
  y: number;
};

type OrganizationGraphProps = {
  employees: Employee[];
  selectedTeam: string | null;
  focusedEmployeeIds: Set<string> | null;
  onEmployeeSelect: (employeeId: string) => void;
};

const NODE_WIDTH = 172;
const NODE_HEIGHT = 62;
const HORIZONTAL_STEP = 196;
const VERTICAL_STEP = 142;
const PADDING = 76;
const MIN_ZOOM = 0.18;
const MAX_ZOOM = 1.35;
const DEFAULT_ZOOM = 0.28;

function buildLayout(employees: Employee[]) {
  const byId = new Map(employees.map((employee) => [employee.id, employee]));
  const children = new Map<string, Employee[]>();
  const roots: Employee[] = [];

  for (const employee of employees) {
    const manager = employee.manager_id ? byId.get(employee.manager_id) : undefined;
    if (!manager || manager.id === employee.id) {
      roots.push(employee);
      continue;
    }
    const reports = children.get(manager.id) ?? [];
    reports.push(employee);
    children.set(manager.id, reports);
  }

  const byName = (a: Employee, b: Employee) => a.name.localeCompare(b.name);
  roots.sort(byName);
  children.forEach((reports) => reports.sort(byName));

  let leafIndex = 0;
  let deepestLevel = 0;
  const positions = new Map<string, PositionedEmployee>();

  function position(employee: Employee, depth: number): number {
    deepestLevel = Math.max(deepestLevel, depth);
    const reports = children.get(employee.id) ?? [];
    const reportCenters = reports.map((report) => position(report, depth + 1));
    const center =
      reportCenters.length > 0
        ? reportCenters.reduce((total, value) => total + value, 0) / reportCenters.length
        : PADDING + leafIndex++ * HORIZONTAL_STEP + NODE_WIDTH / 2;
    positions.set(employee.id, {
      employee,
      x: center - NODE_WIDTH / 2,
      y: PADDING + depth * VERTICAL_STEP,
    });
    return center;
  }

  roots.forEach((root) => position(root, 0));

  return {
    positions,
    children,
    width: Math.max(840, PADDING * 2 + Math.max(0, leafIndex - 1) * HORIZONTAL_STEP + NODE_WIDTH),
    height: PADDING * 2 + deepestLevel * VERTICAL_STEP + NODE_HEIGHT,
  };
}

function ZoomIcon({ direction }: { direction: "in" | "out" }) {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <circle cx="7" cy="7" r="4.25" />
      <path d="m10.25 10.25 3 3M5 7h4" strokeLinecap="round" />
      {direction === "in" && <path d="M7 5v4" strokeLinecap="round" />}
    </svg>
  );
}

function initialView(layout: ReturnType<typeof buildLayout>) {
  const topLevel = [...layout.positions.values()].filter((node) => node.y === PADDING);
  const center =
    topLevel.reduce((total, node) => total + node.x + NODE_WIDTH / 2, 0) /
    Math.max(topLevel.length, 1);
  // A centered executive layer makes the graph useful immediately; drag exposes every branch.
  return { x: 360 - center * DEFAULT_ZOOM, y: 22 };
}

export function OrganizationGraph({
  employees,
  selectedTeam,
  focusedEmployeeIds,
  onEmployeeSelect,
}: OrganizationGraphProps) {
  const layout = useMemo(() => buildLayout(employees), [employees]);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [offset, setOffset] = useState(() => initialView(layout));
  const drag = useRef<{ pointerId: number; x: number; y: number } | null>(null);

  const focused = focusedEmployeeIds !== null;
  const hasResults = !focused || focusedEmployeeIds.size > 0;

  function changeZoom(amount: number) {
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current + amount)));
  }

  function resetView() {
    setZoom(DEFAULT_ZOOM);
    setOffset(initialView(layout));
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault();
    const scale = event.deltaY < 0 ? 0.08 : -0.08;
    changeZoom(scale);
  }

  function beginPan(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function pan(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const x = event.clientX;
    const y = event.clientY;
    setOffset((current) => ({ x: current.x + x - drag.current!.x, y: current.y + y - drag.current!.y }));
    drag.current = { pointerId: event.pointerId, x, y };
  }

  function endPan(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId === event.pointerId) drag.current = null;
  }

  return (
    <div className="relative h-[38rem] overflow-hidden bg-slate-50/70 dark:bg-slate-950/30">
      <div
        className="absolute inset-0 cursor-grab touch-none active:cursor-grabbing"
        onPointerDown={beginPan}
        onPointerMove={pan}
        onPointerUp={endPan}
        onPointerCancel={endPan}
        onWheel={handleWheel}
        aria-label="Interactive organization reporting graph. Drag to pan and use the zoom controls to inspect people."
        role="application"
      >
        <svg
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="absolute left-0 top-0 overflow-visible"
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
            transformOrigin: "top left",
          }}
        >
          <defs>
            <pattern id="organization-grid" width="24" height="24" patternUnits="userSpaceOnUse">
              <path d="M 24 0 L 0 0 0 24" fill="none" stroke="currentColor" strokeWidth="0.5" className="text-slate-300/70 dark:text-slate-700/50" />
            </pattern>
          </defs>
          <rect width={layout.width} height={layout.height} fill="url(#organization-grid)" />

          {[...layout.positions.values()].map((node) => {
            if (!node.employee.manager_id) return null;
            const parent = layout.positions.get(node.employee.manager_id);
            if (!parent) return null;
            const muted = focused && !focusedEmployeeIds.has(node.employee.id);
            const middleY = node.y - 24;
            return (
              <path
                key={`${parent.employee.id}-${node.employee.id}`}
                d={`M ${parent.x + NODE_WIDTH / 2} ${parent.y + NODE_HEIGHT} V ${middleY} H ${node.x + NODE_WIDTH / 2} V ${node.y}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                className={cx(
                  muted ? "text-slate-300/40 dark:text-slate-700/35" : "text-slate-300 dark:text-slate-600"
                )}
              />
            );
          })}

          {[...layout.positions.values()].map(({ employee, x, y }) => {
            const inTeam = selectedTeam !== null && employee.team_key === selectedTeam;
            const match = focusedEmployeeIds?.has(employee.id) ?? false;
            const muted = focused && !match;
            return (
              <g
                key={employee.id}
                transform={`translate(${x} ${y})`}
                className={cx("outline-none", muted && "opacity-25")}
                role="button"
                tabIndex={0}
                aria-label={`Open ${employee.name}, ${employee.title}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onEmployeeSelect(employee.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onEmployeeSelect(employee.id);
                  }
                }}
              >
                <title>{`${employee.name} — ${employee.title}`}</title>
                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx="10"
                  className={cx(
                    "cursor-pointer stroke-1 transition-colors",
                    inTeam
                      ? "fill-indigo-100 stroke-indigo-400 dark:fill-indigo-500/25 dark:stroke-indigo-400"
                      : match
                        ? "fill-violet-100 stroke-violet-400 dark:fill-violet-500/25 dark:stroke-violet-400"
                        : "fill-white stroke-slate-300 dark:fill-slate-900 dark:stroke-slate-700"
                  )}
                />
                <circle
                  cx="18"
                  cy="19"
                  r="7"
                  className={cx(
                    inTeam
                      ? "fill-indigo-500"
                      : match
                        ? "fill-violet-500"
                        : "fill-slate-400 dark:fill-slate-500"
                  )}
                />
                <text x="31" y="22" className="fill-slate-900 text-[11px] font-semibold dark:fill-slate-100">
                  {employee.name}
                </text>
                <text x="12" y="42" className="fill-slate-500 text-[9px] dark:fill-slate-400">
                  {employee.title.length > 27 ? `${employee.title.slice(0, 26)}…` : employee.title}
                </text>
                <text x="12" y="55" className="fill-slate-400 text-[8px] font-mono dark:fill-slate-500">
                  {employee.team_name ?? employee.id}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {!hasResults && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-surface/75 p-6 text-center backdrop-blur-[1px]">
          <div>
            <p className="text-sm font-medium">Nobody matches that search</p>
            <p className="mt-1 text-sm text-muted">Search names, titles, or employee IDs.</p>
          </div>
        </div>
      )}

      <div className="absolute bottom-3 left-3 flex items-center gap-1 rounded-lg border border-border-token bg-surface/95 p-1 shadow-sm backdrop-blur">
        <Button variant="ghost" className="h-8 w-8 p-0" onClick={() => changeZoom(-0.1)} aria-label="Zoom out">
          <ZoomIcon direction="out" />
        </Button>
        <span className="min-w-12 text-center text-xs tabular-nums text-muted">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" className="h-8 w-8 p-0" onClick={() => changeZoom(0.1)} aria-label="Zoom in">
          <ZoomIcon direction="in" />
        </Button>
        <span className="mx-1 h-4 w-px bg-border-token" />
        <Button variant="ghost" className="h-8 px-2 text-xs" onClick={resetView}>
          Reset view
        </Button>
      </div>
      <p className="pointer-events-none absolute bottom-4 right-4 rounded-md bg-surface/85 px-2 py-1 text-xs text-muted shadow-sm backdrop-blur">
        Drag to pan · scroll to zoom · select a person for details
      </p>
    </div>
  );
}
