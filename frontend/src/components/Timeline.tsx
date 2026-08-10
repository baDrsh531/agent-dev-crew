import { phaseLabel, roleLabel } from "../labels";
import type { RunEvent } from "../types";

/** Events that are plumbing rather than collaboration — noise in a timeline. */
const HIDDEN = new Set(["budget.updated", "run.status_changed"]);

type Tone = "" | "tone-phase" | "tone-gate" | "tone-ok" | "tone-bad";

interface Entry {
  icon: string;
  title: string;
  body?: string;
  tone: Tone;
}

function describe(event: RunEvent): Entry {
  const p = event.payload;
  switch (event.type) {
    case "run.created":
      return { icon: "▶", title: "Run démarré", body: p.request, tone: "tone-phase" };
    case "phase.started":
      return { icon: "◆", title: `Phase — ${phaseLabel(p.phase)}`, tone: "tone-phase" };
    case "agent.started":
      return { icon: "●", title: `${p.label} commence`, body: `modèle : ${p.model}`, tone: "" };
    case "agent.message":
      return {
        icon: p.kind === "thinking" ? "…" : "”",
        title: p.kind === "thinking" ? "raisonnement" : "note",
        body: p.text,
        tone: "",
      };
    case "agent.finished":
      return {
        icon: "✓",
        title: "termine",
        body:
          `${p.tool_calls} appels d'outils · ${p.usage?.total_tokens ?? 0} tokens` +
          ` · $${(p.usage?.cost_usd ?? 0).toFixed(4)}`,
        tone: "",
      };
    case "agent.failed":
      return { icon: "✕", title: "Agent en échec", body: p.error, tone: "tone-bad" };
    case "tool.requested":
      return { icon: "→", title: p.tool, body: summarizeInput(p.input), tone: "" };
    case "tool.executed":
      return { icon: "✓", title: p.tool, body: truncate(p.output), tone: "tone-ok" };
    case "tool.denied":
      return { icon: "✕", title: `${p.tool} refusé`, body: truncate(p.output), tone: "tone-bad" };
    case "artifact.produced":
      return { icon: "▣", title: `Artefact — ${p.kind}`, tone: "tone-phase" };
    case "handoff":
      return {
        icon: "⇄",
        title: `${p.from} → ${p.to}`,
        body: `transmet ${p.artifact}`,
        tone: "tone-phase",
      };
    case "decision.recorded":
      return {
        icon: p.verdict === "pass" ? "✓" : "✕",
        title: `Verdict QA — ${p.verdict === "pass" ? "conforme" : "à corriger"}`,
        body: `itération ${p.iteration}`,
        tone: p.verdict === "pass" ? "tone-ok" : "tone-bad",
      };
    case "approval.requested":
      return { icon: "!", title: "Validation demandée", body: p.summary, tone: "tone-gate" };
    case "approval.resolved":
      return {
        icon: p.approved ? "✓" : "✕",
        title: p.approved ? "Approuvé" : "Refusé",
        body: p.reason,
        tone: p.approved ? "tone-ok" : "tone-bad",
      };
    case "limit.reached":
      return { icon: "⊘", title: "Plafond atteint", body: p.reason, tone: "tone-gate" };
    case "run.finished":
      return {
        icon: p.status === "succeeded" ? "✓" : "⊘",
        title: `Run ${p.status === "succeeded" ? "terminé" : p.status}`,
        body:
          `${p.qa_iterations} itération(s) de correction · ${p.elapsed_seconds}s actifs` +
          ` · $${(p.budget?.cost_usd ?? 0).toFixed(4)}`,
        tone: p.status === "succeeded" ? "tone-ok" : "tone-gate",
      };
    default:
      return { icon: "·", title: event.type, body: p.message, tone: "" };
  }
}

function summarizeInput(input: unknown): string {
  if (!input || typeof input !== "object") return "";
  const record = input as Record<string, unknown>;
  const key = ["path", "command", "pattern", "message", "runner"].find((k) => k in record);
  return key ? `${key} : ${String(record[key])}` : "";
}

function truncate(text: unknown, limit = 400): string {
  const value = typeof text === "string" ? text : "";
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

export function Timeline({ events }: { events: RunEvent[] }) {
  const visible = events.filter((e) => !HIDDEN.has(e.type));

  if (visible.length === 0) {
    return <p className="empty">Rien ne s'est encore passé.</p>;
  }

  return (
    <ol className="timeline">
      {visible.map((event) => {
        const { icon, title, body, tone } = describe(event);
        const who = roleLabel(event.role);
        return (
          <li key={event.id} className="tl-item">
            <div className="tl-line" aria-hidden="true" />
            <div className={`tl-dot ${tone}`} aria-hidden="true">{icon}</div>
            <div className="tl-content">
              <div className="tl-title">{title}</div>
              {body && <p className="tl-desc">{body}</p>}
              <div className="tl-foot">
                <span>{new Date(event.at).toLocaleTimeString("fr-FR")}</span>
                {who && <span>{who}</span>}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
