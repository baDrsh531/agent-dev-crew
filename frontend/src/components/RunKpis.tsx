import { useEffect, useState } from "react";
import { compactNumber, durationLabel } from "../labels";
import type { Artifact, RunEvent } from "../types";

/**
 * Wall-clock seconds since the run's first event, ticking while it is live.
 *
 * Deliberately *not* the backend's `elapsed_seconds`, which excludes time
 * spent waiting on a person — that is the right number for judging a budget
 * and the wrong one for "how long have I been sat here". The active figure is
 * shown underneath once the run reports it, so the two are never conflated.
 */
function useWallClock(events: RunEvent[], live: boolean): number {
  const first = events[0]?.at;
  const last = events.at(-1)?.at;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [live]);

  if (!first) return 0;
  const start = new Date(first).getTime();
  const end = live ? now : new Date(last ?? first).getTime();
  return Math.max(0, (end - start) / 1000);
}

/** How close a consumed figure is to its ceiling, as a tone. */
export function pressureTone(used: number, ceiling: number): "" | "warn" | "bad" {
  if (!ceiling) return "";
  const ratio = used / ceiling;
  if (ratio >= 0.95) return "bad";
  if (ratio >= 0.8) return "warn";
  return "";
}

/**
 * A consumed-against-ceiling bar.
 *
 * These are hard ceilings — the orchestrator stops and escalates rather than
 * quietly going past one — so the bar is worth reading before a run gets
 * there. Colour changes at 80% and 95%, and the number stays visible because
 * "nearly full" is not actionable but "38/40" is.
 */
function Gauge({ used, ceiling, label }: { used: number; ceiling: number; label: string }) {
  if (!ceiling) return null;
  const ratio = Math.min(1, used / ceiling);
  const tone = pressureTone(used, ceiling);
  return (
    <div
      className={`gauge ${tone}`}
      role="meter"
      aria-valuenow={used}
      aria-valuemin={0}
      aria-valuemax={ceiling}
      aria-label={label}
    >
      <div className="gauge-fill" style={{ width: `${ratio * 100}%` }} />
    </div>
  );
}

function checksOf(artifacts: Artifact[]): { passed: number; total: number } | null {
  const evidence = artifacts.filter((a) => a.kind === "evidence").at(-1);
  const checks: any[] = evidence?.payload?.checks ?? [];
  const counted = checks.filter((c) => !c.skipped);
  if (counted.length === 0) return null;
  return { passed: counted.filter((c) => c.passed).length, total: counted.length };
}

export function RunKpis({
  events,
  artifacts,
  budget,
  live,
  activeSeconds,
  limits,
}: {
  events: RunEvent[];
  artifacts: Artifact[];
  budget: Record<string, number> | null;
  live: boolean;
  activeSeconds: number | null;
  limits: { max_tokens_per_run: number; max_tool_calls_per_agent: number } | null;
}) {
  const wall = useWallClock(events, live);
  const tokens = budget?.tokens_used ?? 0;
  const toolCalls = budget?.tool_calls_used ?? 0;
  const cost = budget?.cost_usd ?? 0;
  const checks = checksOf(artifacts);

  // The run carries the ceilings it was started under. Reading them from the
  // current config instead would relabel every past run whenever the config
  // changes — a run that finished comfortably inside a 400k budget would
  // suddenly read as over a 200k one it never ran under.
  const maxTokens = budget?.max_tokens || limits?.max_tokens_per_run || 0;
  const maxToolCalls = budget?.max_tool_calls || limits?.max_tool_calls_per_agent || 0;
  const tokenTone = pressureTone(tokens, maxTokens);
  const toolTone = pressureTone(toolCalls, maxToolCalls);

  return (
    <div className="kpi-row">
      <div className="kpi">
        <div className="kpi-label">Durée</div>
        <div className="kpi-value">{durationLabel(wall)}</div>
        {/* Only worth a line when the two differ: on an unattended run they are
            the same number, and repeating it says nothing. */}
        {activeSeconds != null && Math.abs(activeSeconds - wall) > 2 && (
          <div className="kpi-sub" title="Temps actif, hors attente d'une réponse humaine">
            dont {durationLabel(activeSeconds)} actifs
          </div>
        )}
      </div>

      <div className={`kpi ${tokenTone || "accent"}`}>
        <div className="kpi-label">Tokens</div>
        <div className="kpi-value">{compactNumber(tokens)}</div>
        {maxTokens > 0 && (
          <>
            <Gauge used={tokens} ceiling={maxTokens} label="Tokens consommés sur le budget" />
            <div className="kpi-sub">sur {compactNumber(maxTokens)}</div>
          </>
        )}
      </div>

      <div className={`kpi ${toolTone}`}>
        <div className="kpi-label">Appels d'outils</div>
        <div className="kpi-value">
          {toolCalls}
          {maxToolCalls > 0 && <span className="kpi-of">/{maxToolCalls}</span>}
        </div>
        {maxToolCalls > 0 && (
          <>
            <Gauge
              used={toolCalls}
              ceiling={maxToolCalls}
              label="Appels d'outils consommés sur le plafond"
            />
            <div className="kpi-sub">plafond par agent</div>
          </>
        )}
      </div>

      <div className={`kpi ${checks ? (checks.passed === checks.total ? "ok" : "bad") : ""}`}>
        <div className="kpi-label">Contrôles</div>
        <div className="kpi-value">{checks ? `${checks.passed}/${checks.total}` : "—"}</div>
        <div className="kpi-sub">{checks ? "vérifiés par la machine" : "pas encore mesurés"}</div>
      </div>

      <div className="kpi">
        <div className="kpi-label">Coût</div>
        <div className="kpi-value">${cost.toFixed(4)}</div>
        {cost === 0 && <div className="kpi-sub">modèle auto-hébergé</div>}
      </div>
    </div>
  );
}
