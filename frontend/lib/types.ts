/** API types mirroring the FastAPI backend's JSON responses. */

export type PendingInteraction =
  | { type: "question"; question: string }
  | {
      type: "confirmation";
      confirmation_id: string;
      action_summary: string;
      risk_level: "low" | "medium" | "high" | "critical";
    };

export interface ChatResult {
  session_id: string;
  pending: PendingInteraction | null;
  terminal_status: "resolved" | "approval_pending" | "escalated" | "failed" | null;
  final_response: string | null;
  assistant_message: string | null;
  ticket_number: string | null;
  approval_id: string | null;
  error?: string;
}

export interface ChatMessage {
  role: "employee" | "assistant" | "system";
  content: string;
  source: string;
  at: string;
}

export interface SessionDetail {
  id: string;
  status: string;
  terminal_status: string | null;
  original_request: string;
  pending: PendingInteraction | null;
  messages: ChatMessage[];
}

export interface SessionSummary {
  id: string;
  channel: "web" | "voice";
  status: string;
  terminal_status: string | null;
  original_request: string;
  category: string | null;
  created_at: string;
  updated_at: string;
}

export interface DirectoryEmployee {
  id: string;
  name: string;
  title: string;
  team_key: string | null;
  team_name: string | null;
}

export interface Profile {
  name?: string;
  email?: string;
  title?: string;
  team?: { key: string; name: string } | null;
  department?: { key: string; name: string } | null;
  roles?: string[];
  manager?: { id: string; name: string } | null;
}

export interface Ticket {
  id: string;
  ticket_number: string;
  title: string;
  category: string;
  status: string;
  priority: string;
  security_related: boolean;
  escalated: boolean;
  pending_age_days: number | null;
  current_owner_id: string | null;
  current_team_key: string | null;
  created_at: string;
  updated_at: string;
  session_id?: string | null;
  requester_employee_id?: string;
  originating_agent?: string | null;
}

export interface TicketDetail extends Ticket {
  description: string;
  history: {
    from_status: string | null;
    to_status: string;
    changed_by: string;
    reason: string;
    at: string;
  }[];
  approvals: {
    id: string;
    approver_employee_id: string;
    action_summary: string;
    status: string;
    decided_at: string | null;
  }[];
}

export interface OpsMetrics {
  active_sessions: number;
  resolved_today: number;
  open_tickets: number;
  pending_approvals: number;
  escalated_tickets: number;
  pending_over_threshold: number;
  human_interventions: number;
  agent_failures: number;
  loop_guard_activations: number;
  structured_output_failures: number;
}

export interface OpsSession {
  id: string;
  employee_id: string;
  channel: string;
  status: string;
  terminal_status: string | null;
  original_request: string;
  category: string | null;
  intent: string | null;
  risk_level: string | null;
  autonomy_level: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineEntry {
  kind: "event" | "agent_run" | "tool_call";
  at: string | null;
  // event
  event_type?: string;
  actor?: string;
  payload?: Record<string, unknown>;
  // agent_run
  agent_name?: string;
  run_index?: number;
  status?: string;
  outcome?: string | null;
  confidence?: number | null;
  reasoning_summary?: string;
  findings?: unknown[] | null;
  tools_used?: string[] | null;
  handoff_target?: string | null;
  structured_output_retries?: number;
  loop_guard_triggered?: boolean;
  failure_type?: string | null;
  failure_detail?: string | null;
  result?: Record<string, unknown> | null;
  memories_retrieved?: unknown[] | null;
  memories_written?: unknown[] | null;
  completed_at?: string | null;
  // tool_call
  tool_name?: string;
  request?: Record<string, unknown> | null;
  response?: Record<string, unknown> | null;
  error?: string | null;
  duration_ms?: number | null;
}

export interface OpsTimeline {
  session: OpsSession & { final_response: string | null };
  timeline: TimelineEntry[];
}

export interface Approval {
  id: string;
  ticket_id: string | null;
  ticket_number: string | null;
  session_id: string | null;
  requester_employee_id: string;
  approver_employee_id: string;
  privilege_key: string;
  system_key: string | null;
  action_summary: string;
  action_key: string | null;
  risk_level: string;
  status: string;
  decision_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface Escalation {
  id: string;
  ticket_id: string | null;
  ticket_number: string | null;
  ticket_status: string | null;
  session_id: string | null;
  reason: string;
  trigger: string;
  from_owner_id: string | null;
  to_target_id: string | null;
  to_team_key: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  session_id: string | null;
  ticket_id: string | null;
  event_type: string;
  actor: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AgentRunRow {
  id: string;
  session_id: string;
  agent_name: string;
  run_index: number;
  status: string;
  outcome: string | null;
  confidence: number | null;
  reasoning_summary: string;
  handoff_target: string | null;
  structured_output_retries: number;
  loop_guard_triggered: boolean;
  failure_type: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface OrgGraph {
  employees: {
    id: string;
    name: string;
    title: string;
    team_key: string | null;
    team_name: string | null;
    manager_id: string | null;
  }[];
  teams: { key: string; name: string; department_key: string; department_name: string }[];
  systems: {
    key: string;
    name: string;
    category: string | null;
    owner_team_key: string | null;
    support_team_key: string | null;
  }[];
}
