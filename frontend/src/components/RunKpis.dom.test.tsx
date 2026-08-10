import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunKpis, pressureTone } from "./RunKpis";
import type { Artifact, RunEvent } from "../types";

/**
 * The README states the thresholds outright — "orange à 80 %, rouge à 95 %" —
 * and the ceilings are read from the run rather than from today's config.
 * Both are claims a reader can check only if a test does.
 */

const EVENTS: RunEvent[] = [
  {
    id: "e1", run_id: "r1", seq: 1, type: "run.created",
    at: "2026-01-01T00:00:00Z", phase: null, role: null, payload: {},
  },
  {
    id: "e2", run_id: "r1", seq: 2, type: "run.finished",
    at: "2026-01-01T00:05:00Z", phase: null, role: null,
    payload: { elapsed_seconds: 120 },
  },
];

function budget(over: Record<string, number> = {}) {
  return {
    tokens_used: 100_000, max_tokens: 400_000,
    tool_calls_used: 10, max_tool_calls: 40, cost_usd: 0,
    ...over,
  };
}

describe("les seuils annoncés", () => {
  it("reste neutre en dessous de 80 %", () => {
    expect(pressureTone(79, 100)).toBe("");
  });

  it("passe en orange à 80 % exactement", () => {
    expect(pressureTone(80, 100)).toBe("warn");
  });

  it("passe en rouge à 95 % exactement", () => {
    expect(pressureTone(95, 100)).toBe("bad");
  });

  it("n'invente pas de tension sans plafond connu", () => {
    expect(pressureTone(1_000_000, 0)).toBe("");
  });
});

describe("les plafonds viennent du run, pas de la configuration du jour", () => {
  it("affiche le plafond sous lequel le run a réellement tourné", () => {
    // Lire la config actuelle re-étiquetterait tous les runs passés dès qu'on
    // la change : un run confortable dans 400k passerait pour un dépassement.
    render(
      <RunKpis
        events={EVENTS} artifacts={[]} budget={budget({ max_tokens: 800_000 })}
        live={false} activeSeconds={null}
        limits={{ max_tokens_per_run: 200_000, max_tool_calls_per_agent: 5 }}
      />,
    );
    expect(screen.getByText("sur 800k")).toBeInTheDocument();
    // Le plafond d'outils s'affiche dans la valeur elle-même — « 10/40 ».
    expect(screen.getByText("/40")).toBeInTheDocument();
  });

  it("retombe sur la configuration quand le run n'a rien enregistré", () => {
    render(
      <RunKpis
        events={EVENTS} artifacts={[]} budget={null}
        live={false} activeSeconds={null}
        limits={{ max_tokens_per_run: 200_000, max_tool_calls_per_agent: 5 }}
      />,
    );
    expect(screen.getByText("sur 200k")).toBeInTheDocument();
  });
});

describe("les contrôles machine", () => {
  const evidence = (checks: unknown[]): Artifact[] => [
    { kind: "evidence", iteration: 0, payload: { checks }, created_at: "2026-01-01T00:00:00Z" },
  ];

  it("ne compte pas les contrôles sautés dans le dénominateur", () => {
    // Sinon une suite non installée ferait chuter un score qu'elle n'a pas mesuré.
    render(
      <RunKpis
        events={EVENTS}
        artifacts={evidence([
          { name: "tests", passed: true, skipped: false },
          { name: "lint", passed: true, skipped: true },
          { name: "secrets", passed: false, skipped: false },
        ])}
        budget={budget()} live={false} activeSeconds={null} limits={null}
      />,
    );
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });

  it("dit « pas encore mesurés » plutôt que zéro", () => {
    render(
      <RunKpis events={EVENTS} artifacts={[]} budget={budget()}
               live={false} activeSeconds={null} limits={null} />,
    );
    expect(screen.getByText(/pas encore mesurés/i)).toBeInTheDocument();
  });
});

describe("la durée", () => {
  it("ne répète pas le temps actif quand il est égal à l'horloge murale", () => {
    // Sur un run sans attente humaine les deux chiffres sont identiques, et
    // le répéter ne dit rien.
    render(
      <RunKpis events={EVENTS} artifacts={[]} budget={budget()}
               live={false} activeSeconds={300} limits={null} />,
    );
    expect(screen.queryByText(/dont .* actifs/)).not.toBeInTheDocument();
  });

  it("le montre quand une attente humaine les sépare", () => {
    render(
      <RunKpis events={EVENTS} artifacts={[]} budget={budget()}
               live={false} activeSeconds={120} limits={null} />,
    );
    expect(screen.getByText(/dont 2 min 00 actifs/)).toBeInTheDocument();
  });
});
