import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApprovalGate } from "./ApprovalGate";
import type { Approval } from "../types";

/**
 * The portfolio claims two things about this panel. Both are behaviours, and
 * until now neither was checked:
 *
 *   "Chaque action difficile à défaire s'arrête sur un panneau qui montre sa
 *    charge utile complète, jamais un résumé."
 *   "Un refus exige un motif : c'est la seule chose qui permet à l'agent de
 *    proposer autre chose plutôt que de réessayer à l'identique."
 */

function approval(over: Partial<Approval> = {}): Approval {
  return {
    id: "a1", run_id: "r1", tool: "write_file",
    summary: "Écrire app/auth.py",
    tool_input: { path: "app/auth.py", content: "SECRET_ROTATION = True" },
    status: "pending", reason: "", created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("le refus exige un motif", () => {
  it("laisse refuser dès qu'un motif est écrit", async () => {
    const onResolve = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalGate approval={approval()} onResolve={onResolve} />);

    const deny = screen.getByRole("button", { name: /refuser/i });
    expect(deny).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/motif/i), "chemin hors périmètre");
    expect(deny).toBeEnabled();

    await userEvent.click(deny);
    expect(onResolve).toHaveBeenCalledWith(false, "chemin hors périmètre");
  });

  it("refuse un motif qui n'est que des espaces", async () => {
    render(<ApprovalGate approval={approval()} onResolve={vi.fn()} />);
    await userEvent.type(screen.getByLabelText(/motif/i), "   ");
    expect(screen.getByRole("button", { name: /refuser/i })).toBeDisabled();
  });

  it("n'exige rien pour approuver", async () => {
    const onResolve = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalGate approval={approval()} onResolve={onResolve} />);

    await userEvent.click(screen.getByRole("button", { name: /approuver/i }));
    expect(onResolve).toHaveBeenCalledWith(true, "");
  });

  it("dit pourquoi le refus est bloqué, au lieu de paraître cassé", () => {
    render(<ApprovalGate approval={approval()} onResolve={vi.fn()} />);
    expect(screen.getByText(/réessayer la même chose/i)).toBeInTheDocument();
  });
});

describe("rien n'est approuvé à l'aveugle", () => {
  it("montre le champ principal en entier", () => {
    render(<ApprovalGate approval={approval()} onResolve={vi.fn()} />);
    expect(screen.getByText("SECRET_ROTATION = True")).toBeInTheDocument();
    expect(screen.getByText(/contenu à écrire/i)).toBeInTheDocument();
  });

  it("ouvre la charge utile d'emblée quand aucun champ n'est reconnu", () => {
    // C'est le cas où l'ancienne version n'affichait rien du tout — celui où
    // il faut le plus regarder.
    render(
      <ApprovalGate
        approval={approval({ tool: "outil_inconnu", tool_input: { etrange: "valeur" } })}
        onResolve={vi.fn()}
      />,
    );
    expect(screen.getByText(/pas de champ principal reconnu/i)).toBeInTheDocument();
    expect(screen.getByText(/etrange/)).toBeInTheDocument();
  });

  it("ne perd aucun champ secondaire", async () => {
    render(
      <ApprovalGate
        approval={approval({ tool_input: { content: "x = 1", path: "a.py", mode: "append" } })}
        onResolve={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /charge utile complète/i }));
    expect(screen.getByText(/append/)).toBeInTheDocument();
  });
});
