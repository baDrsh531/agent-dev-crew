import type { Run, RunStatus } from "./types";

/**
 * Everything the dashboard shows, derived from the run list.
 *
 * Two rules run through this file, and they are the reason it exists instead
 * of a few inline `.filter().length` calls in the view:
 *
 * **Nothing is invented.** Every figure here comes from a column the backend
 * actually stores. A dashboard is the easiest place in an app to put a
 * plausible number nobody can check, and this project has spent its whole life
 * refusing to do that elsewhere.
 *
 * **Small samples say so.** A success rate over three runs is noise wearing a
 * percentage sign, and a week-on-week delta over three runs is worse. Anything
 * that needs a sample to mean something carries its own `n`, and the view is
 * expected to show it.
 */

export interface Point {
  label: string;
  value: number;
  id?: string;
  tone?: "ok" | "warn" | "bad" | "running";
}

export interface Dashboard {
  total: number;
  /** True when the list hit the API's ceiling, so "total" is really "last N". */
  capped: boolean;
  byStatus: { status: RunStatus; count: number }[];
  finished: number;
  succeeded: number;
  /** The denominator behind `successRate`. Exposed rather than recomputed by
   *  the view: a rate and its sample size must never be able to disagree. */
  judged: number;
  /** null when nothing has finished — a rate over zero runs is not a rate. */
  successRate: number | null;
  startedThisWeek: number;
  medianTokens: number | null;
  totalCost: number;
  /** Chronological, oldest first, so a chart reads left to right. */
  tokenSeries: Point[];
  durationSeries: Point[];
  /** Where runs that did not succeed came to a stop. */
  stoppedAt: { phase: string; count: number }[];
  repairLoops: { none: number; some: number; total: number };
  recent: Run[];
}

/**
 * How many runs the dashboard asks for, and therefore how many it describes.
 *
 * Named once because the fetch and the summary have to agree: the API defaults
 * to 50, `summarise` assumed 200, and past fifty runs the dashboard quietly
 * described only the most recent fifty while its own caption said it covered
 * everything. Two numbers that must match are one constant.
 *
 * 200 is the API's own ceiling (`le=200`).
 */
export const RUN_LIST_LIMIT = 200;

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

/** Statuses a run can no longer leave on its own. */
const TERMINAL = new Set<RunStatus>(["succeeded", "escalated", "failed", "cancelled"]);

/** Order the status breakdown reads in: outcome first, then what needs you. */
const STATUS_ORDER: RunStatus[] = [
  "succeeded", "escalated", "failed", "cancelled", "waiting_for_human", "running", "pending",
];

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** Wall clock from creation to last update. Includes time spent waiting on a
 *  person — the run row has no other clock, and inventing one would be worse. */
export function durationSeconds(run: Run): number {
  const start = new Date(run.created_at).getTime();
  const end = new Date(run.updated_at).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 0;
  return (end - start) / 1000;
}

function toneOf(status: RunStatus): Point["tone"] {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "bad";
  if (status === "escalated" || status === "waiting_for_human") return "warn";
  if (status === "running" || status === "pending") return "running";
  return undefined;
}

/** A short, recognisable label for a run in a chart axis. */
function shortLabel(run: Run): string {
  const text = (run.title || run.request).trim();
  const words = text.split(/\s+/).slice(0, 3).join(" ");
  return words.length > 22 ? `${words.slice(0, 21)}…` : words;
}

export function summarise(runs: Run[], limit = RUN_LIST_LIMIT, series = 8): Dashboard {
  const byStatus = STATUS_ORDER.map((status) => ({
    status,
    count: runs.filter((r) => r.status === status).length,
  })).filter((entry) => entry.count > 0);

  const finishedRuns = runs.filter((r) => TERMINAL.has(r.status));
  const succeeded = runs.filter((r) => r.status === "succeeded").length;
  // Cancelled runs are excluded from the denominator: a person stopping a run
  // is their decision, not the system failing at it.
  const judged = finishedRuns.filter((r) => r.status !== "cancelled");

  const cutoff = Date.now() - WEEK_MS;
  const startedThisWeek = runs.filter((r) => new Date(r.created_at).getTime() >= cutoff).length;

  // Oldest first: a chart that reads right to left is a chart read wrong.
  const chronological = [...runs].reverse().slice(-series);

  const stopped = new Map<string, number>();
  for (const run of finishedRuns) {
    if (run.status === "succeeded") continue;
    const phase = run.phase || "inconnue";
    stopped.set(phase, (stopped.get(phase) ?? 0) + 1);
  }

  const withLoops = finishedRuns.filter((r) => r.qa_iterations > 0).length;

  return {
    total: runs.length,
    capped: runs.length >= limit,
    byStatus,
    finished: finishedRuns.length,
    succeeded,
    judged: judged.length,
    successRate: judged.length ? succeeded / judged.length : null,
    startedThisWeek,
    medianTokens: median(finishedRuns.map((r) => r.tokens_used).filter((t) => t > 0)),
    totalCost: runs.reduce((sum, r) => sum + r.cost_usd, 0),
    tokenSeries: chronological.map((run) => ({
      label: shortLabel(run),
      value: run.tokens_used,
      id: run.id,
      tone: toneOf(run.status),
    })),
    durationSeries: chronological.map((run) => ({
      label: shortLabel(run),
      value: Math.round(durationSeconds(run)),
      id: run.id,
      tone: toneOf(run.status),
    })),
    stoppedAt: [...stopped.entries()]
      .map(([phase, count]) => ({ phase, count }))
      .sort((a, b) => b.count - a.count),
    repairLoops: {
      none: finishedRuns.length - withLoops,
      some: withLoops,
      total: finishedRuns.length,
    },
    recent: runs.slice(0, 6),
  };
}
