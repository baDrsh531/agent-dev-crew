import { useState } from "react";
import type { Artifact } from "../types";

const TITLES: Record<string, string> = {
  intake: "Ce que nous avons compris",
  spec: "Spécification",
  plan: "Plan technique",
  changeset: "Modifications",
  qa_report: "Rapport QA",
  docs_bundle: "Documentation",
};

/** Renders each artifact type as the thing it is, not as a JSON blob. */
function Body({ kind, payload }: { kind: string; payload: Record<string, any> }) {
  switch (kind) {
    case "intake":
      // Deliberately the plainest view in the app: it is the one a
      // non-developer reads, and the only one they are asked to judge.
      return (
        <>
          <p className="lead">{payload.understood_goal}</p>
          <ol className="steps">
            {payload.proposed_steps?.map((step: string, i: number) => <li key={i}>{step}</li>)}
          </ol>
          {payload.clarifications?.map((c: any, i: number) => (
            <div key={i} className="inner-card">
              <h5>{c.question}</h5>
              <p>Hypothèse retenue : {c.assumed_answer}</p>
              <p className="muted">{c.why_it_matters}</p>
            </div>
          ))}
          {payload.out_of_scope?.length > 0 && (
            <p className="muted">Non inclus : {payload.out_of_scope.join(" ; ")}</p>
          )}
          {payload.risk_note && <p className="warn-text">{payload.risk_note}</p>}
          <details>
            <summary>La demande telle que l'équipe technique l'a reçue</summary>
            <pre>{payload.technical_request}</pre>
          </details>
        </>
      );
    case "spec":
      return (
        <>
          <p>{payload.summary}</p>
          {payload.user_stories?.map((story: any) => (
            <div key={story.id} className="inner-card">
              <h5>
                {story.id} — en tant que {story.as_a}, je veux {story.i_want}
              </h5>
              <ul>
                {story.acceptance_criteria?.map((c: string, i: number) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          ))}
          {payload.assumptions?.length > 0 && (
            <p className="muted">Hypothèses : {payload.assumptions.join(" ; ")}</p>
          )}
          {payload.out_of_scope?.length > 0 && (
            <p className="muted">Hors périmètre : {payload.out_of_scope.join(" ; ")}</p>
          )}
        </>
      );
    case "plan":
      return (
        <>
          <p>{payload.approach}</p>
          <ol className="steps">
            {payload.steps?.map((step: any) => (
              <li key={step.id}>
                <code>{step.action}</code> <strong>{step.target}</strong> — {step.intent}
                <span className="muted"> ({step.rationale})</span>
              </li>
            ))}
          </ol>
          {payload.alternatives_rejected?.length > 0 && (
            <details>
              <summary>Alternatives écartées</summary>
              <ul>
                {payload.alternatives_rejected.map((a: string, i: number) => <li key={i}>{a}</li>)}
              </ul>
            </details>
          )}
        </>
      );
    case "changeset":
      return (
        <>
          <p>{payload.summary}</p>
          <ul>
            {payload.files_changed?.map((file: any, i: number) => (
              <li key={i}>
                <code>{file.action}</code> <strong>{file.path}</strong> — {file.summary}
              </li>
            ))}
          </ul>
          {payload.steps_skipped?.length > 0 && (
            <p className="warn-text">Étapes sautées : {payload.steps_skipped.join(", ")}</p>
          )}
          {payload.notes_for_qa && <p className="muted">Pour la QA : {payload.notes_for_qa}</p>}
        </>
      );
    case "qa_report":
      return (
        <>
          <p className={payload.verdict === "pass" ? "verdict-pass" : "verdict-fail"}>
            {payload.verdict?.toUpperCase()} — {payload.summary}
          </p>
          <ul>
            {payload.checks?.map((check: any, i: number) => (
              <li key={i}>
                {check.passed ? "✓" : "✗"} <strong>{check.name}</strong> — {check.detail}
              </li>
            ))}
          </ul>
          {payload.findings?.map((finding: any, i: number) => (
            <div key={i} className="inner-card finding">
              <h5>
                <span className={`sev sev-${finding.severity}`}>{finding.severity}</span>{" "}
                {finding.file}
                {finding.line ? `:${finding.line}` : ""} — {finding.summary}
              </h5>
              <p>Se reproduit quand : {finding.failure_scenario}</p>
              <p className="muted">Correction : {finding.suggested_fix}</p>
            </div>
          ))}
        </>
      );
    case "docs_bundle":
      return (
        <>
          {payload.plain_language_diff && (
            <p className="lead">{payload.plain_language_diff}</p>
          )}
          {payload.report && (
            <div className="report">
              <div className="inner-card">
                <h5>Ce qui a changé</h5>
                <p>{payload.report.what_changed}</p>
              </div>
              <div className="inner-card">
                <h5>Ce qui a été vérifié</h5>
                <p>{payload.report.what_was_verified}</p>
              </div>
              <div className="inner-card">
                <h5>Ce qu'il faut surveiller</h5>
                <p>{payload.report.what_to_watch}</p>
              </div>
            </div>
          )}
          <p className="muted">{payload.summary_for_humans}</p>
          {["changelog_entry", "api_documentation", "usage_examples", "setup_instructions"]
            .filter((key) => payload[key]?.trim())
            .map((key) => (
              <details key={key}>
                <summary>{key.replace(/_/g, " ")}</summary>
                <pre>{payload[key]}</pre>
              </details>
            ))}
        </>
      );
    default:
      return <pre>{JSON.stringify(payload, null, 2)}</pre>;
  }
}

export function Artifacts({ artifacts }: { artifacts: Artifact[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (artifacts.length === 0) {
    return <p className="empty">Les artefacts apparaissent ici au fur et à mesure des relais.</p>;
  }

  return (
    <div className="artifacts">
      {artifacts.map((artifact) => {
        const key = `${artifact.kind}-${artifact.iteration}`;
        const isOpen = open === key;
        return (
          <article key={key} className="artifact">
            <button className="artifact-head" onClick={() => setOpen(isOpen ? null : key)}>
              <span>{TITLES[artifact.kind] ?? artifact.kind}</span>
              {artifact.iteration > 0 && <em>itération {artifact.iteration}</em>}
              <span className="chevron">{isOpen ? "−" : "+"}</span>
            </button>
            {isOpen && (
              <div className="artifact-body">
                <Body kind={artifact.kind} payload={artifact.payload} />
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
