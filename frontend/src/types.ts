export type RunStatus =
  | "pending"
  | "running"
  | "waiting_for_human"
  | "succeeded"
  | "escalated"
  | "failed"
  | "cancelled";

export type Phase =
  | "intake" | "intake_approval" | "analyze" | "design" | "plan_approval"
  | "implement" | "review" | "fix" | "document" | "done" | "escalated" | "failed";

export type Role =
  | "orchestrator" | "translator" | "analyst" | "architect"
  | "developer" | "qa" | "documenter";

export interface RunEvent {
  id: string;
  run_id: string;
  seq: number;
  type: string;
  at: string;
  phase: Phase | null;
  role: Role | null;
  payload: Record<string, any>;
}

export interface Run {
  id: string;
  request: string;
  title: string;
  status: RunStatus;
  phase: Phase;
  branch: string;
  base_commit: string;
  /** The run's own checkout. Empty once discarded, or if it shared the root. */
  worktree_path: string;
  qa_iterations: number;
  tokens_used: number;
  cost_usd: number;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  kind: string;
  iteration: number;
  payload: Record<string, any>;
  created_at: string;
}

export interface Approval {
  id: string;
  run_id: string;
  tool: string;
  summary: string;
  tool_input: Record<string, any>;
  status: "pending" | "approved" | "denied";
  reason: string;
  created_at: string;
}

export interface Snapshot {
  run: Run;
  events: RunEvent[];
  artifacts: Artifact[];
  pending_approvals: Approval[];
  live: boolean;
  budget: Record<string, number> | null;
}

export interface DiffResponse {
  diff: string;
  branch: string;
  base_commit?: string;
  /** False with a `reason` when there is nothing to show — not an error. */
  available: boolean;
  reason?: string;
  truncated?: boolean;
}

export interface WorkspaceListing {
  root: string;
  available: boolean;
  reason?: string;
  branch?: string;
  files: { path: string; touched: boolean }[];
  /** Segments the sandbox refuses to expose — named, not silently omitted. */
  blocked?: string[];
}

export interface Endpoint {
  url: string;
  leases: number;
  failures: number;
  healthy: boolean;
  cooldown_remaining: number;
  last_error: string;
}

export interface EndpointHealth {
  pooled: boolean;
  endpoints: Endpoint[];
  /** Whether the pooled servers run the same model. Meaningless when not pooled. */
  agree: boolean;
  served?: Record<string, string[]>;
  configured_model?: string;
  /** Roles deliberately sent to a different model. Not part of `agree`. */
  role_routes: Record<string, { url: string; model: string }>;
}

export interface ApprovalModeOption {
  id: string;
  label: string;
}

export interface AppConfig {
  provider: string;
  approval_mode: string;
  approval_modes: ApprovalModeOption[];
  limits: {
    max_qa_iterations: number;
    max_tokens_per_run: number;
    max_wall_clock_seconds: number;
    max_tool_calls_per_agent: number;
  };
  roles: { id: Role; label: string; model: string }[];
  phases: Phase[];
  permissions: Record<string, Record<string, "allowed" | "approval" | "denied">>;
}
