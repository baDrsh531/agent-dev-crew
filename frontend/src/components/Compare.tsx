import { useEffect, useState } from "react";
import { api } from "../api";
import { parseDiff } from "../diff";
import { compactNumber, durationLabel, statusLabel, statusTone } from "../labels";
import { durationSeconds } from "../stats";
import type { Run, Snapshot } from "../types";

/**
 * Two runs, side by side, with the deltas computed.
 *
 * This comparison was being done by hand — "178 s against 269 s, 175k against
 * 251k for the same task" — every time something was tuned. Doing it by hand
 * is where the mistakes live, and it does not scale past two numbers.
 *
 * The direction of "better" is per metric and stated, not assumed: fewer
 * tokens is an improvement, more files touched is neither good nor bad. A
 * table that coloured every decrease green would be lying about half its rows.
 */

interface Metric {
  label: string;
  of: (snapshot: Snapshot) => number | null;
  format: (value: number) => string;
  /** "down" = lower is better, "up" = higher is, "none" = no direction. */
  better: "down" | "up" | "none";
}

const METRICS: Metric[] = [
  {
    label: "Durée",
    of: (s) => durationSeconds(s.run),
    format: (v) => durationLabel(v),
    better: "down",
  },
  {
    label: "Tokens",
    of: (s) => s.budget?.tokens_used ?? s.run.tokens_used,
    format: compactNumber,
    better: "down",
  },
  {
    label: "Appels d'outils",
    of: (s) => s.budget?.tool_calls_used ?? null,
    format: (v) => String(v),
    better: "down",
  },
  {
    label: "Reprises QA",
    of: (s) => s.run.qa_iterations,
    format: (v) => String(v),
    better: "down",
  },
  {
    label: "Artefacts produits",
    of: (s) => new Set(s.artifacts.map((a) => a.kind)).size,
    format: (v) => String(v),
    better: "up",
  },
  {
    label: "Contrôles réussis",
    of: (s) => {
      const evidence = s.artifacts.filter((a) => a.kind === "evidence").at(-1);
      const checks: any[] = evidence?.payload?.checks ?? [];
      const counted = checks.filter((c) => !c.skipped);
      return counted.length ? counted.filter((c) => c.passed).length : null;
    },
    format: (v) => String(v),
    better: "up",
  },
];

function DeltaCell({ a, b, metric }: { a: number | null; b: number | null; metric: Metric }) {
  if (a === null || b === null) return <td className="num">—</td>;
  const delta = b - a;
  if (delta === 0) return <td className="num muted">identique</td>;
  const pct = a === 0 ? null : Math.round((delta / a) * 100);
  const improved =
    metric.better === "none" ? null : metric.better === "down" ? delta < 0 : delta > 0;
  const tone = improved === null ? "" : improved ? "delta-good" : "delta-bad";
  return (
    <td className={`num ${tone}`}>
      {delta > 0 ? "+" : "−"}
      {metric.format(Math.abs(delta))}
      {pct !== null && <span className="delta-pct"> ({delta > 0 ? "+" : "−"}{Math.abs(pct)} %)</span>}
    </td>
  );
}

function Head({ snapshot }: { snapshot: Snapshot }) {
  return (
    <div className="compare-head">
      <span className={`status-chip tone-${statusTone(snapshot.run.status)}`}>
        <span className={`status-dot tone-${statusTone(snapshot.run.status)}`} aria-hidden="true" />
        {statusLabel(snapshot.run.status)}
      </span>
      <div className="compare-title">{snapshot.run.title || snapshot.run.request}</div>
      <code>{snapshot.run.branch}</code>
    </div>
  );
}

export function Compare({
  runs,
  leftId,
  rightId,
  onPick,
}: {
  runs: Run[];
  leftId: string | null;
  rightId: string | null;
  onPick: (side: "left" | "right", id: string) => void;
}) {
  const [left, setLeft] = useState<Snapshot | null>(null);
  const [right, setRight] = useState<Snapshot | null>(null);
  const [files, setFiles] = useState<{ left: number | null; right: number | null }>({
    left: null, right: null,
  });

  useEffect(() => {
    let alive = true;
    const load = async (id: string | null, side: "left" | "right") => {
      if (!id) {
        (side === "left" ? setLeft : setRight)(null);
        return;
      }
      const snapshot = await api.snapshot(id).catch(() => null);
      if (!alive) return;
      (side === "left" ? setLeft : setRight)(snapshot);
      const diff = await api.diff(id).catch(() => null);
      if (!alive) return;
      const count = diff?.available ? parseDiff(diff.diff).length : null;
      setFiles((f) => ({ ...f, [side]: count }));
    };
    load(leftId, "left");
    load(rightId, "right");
    return () => {
      alive = false;
    };
  }, [leftId, rightId]);

  const picker = (side: "left" | "right", value: string | null) => (
    <select
      className="compare-select"
      value={value ?? ""}
      onChange={(e) => onPick(side, e.target.value)}
      aria-label={side === "left" ? "Run de référence" : "Run à comparer"}
    >
      <option value="">Choisir un run…</option>
      {runs.map((run) => (
        <option key={run.id} value={run.id}>
          {(run.title || run.request).slice(0, 60)} — {statusLabel(run.status)}
        </option>
      ))}
    </select>
  );

  return (
    <div className="home">
      <section>
        <h2 className="section-title">Comparer deux runs</h2>
        <div className="compare-pickers">
          <div>
            <div className="compare-side-label">Référence</div>
            {picker("left", leftId)}
            {left && <Head snapshot={left} />}
          </div>
          <div>
            <div className="compare-side-label">Comparé à</div>
            {picker("right", rightId)}
            {right && <Head snapshot={right} />}
          </div>
        </div>
      </section>

      {left && right ? (
        <section>
          <div className="chart-card">
            <p className="chart-sub">
              L'écart est coloré selon le sens qui compte pour chaque mesure : moins
              de tokens est un progrès, plus de fichiers touchés n'est ni bon ni
              mauvais. Une colonne qui verdirait toute baisse mentirait sur la
              moitié de ses lignes.
            </p>
            <div className="table-scroll">
              <table className="cost-table">
                <thead>
                  <tr>
                    <th scope="col">Mesure</th>
                    <th scope="col" className="num">Référence</th>
                    <th scope="col" className="num">Comparé</th>
                    <th scope="col" className="num">Écart</th>
                  </tr>
                </thead>
                <tbody>
                  {METRICS.map((metric) => {
                    const a = metric.of(left);
                    const b = metric.of(right);
                    return (
                      <tr key={metric.label}>
                        <td>{metric.label}</td>
                        <td className="num">{a === null ? "—" : metric.format(a)}</td>
                        <td className="num">{b === null ? "—" : metric.format(b)}</td>
                        <DeltaCell a={a} b={b} metric={metric} />
                      </tr>
                    );
                  })}
                  <tr>
                    <td>Fichiers touchés</td>
                    <td className="num">{files.left ?? "—"}</td>
                    <td className="num">{files.right ?? "—"}</td>
                    <DeltaCell
                      a={files.left}
                      b={files.right}
                      metric={{ label: "", of: () => null, format: String, better: "none" }}
                    />
                  </tr>
                </tbody>
              </table>
            </div>
            {left.run.request !== right.run.request && (
              <p className="notice warn" style={{ marginTop: 14 }}>
                Ces deux runs n'ont pas la même demande. L'écart mesure alors la
                différence entre deux tâches, pas l'effet d'un changement.
              </p>
            )}
          </div>
        </section>
      ) : (
        <p className="empty">Choisissez deux runs pour voir les écarts.</p>
      )}
    </div>
  );
}
