import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Home } from "./Home";
import type { AppConfig, Run, RunStatus } from "../types";

/**
 * The dashboard's own claim — "les chiffres portent leur échantillon", and
 * "sous cinq runs il écrit lui-même que l'échantillon est trop petit pour
 * conclure". A dashboard is the easiest place in an app to state something
 * nobody can check, so these are the assertions that keep it honest.
 */

let n = 0;
function run(status: RunStatus, over: Partial<Run> = {}): Run {
  n += 1;
  const at = new Date(Date.UTC(2026, 0, 1, 0, n)).toISOString();
  return {
    id: `r${n}`, request: `demande ${n}`, title: `tâche ${n}`, status,
    phase: "done", branch: `agent/r${n}`, base_commit: "abc", worktree_path: "",
    qa_iterations: 0, tokens_used: 100_000, cost_usd: 0, error: "",
    created_at: at, updated_at: at, ...over,
  };
}

const CONFIG = {
  provider: "openai_compatible", approval_mode: "auto", approval_modes: [],
  limits: {
    max_qa_iterations: 3, max_tokens_per_run: 400_000,
    max_wall_clock_seconds: 900, max_tool_calls_per_agent: 40,
  },
  roles: [], phases: [], permissions: {},
} as unknown as AppConfig;

function show(runs: Run[]) {
  return render(
    <Home runs={runs} config={CONFIG} onOpenRun={vi.fn()} onNewTask={vi.fn()} />,
  );
}

/** Un même mot apparaît dans la répartition et dans le tableau des runs
 *  récents ; une assertion doit dire duquel elle parle. */
function card(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest(".chart-card") as HTMLElement;
}

describe("un chiffre ne part jamais sans son échantillon", () => {
  it("écrit le dénominateur à côté du taux", () => {
    show([run("succeeded"), run("succeeded"), run("failed")]);
    expect(screen.getByText("67 %")).toBeInTheDocument();
    expect(screen.getByText("2 sur 3 runs jugés")).toBeInTheDocument();
  });

  it("avertit lui-même quand l'échantillon est trop petit", () => {
    show([run("succeeded"), run("failed")]);
    expect(screen.getByText(/trop petit pour en conclure/i)).toBeInTheDocument();
  });

  it("cesse d'avertir dès que l'échantillon suffit", () => {
    show(Array.from({ length: 6 }, () => run("succeeded")));
    expect(screen.queryByText(/trop petit pour en conclure/i)).not.toBeInTheDocument();
  });

  it("n'affiche pas de taux du tout tant que rien n'a fini", () => {
    // Zéro pour cent se lirait comme un échec total.
    show([run("running"), run("pending")]);
    // Sur la tuile elle-même : les répartitions ont leurs propres pourcentages,
    // qui sont légitimes et n'ont rien à voir avec le taux de réussite.
    const tuile = screen.getByText("Réussite").closest(".tile") as HTMLElement;
    expect(within(tuile).getByText("—")).toBeInTheDocument();
    expect(within(tuile).getByText(/aucun run terminé/i)).toBeInTheDocument();
  });
});

describe("le périmètre annoncé est celui qui est décrit", () => {
  it("dit « depuis le début » tant que la liste n'est pas tronquée", () => {
    show([run("succeeded")]);
    expect(screen.getByText("depuis le début")).toBeInTheDocument();
  });

  it("dit « les 200 plus récents » dès qu'elle l'est", () => {
    show(Array.from({ length: 200 }, () => run("succeeded")));
    expect(screen.getByText("les 200 plus récents")).toBeInTheDocument();
  });
});

describe("une escalade n'est pas rangée avec les échecs", () => {
  it("apparaît dans sa propre ligne de répartition", () => {
    show([run("succeeded"), run("escalated"), run("failed")]);
    const statuts = within(card("Statuts"));
    expect(statuts.getByText("escaladé")).toBeInTheDocument();
    expect(statuts.getByText("échoué")).toBeInTheDocument();
  });

  it("compte quand même comme un run jugé", () => {
    // Elle n'est pas une réussite : la masquer du dénominateur gonflerait le taux.
    show([run("succeeded"), run("escalated")]);
    expect(screen.getByText("1 sur 2 runs jugés")).toBeInTheDocument();
  });
});

describe("sans aucun run", () => {
  it("le dit au lieu d'afficher des cases vides", () => {
    show([]);
    expect(screen.getByText(/aucun run pour l'instant/i)).toBeInTheDocument();
    expect(screen.queryByText(/vue d'ensemble/i)).not.toBeInTheDocument();
  });
});
