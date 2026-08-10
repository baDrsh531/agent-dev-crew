import { useMemo } from "react";
import { compactNumber, durationLabel, phaseLabel, statusLabel, statusTone } from "../labels";
import { summarise } from "../stats";
import type { AppConfig, Run } from "../types";
import { BarChart, BreakdownBar, LineChart } from "./charts";

/**
 * A tile. `sample` is not decoration: a rate without its denominator is the
 * easiest lie a dashboard can tell, so the count travels with the figure.
 */
function Tile({
  label,
  value,
  sample,
  note,
  tone,
}: {
  label: string;
  value: string;
  sample?: string;
  note?: string;
  tone?: "ok" | "warn" | "bad" | "accent";
}) {
  return (
    <div className={`tile ${tone ?? ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {sample && <div className="tile-sample">{sample}</div>}
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

export function Home({
  runs,
  config,
  onOpenRun,
  onNewTask,
}: {
  runs: Run[];
  config: AppConfig | null;
  onOpenRun: (id: string) => void;
  onNewTask: () => void;
}) {
  const d = useMemo(() => summarise(runs), [runs]);
  const budget = config?.limits.max_tokens_per_run ?? 0;

  if (runs.length === 0) {
    return (
      <div className="home">
        <div className="empty-state">
          <div className="icon-circle" aria-hidden="true">◔</div>
          <h3>Rien à montrer — aucun run pour l'instant</h3>
          <p>
            Ce tableau de bord se remplit à partir des runs réels. Lancez-en un
            et les chiffres apparaîtront ici.
          </p>
          <button type="button" className="btn" onClick={onNewTask}>
            Démarrer une tâche
          </button>
        </div>
      </div>
    );
  }

  // Below this, a percentage is noise wearing a percent sign. The figure is
  // still shown; the caveat comes with it rather than instead of it.
  const THIN_SAMPLE = 5;

  return (
    <div className="home">
      <section>
        <h2 className="section-title">Vue d'ensemble</h2>
        <div className="tile-grid">
          <Tile
            label="Runs"
            value={String(d.total)}
            sample={d.capped ? "les 200 plus récents" : "depuis le début"}
            note={d.startedThisWeek > 0 ? `dont ${d.startedThisWeek} cette semaine` : undefined}
          />
          <Tile
            label="Réussite"
            value={d.successRate === null ? "—" : `${Math.round(d.successRate * 100)} %`}
            sample={
              d.successRate === null
                ? "aucun run terminé"
                : `${d.succeeded} sur ${d.judged} runs jugés`
            }
            note={
              d.judged > 0 && d.judged < THIN_SAMPLE
                ? "échantillon trop petit pour en conclure quoi que ce soit"
                : "les runs annulés sont exclus"
            }
            tone={d.successRate === null ? undefined : d.successRate >= 0.8 ? "ok" : "warn"}
          />
          <Tile
            label="Tokens par run"
            value={d.medianTokens === null ? "—" : compactNumber(d.medianTokens)}
            sample="médiane"
            note={
              budget > 0 && d.medianTokens !== null
                ? `${Math.round((d.medianTokens / budget) * 100)} % du budget`
                : undefined
            }
            tone="accent"
          />
          <Tile
            label="Coût total"
            value={`$${d.totalCost.toFixed(4)}`}
            sample={d.totalCost === 0 ? "modèle auto-hébergé" : `sur ${d.total} runs`}
            note={
              d.totalCost === 0
                ? "le coût marginal d'un token y est nul"
                : undefined
            }
          />
        </div>
      </section>

      <section>
        <h2 className="section-title">Consommation</h2>
        <div className="chart-grid">
          <div className="chart-card">
            <h3>Tokens par run</h3>
            <p className="chart-sub">
              {d.tokenSeries.length} runs les plus récents, du plus ancien au plus récent.
              {budget > 0 && " La ligne pointillée est le plafond : ce qui compte est la marge."}
            </p>
            <BarChart
              data={d.tokenSeries}
              format={compactNumber}
              reference={budget > 0 ? { value: budget, label: "plafond" } : undefined}
              onSelect={(p) => p.id && onOpenRun(p.id)}
            />
          </div>

          <div className="chart-card">
            <h3>Durée par run</h3>
            <p className="chart-sub">
              Horloge murale, de la création à la dernière mise à jour — l'attente
              d'une réponse humaine y est incluse.
            </p>
            <LineChart
              data={d.durationSeries}
              format={(v) => durationLabel(v)}
              onSelect={(p) => p.id && onOpenRun(p.id)}
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className="section-title">Comment ils se terminent</h2>
        <div className="chart-grid">
          <div className="chart-card">
            <h3>Statuts</h3>
            <p className="chart-sub">
              Un run escaladé n'est pas une panne : l'orchestrateur s'est arrêté
              à un plafond plutôt que de le dépasser.
            </p>
            <BreakdownBar
              total={d.total}
              rows={d.byStatus.map((entry) => ({
                label: statusLabel(entry.status),
                count: entry.count,
                tone: statusTone(entry.status),
              }))}
            />
          </div>

          <div className="chart-card">
            <h3>Où ils s'arrêtent</h3>
            <p className="chart-sub">
              Phase atteinte par les runs qui n'ont pas abouti. C'est là qu'il
              faut regarder pour savoir quoi corriger.
            </p>
            {d.stoppedAt.length === 0 ? (
              <p className="empty">Aucun run terminé n'a échoué ni escaladé.</p>
            ) : (
              <BreakdownBar
                total={d.stoppedAt.reduce((n, s) => n + s.count, 0)}
                rows={d.stoppedAt.map((entry) => ({
                  label: phaseLabel(entry.phase),
                  count: entry.count,
                  tone: "warn",
                }))}
              />
            )}
          </div>
        </div>
      </section>

      {d.repairLoops.total > 0 && (
        <section>
          <h2 className="section-title">Boucles de correction</h2>
          <div className="chart-card">
            <p className="chart-sub">
              Combien de runs terminés ont dû repasser par le développeur après
              un refus de la QA. Une part élevée dit que la spécification ou le
              plan arrivent incomplets, pas que la QA est trop sévère.
            </p>
            <BreakdownBar
              total={d.repairLoops.total}
              rows={[
                { label: "Aucune reprise", count: d.repairLoops.none, tone: "ok" },
                { label: "Au moins une", count: d.repairLoops.some, tone: "warn" },
              ]}
            />
          </div>
        </section>
      )}

      <section>
        <h2 className="section-title">Runs récents</h2>
        <div className="chart-card">
          <div className="table-scroll">
            <table className="home-table">
              <thead>
                <tr>
                  <th scope="col">Tâche</th>
                  <th scope="col">Statut</th>
                  <th scope="col" className="num">Tokens</th>
                  <th scope="col" className="num">Durée</th>
                  <th scope="col" className="num">Coût</th>
                </tr>
              </thead>
              <tbody>
                {d.recent.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <button
                        type="button"
                        className="link-row"
                        onClick={() => onOpenRun(run.id)}
                      >
                        {run.title || run.request}
                      </button>
                    </td>
                    <td>
                      <span className={`status-chip tone-${statusTone(run.status)}`}>
                        <span
                          className={`status-dot tone-${statusTone(run.status)}`}
                          aria-hidden="true"
                        />
                        {statusLabel(run.status)}
                      </span>
                    </td>
                    <td className="num">{run.tokens_used ? compactNumber(run.tokens_used) : "—"}</td>
                    <td className="num">
                      {durationLabel(
                        (new Date(run.updated_at).getTime() - new Date(run.created_at).getTime()) / 1000,
                      )}
                    </td>
                    <td className="num">${run.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}
