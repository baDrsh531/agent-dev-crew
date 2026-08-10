import { useEffect, useRef, useState } from "react";
import type { Approval } from "../types";

interface Props {
  approval: Approval;
  onResolve: (approved: boolean, reason: string) => Promise<void>;
}

/**
 * The primary field of a tool call — the bit a person actually needs to read.
 *
 * Returns a label as well as the text, because "content" and "command" call
 * for very different levels of suspicion and an unlabelled code block hides
 * which one you are looking at.
 */
const CANDIDATES: { key: string; label: string }[] = [
  { key: "command", label: "Commande à exécuter" },
  { key: "content", label: "Contenu à écrire" },
  { key: "new_string", label: "Texte de remplacement" },
  { key: "preview", label: "Aperçu" },
  { key: "approach", label: "Approche" },
];

function primaryField(input: Record<string, any>) {
  for (const { key, label } of CANDIDATES) {
    const value = input?.[key];
    if (typeof value === "string" && value.trim()) return { key, label, text: value };
  }
  return null;
}

/** Everything except the field already shown in full, so nothing is duplicated. */
function remainder(input: Record<string, any>, shownKey: string | null): Record<string, any> {
  const rest: Record<string, any> = {};
  for (const [key, value] of Object.entries(input ?? {})) {
    if (key !== shownKey) rest[key] = value;
  }
  return rest;
}

/**
 * The human gate.
 *
 * Two rules this layout exists to enforce:
 *
 * **Nothing is approved blind.** An earlier version showed a preview only when
 * the payload happened to use one of a handful of known keys, and rendered an
 * empty panel otherwise — so the one case where you most need to look was the
 * one that showed you nothing. The full payload is always reachable here; a
 * recognised field is merely promoted, never substituted for the rest.
 *
 * **A refusal has to say why.** The reason is sent back to the agent and is the
 * only thing that lets it try something different; a bare "no" makes it retry
 * the same thing. So Deny stays disabled until there is one, and says why
 * rather than looking broken.
 */
export function ApprovalGate({ approval, onResolve }: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const panel = useRef<HTMLElement>(null);

  // A gate that appears below the fold is a gate nobody answers.
  useEffect(() => {
    panel.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [approval.id]);

  const resolve = async (approved: boolean) => {
    setBusy(true);
    try {
      await onResolve(approved, reason.trim());
    } finally {
      setBusy(false);
    }
  };

  const input = approval.tool_input ?? {};
  const canDeny = reason.trim().length > 0;

  // The intake gate is the one a non-developer is asked to judge, so it gets a
  // plain-language layout rather than a payload preview.
  if (approval.tool === "intake") {
    return (
      <section className="gate" ref={panel} aria-live="assertive">
        <header className="gate-header">
          <span className="gate-badge">À confirmer</span>
          <h3>{input.understood_goal ?? approval.summary}</h3>
        </header>

        {Array.isArray(input.steps) && (
          <ol className="steps">
            {input.steps.map((step: string, i: number) => <li key={i}>{step}</li>)}
          </ol>
        )}

        {Array.isArray(input.clarifications) &&
          input.clarifications.map((c: any, i: number) => (
            <div key={i} className="inner-card">
              <h5>{c.question}</h5>
              <p>Sauf avis contraire : {c.assumed_answer}</p>
              <p className="muted">{c.why_it_matters}</p>
            </div>
          ))}

        {Array.isArray(input.out_of_scope) && input.out_of_scope.length > 0 && (
          <p className="muted">Non inclus : {input.out_of_scope.join(" ; ")}</p>
        )}
        {input.risk && <p className="warn-text">{input.risk}</p>}

        <div className="gate-actions">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Pas tout à fait ? Dites ce qu'il faut changer."
            aria-label="Correction à apporter"
          />
          <button type="button" className="btn approve" disabled={busy} onClick={() => resolve(true)}>
            Oui, allez-y
          </button>
          <button
            type="button"
            className="btn deny"
            disabled={busy || !canDeny}
            onClick={() => resolve(false)}
            title={canDeny ? undefined : "Dites ce qui ne va pas pour demander une reformulation"}
          >
            Non, reformuler
          </button>
        </div>
        {!canDeny && (
          <p className="gate-hint">
            Pour demander une reformulation, écrivez ce qui ne va pas — c'est ce
            qui permet à l'agent de proposer autre chose.
          </p>
        )}
      </section>
    );
  }

  const primary = primaryField(input);
  const rest = remainder(input, primary?.key ?? null);
  const restCount = Object.keys(rest).length;
  // With no recognised field there is nothing else to look at, so the payload
  // is open from the start rather than hidden behind a click.
  const rawOpen = showRaw || !primary;

  return (
    <section className="gate" ref={panel} aria-live="assertive">
      <header className="gate-header">
        <span className="gate-badge">Attend votre réponse</span>
        <h3>{approval.summary}</h3>
        <code className="gate-tool">{approval.tool}</code>
      </header>

      {typeof input.path === "string" && (
        <p className="gate-approach">
          Fichier&nbsp;: <code>{input.path}</code>
        </p>
      )}

      {primary ? (
        <>
          <div className="gate-field-label">{primary.label}</div>
          <pre className="gate-preview">{primary.text}</pre>
        </>
      ) : (
        <p className="gate-approach">
          Cette action n'a pas de champ principal reconnu. Sa charge utile
          complète est ci-dessous — lisez-la avant d'approuver.
        </p>
      )}

      {Array.isArray(input.risks) && input.risks.length > 0 && (
        <ul className="gate-risks">
          {input.risks.map((risk: string, i: number) => <li key={i}>{risk}</li>)}
        </ul>
      )}

      {restCount > 0 && (
        <div className="gate-raw">
          {primary && (
            <button
              type="button"
              className="link"
              aria-expanded={rawOpen}
              onClick={() => setShowRaw(!showRaw)}
            >
              {rawOpen ? "Masquer" : "Voir"} la charge utile complète ({restCount} champ
              {restCount > 1 ? "s" : ""})
            </button>
          )}
          {rawOpen && <pre className="gate-preview">{JSON.stringify(rest, null, 2)}</pre>}
        </div>
      )}

      <div className="gate-actions">
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Motif — transmis à l'agent, obligatoire pour refuser"
          aria-label="Motif"
        />
        <button type="button" className="btn approve" disabled={busy} onClick={() => resolve(true)}>
          Approuver
        </button>
        <button
          type="button"
          className="btn deny"
          disabled={busy || !canDeny}
          onClick={() => resolve(false)}
          title={canDeny ? undefined : "Un motif est nécessaire pour refuser"}
        >
          Refuser
        </button>
      </div>
      {!canDeny && (
        <p className="gate-hint">
          Un refus sans motif fait réessayer la même chose. Écrivez ce qui ne va
          pas et l'agent pourra corriger.
        </p>
      )}
    </section>
  );
}
