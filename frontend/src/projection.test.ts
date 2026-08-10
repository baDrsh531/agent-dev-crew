import { describe, expect, it } from "vitest";
import { elapsedLabel, gapsBetween, project } from "./projection";
import type { Run, RunEvent } from "./types";

/**
 * Replay is not a second implementation of the live view — it is the same
 * projection over a truncated event list. That property is what makes it
 * trustworthy, and it only holds if `project` really rebuilds state from
 * events alone. These tests hold it to that.
 */

const base: Run = {
  id: "r1", request: "faire quelque chose", title: "tâche", status: "running",
  phase: "intake", branch: "agent/r1", base_commit: "abc", worktree_path: "",
  qa_iterations: 0, tokens_used: 0, cost_usd: 0, error: "",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

let seq = 0;
function event(type: string, payload: Record<string, unknown> = {}, at?: string): RunEvent {
  seq += 1;
  return {
    id: `e${seq}`, run_id: "r1", seq, type,
    at: at ?? `2026-01-01T00:00:${String(seq).padStart(2, "0")}Z`,
    phase: null, role: null, payload,
  };
}

describe("project", () => {
  it("follows the phase the run last entered", () => {
    const p = project([event("phase.started", { phase: "analyze" }),
                       event("phase.started", { phase: "design" })], base);
    expect(p.phase).toBe("design");
  });

  it("takes the status from the finish event, not from the base run", () => {
    const p = project([event("run.finished", { status: "escalated" })], base);
    expect(p.status).toBe("escalated");
    expect(p.finished).toBe(true);
  });

  it("keeps both QA reports of a repair loop instead of overwriting", () => {
    // Keyed by kind *and* iteration: the second report is a new artifact, not
    // a correction of the first, and the run is only readable with both.
    const p = project([
      event("artifact.produced", { kind: "qa_report", iteration: 0, artifact: { verdict: "fail" } }),
      event("artifact.produced", { kind: "qa_report", iteration: 1, artifact: { verdict: "pass" } }),
    ], base);

    expect(p.artifacts).toHaveLength(2);
    expect(p.artifacts.map((a) => a.iteration)).toEqual([0, 1]);
  });

  it("drops an approval once it has been resolved", () => {
    const p = project([
      event("approval.requested", { approval_id: "a1", tool: "write_file", summary: "s" }),
      event("approval.resolved", { approval_id: "a1", approved: true }),
    ], base);
    expect(p.pendingApprovals).toEqual([]);
  });

  it("leaves an unresolved approval pending, with its payload", () => {
    const p = project([
      event("approval.requested", {
        approval_id: "a1", tool: "run_command", summary: "pip install", input: { command: "pip" },
      }),
    ], base);

    expect(p.pendingApprovals).toHaveLength(1);
    expect(p.pendingApprovals[0].tool_input).toEqual({ command: "pip" });
  });

  it("shows the budget as of the cursor, not the final one", () => {
    // This is the whole point of the scrubber: the state *at that moment*.
    const events = [
      event("budget.updated", { tokens_used: 100 }),
      event("budget.updated", { tokens_used: 900 }),
    ];
    expect(project(events.slice(0, 1), base).budget).toEqual({ tokens_used: 100 });
    expect(project(events, base).budget).toEqual({ tokens_used: 900 });
  });

  it("rebuilds nothing from an empty list rather than inventing a start", () => {
    const p = project([], base);
    expect(p.artifacts).toEqual([]);
    expect(p.budget).toBeNull();
    expect(p.finished).toBe(false);
  });
});

describe("gapsBetween", () => {
  it("gives the first event no gap to wait through", () => {
    expect(gapsBetween([event("a")])).toEqual([0]);
  });

  it("clamps a long pause so a thinking model is not a dead screen", () => {
    const gaps = gapsBetween([
      event("a", {}, "2026-01-01T00:00:00Z"),
      event("b", {}, "2026-01-01T00:01:00Z"),   // 60 s
    ]);
    expect(gaps[1]).toBeLessThanOrEqual(1800);
  });

  it("clamps a burst so six events in one millisecond stay watchable", () => {
    const gaps = gapsBetween([
      event("a", {}, "2026-01-01T00:00:00.000Z"),
      event("b", {}, "2026-01-01T00:00:00.000Z"),
    ]);
    expect(gaps[1]).toBeGreaterThanOrEqual(90);
  });
});

describe("elapsedLabel", () => {
  it("counts from the first event, not from zero", () => {
    const events = [
      event("a", {}, "2026-01-01T00:00:10Z"),
      event("b", {}, "2026-01-01T00:00:40Z"),
    ];
    expect(elapsedLabel(events, 1)).toBe("30s");
  });

  it("switches to minutes past sixty seconds", () => {
    const events = [
      event("a", {}, "2026-01-01T00:00:00Z"),
      event("b", {}, "2026-01-01T00:01:05Z"),
    ];
    expect(elapsedLabel(events, 1)).toBe("1m 5s");
  });

  it("does not run off the end when the cursor is past the last event", () => {
    expect(elapsedLabel([event("a")], 99)).toBe("0s");
  });

  it("is zero for no events at all", () => {
    expect(elapsedLabel([], 0)).toBe("0s");
  });
});
