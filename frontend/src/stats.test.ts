import { describe, expect, it } from "vitest";
import { durationSeconds, median, summarise } from "./stats";
import type { Run, RunStatus } from "./types";

/**
 * The dashboard's claim is that no figure on it is invented. These tests hold
 * it to that — in particular the two places where a dashboard usually lies: a
 * rate quoted without its sample, and a percentage over almost no data.
 */

let clock = 0;
function run(status: RunStatus, over: Partial<Run> = {}): Run {
  clock += 1;
  const created = new Date(Date.UTC(2026, 0, 1, 0, clock)).toISOString();
  return {
    id: `r${clock}`,
    request: `demande ${clock}`,
    title: `tâche ${clock}`,
    status,
    phase: "done",
    branch: `agent/r${clock}`,
    base_commit: "abc",
    worktree_path: "",
    qa_iterations: 0,
    tokens_used: 1000,
    cost_usd: 0,
    error: "",
    created_at: created,
    updated_at: created,
    ...over,
  };
}

describe("median", () => {
  it("is the middle value for an odd count", () => expect(median([3, 1, 2])).toBe(2));
  it("is the mean of the two middle values for an even count", () =>
    expect(median([1, 2, 3, 4])).toBe(2.5));
  it("is null for nothing — not zero, which would read as a measurement", () =>
    expect(median([])).toBeNull());
});

describe("summarise", () => {
  it("counts every run and groups them by status", () => {
    const d = summarise([run("succeeded"), run("succeeded"), run("failed")]);

    expect(d.total).toBe(3);
    expect(d.byStatus).toEqual([
      { status: "succeeded", count: 2 },
      { status: "failed", count: 1 },
    ]);
  });

  it("excludes cancelled runs from the success rate", () => {
    // A person stopping a run is their decision, not the system failing at it.
    const d = summarise([run("succeeded"), run("failed"), run("cancelled")]);

    expect(d.judged).toBe(2);
    expect(d.successRate).toBe(0.5);
  });

  it("exposes the denominator behind the rate", () => {
    // The view must never be able to recompute this and disagree with it.
    const d = summarise([run("succeeded"), run("escalated"), run("failed")]);
    expect(d.succeeded / d.judged).toBe(d.successRate);
  });

  it("has no success rate at all when nothing has finished", () => {
    // A rate over zero runs is not a rate; zero would read as total failure.
    expect(summarise([run("running"), run("pending")]).successRate).toBeNull();
  });

  it("does not count a still-running run as finished", () => {
    const d = summarise([run("succeeded"), run("running"), run("waiting_for_human")]);
    expect(d.finished).toBe(1);
  });

  it("reports where the runs that failed came to a stop", () => {
    const d = summarise([
      run("escalated", { phase: "implement" }),
      run("escalated", { phase: "implement" }),
      run("failed", { phase: "review" }),
      run("succeeded", { phase: "done" }),
    ]);

    expect(d.stoppedAt).toEqual([
      { phase: "implement", count: 2 },
      { phase: "review", count: 1 },
    ]);
  });

  it("orders the charts oldest first, so they read left to right", () => {
    // The API returns newest first; a chart in that order reads backwards.
    const newestFirst = [run("succeeded"), run("succeeded"), run("succeeded")].reverse();
    const d = summarise(newestFirst);
    const times = d.tokenSeries.map((p) => newestFirst.find((r) => r.id === p.id)!.created_at);
    expect([...times].sort()).toEqual(times);
  });

  it("ignores runs that never spent a token when taking the median", () => {
    const d = summarise([
      run("succeeded", { tokens_used: 0 }),
      run("succeeded", { tokens_used: 100 }),
      run("succeeded", { tokens_used: 300 }),
    ]);
    expect(d.medianTokens).toBe(200);
  });

  it("counts the runs that needed a QA repair loop", () => {
    const d = summarise([
      run("succeeded", { qa_iterations: 0 }),
      run("succeeded", { qa_iterations: 2 }),
      run("escalated", { qa_iterations: 1 }),
    ]);
    expect(d.repairLoops).toEqual({ none: 1, some: 2, total: 3 });
  });

  it("says so when the list hit the API's ceiling", () => {
    // Otherwise "48 runs" would silently mean "the 48 most recent".
    expect(summarise([run("succeeded")], 1).capped).toBe(true);
    expect(summarise([run("succeeded")], 200).capped).toBe(false);
  });

  it("handles no runs at all without dividing by zero", () => {
    const d = summarise([]);
    expect(d.total).toBe(0);
    expect(d.successRate).toBeNull();
    expect(d.medianTokens).toBeNull();
    expect(d.tokenSeries).toEqual([]);
  });
});

describe("durationSeconds", () => {
  it("measures creation to last update", () => {
    expect(
      durationSeconds(run("succeeded", {
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:02:30Z",
      })),
    ).toBe(150);
  });

  it("is zero rather than negative when the clock disagrees with itself", () => {
    expect(
      durationSeconds(run("succeeded", {
        created_at: "2026-01-01T00:02:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      })),
    ).toBe(0);
  });

  it("is zero for an unparsable date instead of NaN spreading into the chart", () => {
    expect(durationSeconds(run("succeeded", { updated_at: "pas une date" }))).toBe(0);
  });
});
