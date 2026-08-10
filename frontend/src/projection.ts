import type { Approval, Artifact, Phase, Run, RunEvent, RunStatus } from "./types";

/**
 * Rebuild what the UI shows from a list of events.
 *
 * The live view was already doing this incrementally, event by event. Pulling
 * it out into one pure function means replay is not a second implementation of
 * the same logic: replaying is just projecting a truncated list. Any state the
 * live view can reach, the scrubber can reach too, because it is the same code.
 */
export interface Projection {
  events: RunEvent[];
  artifacts: Artifact[];
  pendingApprovals: Approval[];
  phase: Phase;
  status: RunStatus;
  budget: Record<string, number> | null;
  qaIterations: number;
  finished: boolean;
}

export function project(events: RunEvent[], base: Run): Projection {
  const artifacts = new Map<string, Artifact>();
  const pending = new Map<string, Approval>();
  let phase: Phase = "intake";
  let status: RunStatus = base.status;
  let budget: Record<string, number> | null = null;
  let qaIterations = 0;
  let finished = false;

  for (const event of events) {
    const p = event.payload;
    switch (event.type) {
      case "phase.started":
        phase = p.phase as Phase;
        break;
      case "run.status_changed":
        status = p.status as RunStatus;
        break;
      case "budget.updated":
        budget = p as Record<string, number>;
        break;
      case "artifact.produced":
        // Keyed by kind+iteration so a repair loop's second QA report replaces
        // nothing and appears alongside the first.
        artifacts.set(`${p.kind}-${p.iteration}`, {
          kind: p.kind,
          iteration: p.iteration,
          payload: p.artifact,
          created_at: event.at,
        });
        break;
      case "decision.recorded":
        if (p.decision === "qa_verdict") qaIterations = p.iteration ?? qaIterations;
        break;
      case "approval.requested":
        pending.set(p.approval_id, {
          id: p.approval_id,
          run_id: event.run_id,
          tool: p.tool,
          summary: p.summary,
          tool_input: p.input ?? {},
          status: "pending",
          reason: "",
          created_at: event.at,
        });
        break;
      case "approval.resolved":
        pending.delete(p.approval_id);
        break;
      case "run.finished":
        status = p.status as RunStatus;
        finished = true;
        break;
      default:
        break;
    }
  }

  return {
    events,
    artifacts: [...artifacts.values()],
    pendingApprovals: [...pending.values()],
    phase,
    status,
    budget,
    qaIterations,
    finished,
  };
}

/**
 * Real gaps between events, in milliseconds, clamped for watchability.
 *
 * A run has a five-second pause while a model thinks and then six events in
 * the same millisecond. Replaying either faithfully is unwatchable, so gaps are
 * clamped at both ends: nothing is instant, nothing takes longer than a beat.
 */
const MIN_GAP_MS = 90;
const MAX_GAP_MS = 1800;

export function gapsBetween(events: RunEvent[]): number[] {
  return events.map((event, index) => {
    if (index === 0) return 0;
    const previous = new Date(events[index - 1].at).getTime();
    const current = new Date(event.at).getTime();
    const delta = Number.isFinite(current - previous) ? current - previous : MIN_GAP_MS;
    return Math.min(Math.max(delta, MIN_GAP_MS), MAX_GAP_MS);
  });
}

export function elapsedLabel(events: RunEvent[], cursor: number): string {
  if (events.length === 0) return "0s";
  const start = new Date(events[0].at).getTime();
  const at = new Date(events[Math.min(cursor, events.length - 1)].at).getTime();
  const seconds = Math.max(0, Math.round((at - start) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
