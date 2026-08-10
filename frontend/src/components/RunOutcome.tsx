import { compactNumber, phaseLabel } from "../labels";
import type { Artifact, Run, RunEvent, RunStatus } from "../types";

/**
 * What happened at the end, and what to do about it.
 *
 * The distinction this exists to make: an **escalation is the system working**.
 * The orchestrator runs under hard ceilings and stops at one instead of
 * quietly going past it. Shown as a red failure, that reads as a bug and
 * invites someone to "fix" the safety mechanism.
 *
 * So an escalation gets a post-mortem instead of an error box: which ceiling,
 * at which phase, what had already been produced by then, and a button that
 * relaunches with the room that was missing. The point is that the run stops
 * being a dead end and becomes the next action.
 */

interface Ceiling {
  match: RegExp;
  what: string;
  hint: string;
  /** Only the token ceiling can be widened from here; the others need a
   *  different fix and offering a button for them would be theatre. */
  widen?: boolean;
}

const CEILINGS: Ceiling[] = [
  {
    match: /token/i,
    what: "le budget de tokens",
    hint: "Relancez avec plus de marge, ou découpez la demande en tâches plus petites.",
    widen: true,
  },
  {
    match: /tool call|appels d'outils/i,
    what: "le plafond d'appels d'outils",
    hint: "L'agent a exploré plus que prévu. Une demande plus précise réduit l'exploration ; un budget plus large ne l'aidera pas.",
  },
  {
    match: /wall clock|elapsed|temps/i,
    what: "le temps imparti",
    hint: "Le travail déjà commité est sur la branche du run.",
  },
  {
    match: /qa|repair|itération/i,
    what: "le nombre de reprises autorisées",
    hint: "La QA a refusé la correction trop de fois. Le rapport QA dit ce qui bloque — c'est là qu'il faut regarder avant de relancer.",
  },
  {
    match: /denied|refus/i,
    what: "une décision humaine",
    hint: "Une action a été refusée à un gate. Le motif que vous avez donné est dans la timeline.",
  },
];

const ARTIFACT_LABEL: Record<string, string> = {
  intake: "cadrage",
  spec: "spécification",
  plan: "plan technique",
  changeset: "modifications",
  evidence: "contrôles machine",
  qa_report: "rapport QA",
  docs_bundle: "documentation",
};

export function RunOutcome({
  run,
  events,
  artifacts,
  onRelaunch,
}: {
  run: Run;
  events: RunEvent[];
  artifacts: Artifact[];
  onRelaunch: (request: string, maxTokens: number | null) => void;
}) {
  const status: RunStatus = run.status;
  if (status !== "escalated" && status !== "failed" && status !== "cancelled") return null;

  // The engine records why it stopped as its own event, which is more specific
  // than the run's error column when both are present.
  const limit = events.find((e) => e.type === "limit.reached");
  const reason = String(limit?.payload?.reason ?? run.error ?? "").trim();
  // `run.phase` is overwritten with the terminal marker when a run stops, so
  // reading it here answered "at which phase?" with "escalated" — true, and
  // useless. The log still holds the last phase actually entered.
  const lastWorkingPhase =
    events
      .filter((e) => e.type === "phase.started")
      .map((e) => String(e.payload.phase))
      .filter((p) => !["escalated", "failed", "done"].includes(p))
      .at(-1) ?? run.phase;
  const budget = events.filter((e) => e.type === "budget.updated").at(-1)?.payload ?? {};
  const produced = [...new Set(artifacts.map((a) => a.kind))];

  if (status === "cancelled") {
    return (
      <div className="notice info">
        <h4>Run annulé</h4>
        <p>
          Vous avez arrêté ce run. Ce qu'il avait déjà écrit reste sur sa branche{" "}
          <code>{run.branch}</code> — « Jeter ce run » supprime tout.
        </p>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="notice bad">
        <h4>Le run a échoué</h4>
        <p>
          {reason ||
            "Aucun motif n'a été enregistré — le dernier événement de la timeline dit où ça s'est arrêté."}
        </p>
      </div>
    );
  }

  const ceiling = CEILINGS.find((c) => c.match.test(reason));
  const used = Number(budget.tokens_used ?? run.tokens_used ?? 0);
  const ceilingValue = Number(budget.max_tokens ?? 0);
  // Enough room to be worth the relaunch, rounded to something readable.
  const suggested = Math.min(4_000_000, Math.max(50_000, Math.ceil((ceilingValue || used) * 2 / 50_000) * 50_000));

  return (
    <section className="postmortem" aria-label="Post-mortem de l'escalade">
      <header>
        <span className="postmortem-badge">Escaladé</span>
        <h4>L'orchestrateur s'est arrêté là où on lui a dit</h4>
      </header>

      <p className="postmortem-lead">
        Ce n'est pas une panne. Le run tourne sous des plafonds fermes et s'arrête
        à l'un d'eux plutôt que de le dépasser en silence.
      </p>

      <dl className="postmortem-facts">
        <div>
          <dt>Plafond atteint</dt>
          <dd>{ceiling?.what ?? "un plafond"}</dd>
        </div>
        <div>
          <dt>À la phase</dt>
          <dd>{phaseLabel(lastWorkingPhase)}</dd>
        </div>
        {ceilingValue > 0 && (
          <div>
            <dt>Consommé</dt>
            <dd>
              {compactNumber(used)} / {compactNumber(ceilingValue)} tokens
            </dd>
          </div>
        )}
        <div>
          <dt>Déjà produit</dt>
          <dd>
            {produced.length
              ? produced.map((k) => ARTIFACT_LABEL[k] ?? k).join(", ")
              : "rien d'exploitable"}
          </dd>
        </div>
      </dl>

      {reason && <p className="postmortem-reason">{reason}</p>}
      {ceiling && <p className="postmortem-hint">{ceiling.hint}</p>}

      <div className="run-actions">
        {ceiling?.widen && (
          <button
            type="button"
            className="btn"
            onClick={() => onRelaunch(run.request, suggested)}
          >
            Relancer avec {compactNumber(suggested)} tokens
          </button>
        )}
        <button type="button" className="btn" onClick={() => onRelaunch(run.request, null)}>
          Reprendre la demande telle quelle
        </button>
      </div>
    </section>
  );
}
