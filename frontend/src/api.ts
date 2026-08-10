import { RUN_LIST_LIMIT } from "./stats";
import type {
  AppConfig, DiffResponse, EndpointHealth, RunEvent, Snapshot, WorkspaceListing,
} from "./types";

const BASE = "/api";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  config: () => fetch(`${BASE}/config`).then(json<AppConfig>),

  health: () => fetch(`${BASE}/health`).then(json<Record<string, any>>),

  /** Per-server load and routing. Reaches out over the network, so it is its
   *  own call rather than part of the cheap health check. */
  endpointHealth: () => fetch(`${BASE}/health/endpoints`).then(json<EndpointHealth>),

  /** Asks for exactly what the dashboard claims to describe — see RUN_LIST_LIMIT. */
  listRuns: (limit: number = RUN_LIST_LIMIT) =>
    fetch(`${BASE}/runs?limit=${limit}`)
      .then(json<{ runs: Snapshot["run"][] }>)
      .then((d) => d.runs),

  createRun: (request: string, approvalMode?: string, maxTokens?: number | null) =>
    fetch(`${BASE}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request,
        approval_mode: approvalMode,
        // Omitted rather than sent as null: the backend treats absence as
        // "use the configured default", which is not the same as a value.
        ...(maxTokens ? { max_tokens: maxTokens } : {}),
      }),
    }).then(json<{ run_id: string }>),

  /** The run's file tree, as the agents were allowed to see it. */
  workspace: (runId: string) =>
    fetch(`${BASE}/runs/${runId}/workspace`).then(json<WorkspaceListing>),

  resetWorkspace: () =>
    fetch(`${BASE}/workspace/reset`, { method: "POST" }).then(
      json<{ ok: boolean; workspace: string; checkouts_discarded: number }>,
    ),

  snapshot: (runId: string) => fetch(`${BASE}/runs/${runId}`).then(json<Snapshot>),

  /** Recomputed from git, so it works for runs this process never ran. */
  diff: (runId: string) => fetch(`${BASE}/runs/${runId}/diff`).then(json<DiffResponse>),

  resolveApproval: (runId: string, approvalId: string, approved: boolean, reason: string) =>
    fetch(`${BASE}/runs/${runId}/approvals/${approvalId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, reason }),
    }).then(json<{ ok: boolean }>),

  cancel: (runId: string) =>
    fetch(`${BASE}/runs/${runId}/cancel`, { method: "POST" }).then(json<{ ok: boolean }>),

  /** Discard a run's checkout and branch. Nothing of its work survives. */
  rollback: (runId: string) =>
    fetch(`${BASE}/runs/${runId}/rollback`, { method: "POST" }).then(
      json<{ ok: boolean; branch: string; removed: string }>,
    ),
};

/**
 * Subscribe to a run's event stream.
 *
 * The server replays from `afterSeq` before tailing, so a reconnect after a
 * dropped connection recovers the gap instead of silently losing events.
 */
export function streamRun(
  runId: string,
  afterSeq: number,
  onEvent: (event: RunEvent) => void,
  onError?: () => void,
): () => void {
  const source = new EventSource(`${BASE}/runs/${runId}/stream?after_seq=${afterSeq}`);
  source.addEventListener("run", (message) => {
    onEvent(JSON.parse((message as MessageEvent).data) as RunEvent);
  });
  source.onerror = () => onError?.();
  return () => source.close();
}
