import { phaseLabel } from "../labels";
import type { Phase, RunEvent, RunStatus } from "../types";

const PIPELINE: Phase[] = [
  "intake", "analyze", "design", "implement", "review", "fix", "document", "done",
];

/**
 * Where the run is, at a glance.
 *
 * This answers the only question anyone has during three minutes of waiting —
 * "how far along is it?" — so it sits at the top of the run and is not hidden
 * behind expert mode. The current step pulses only while the run is actually
 * live: a finished run that kept pulsing would read as still working, which is
 * the one thing this must never get wrong.
 *
 * The repair counter is attached to *Fix* rather than shown separately,
 * because a loop is a property of that step and nowhere else.
 */
export function PipelineStrip({
  events,
  current,
  qaIterations,
  status,
  live,
}: {
  events: RunEvent[];
  current: Phase;
  qaIterations: number;
  status: RunStatus;
  live: boolean;
}) {
  const visited = new Set(
    events.filter((e) => e.type === "phase.started").map((e) => e.payload.phase as Phase),
  );
  const stopped = status === "escalated" || status === "failed" || status === "cancelled";
  const currentIndex = PIPELINE.indexOf(current);

  return (
    <ol className="pipeline" aria-label={`Pipeline — phase actuelle : ${phaseLabel(current)}`}>
      {PIPELINE.map((phase, index) => {
        const isCurrent = phase === current;
        const done = visited.has(phase) && !isCurrent;
        // Steps the run passed but that come before the current one read as
        // done; those it never reached stay grey even if visited out of order.
        const state = isCurrent
          ? stopped ? "stopped" : live ? "active" : "reached"
          : done || index < currentIndex
            ? "done"
            : "pending";
        return (
          <li key={phase} className={`pipe-step ${state}`}>
            <span className="pipe-mark" aria-hidden="true">
              {state === "done" ? "✓" : state === "stopped" ? "⊘" : index + 1}
            </span>
            <span className="pipe-name">{phaseLabel(phase)}</span>
            {phase === "fix" && qaIterations > 0 && (
              <span className="pipe-loops" title={`${qaIterations} retour(s) de la QA`}>
                ×{qaIterations}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
