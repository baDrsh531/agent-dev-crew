import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RunOutcome } from "./RunOutcome";
import type { Artifact, Run, RunEvent, RunStatus } from "../types";

/**
 * The portfolio's other public claim: "Une escalade est le mécanisme de
 * sécurité qui fonctionne, pas une panne — elle est colorée en conséquence",
 * and "l'interface dit lequel, à quelle phase, ce qui avait déjà été produit,
 * et propose de relancer avec la marge qui manquait".
 */

function run(status: RunStatus, over: Partial<Run> = {}): Run {
  return {
    id: "r1", request: "Ajouter la pagination", title: "Ajouter la pagination",
    status, phase: "escalated", branch: "agent/r1", base_commit: "abc",
    worktree_path: "", qa_iterations: 2, tokens_used: 418_000, cost_usd: 0,
    error: "token budget exhausted (417512/400000)",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:10:00Z",
    ...over,
  };
}

const PHASES: RunEvent[] = ["analyze", "implement", "fix"].map((phase, i) => ({
  id: `e${i}`, run_id: "r1", seq: i + 1, type: "phase.started",
  at: "2026-01-01T00:00:00Z", phase: null, role: null, payload: { phase },
}));

const ARTIFACTS: Artifact[] = [
  { kind: "spec", iteration: 0, payload: {}, created_at: "2026-01-01T00:00:00Z" },
  { kind: "changeset", iteration: 0, payload: {}, created_at: "2026-01-01T00:00:00Z" },
];

describe("une escalade n'est pas une panne", () => {
  it("le dit explicitement plutôt que d'afficher une erreur", () => {
    render(
      <RunOutcome run={run("escalated")} events={PHASES} artifacts={ARTIFACTS}
                  onRelaunch={vi.fn()} />,
    );
    expect(screen.getByText(/n'est pas une panne/i)).toBeInTheDocument();
  });

  it("nomme la phase de travail atteinte, pas le marqueur terminal", () => {
    // `run.phase` vaut "escalated" à la fin : le lire répondait « à la phase :
    // escaladé », ce qui est vrai et inutile.
    render(
      <RunOutcome run={run("escalated")} events={PHASES} artifacts={ARTIFACTS}
                  onRelaunch={vi.fn()} />,
    );
    expect(screen.getByText("Correction")).toBeInTheDocument();
    expect(screen.queryByText("Escaladé", { selector: "dd" })).not.toBeInTheDocument();
  });

  it("liste ce qui avait déjà été produit", () => {
    render(
      <RunOutcome run={run("escalated")} events={PHASES} artifacts={ARTIFACTS}
                  onRelaunch={vi.fn()} />,
    );
    expect(screen.getByText(/spécification, modifications/i)).toBeInTheDocument();
  });

  it("propose d'élargir le budget, avec la demande d'origine", async () => {
    const onRelaunch = vi.fn();
    render(
      <RunOutcome run={run("escalated")} events={PHASES} artifacts={ARTIFACTS}
                  onRelaunch={onRelaunch} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /relancer avec/i }));
    const [request, budget] = onRelaunch.mock.calls[0];
    expect(request).toBe("Ajouter la pagination");
    expect(budget).toBeGreaterThan(400_000);
  });
});

describe("l'offre de relance correspond au plafond qui a mordu", () => {
  it("n'est pas proposée quand élargir le budget n'aiderait pas", () => {
    // Plafond d'appels d'outils : plus de tokens n'y change rien. Proposer le
    // bouton quand même serait du théâtre.
    render(
      <RunOutcome
        run={run("escalated", { error: "tool call ceiling reached (40/40)" })}
        events={PHASES} artifacts={ARTIFACTS} onRelaunch={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /relancer avec/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /telle quelle/i })).toBeInTheDocument();
  });
});

describe("les trois issues restent distinctes", () => {
  it("un échec est présenté comme un échec", () => {
    render(
      <RunOutcome run={run("failed", { error: "quelque chose a cassé" })}
                  events={PHASES} artifacts={[]} onRelaunch={vi.fn()} />,
    );
    expect(screen.getByText(/le run a échoué/i)).toBeInTheDocument();
    expect(screen.queryByText(/n'est pas une panne/i)).not.toBeInTheDocument();
  });

  it("une annulation dit que le travail est conservé", () => {
    render(
      <RunOutcome run={run("cancelled")} events={PHASES} artifacts={[]}
                  onRelaunch={vi.fn()} />,
    );
    expect(screen.getByText(/reste sur sa branche/i)).toBeInTheDocument();
  });

  it("un run réussi n'affiche rien du tout", () => {
    const { container } = render(
      <RunOutcome run={run("succeeded")} events={PHASES} artifacts={ARTIFACTS}
                  onRelaunch={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
