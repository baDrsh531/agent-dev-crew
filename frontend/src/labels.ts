import type { Phase, Role, RunStatus } from "./types";

/**
 * How a status is named and coloured.
 *
 * Six statuses, not three. An **escalation** is the orchestrator stopping
 * exactly where it was told to — a ceiling reached, a gate refused — and
 * painting it the same red as a crash would report a working safety mechanism
 * as a defect. It gets amber, like the other "a person is needed here" states.
 */
export type Tone = "running" | "waiting" | "ok" | "warn" | "bad" | "idle";

const STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  pending: { label: "en attente", tone: "idle" },
  running: { label: "en cours", tone: "running" },
  waiting_for_human: { label: "attend votre réponse", tone: "waiting" },
  succeeded: { label: "terminé", tone: "ok" },
  escalated: { label: "escaladé", tone: "warn" },
  failed: { label: "échoué", tone: "bad" },
  cancelled: { label: "annulé", tone: "idle" },
};

export function statusLabel(status: RunStatus): string {
  return STATUS[status]?.label ?? status;
}

export function statusTone(status: RunStatus): Tone {
  return STATUS[status]?.tone ?? "idle";
}

export const PHASE_LABEL: Record<Phase, string> = {
  intake: "Cadrage",
  intake_approval: "Validation du cadrage",
  analyze: "Analyse",
  design: "Conception",
  plan_approval: "Validation du plan",
  implement: "Développement",
  review: "Revue QA",
  fix: "Correction",
  document: "Documentation",
  done: "Terminé",
  escalated: "Escaladé",
  failed: "Échoué",
};

export const ROLE_LABEL: Record<Role, string> = {
  orchestrator: "Chef de projet",
  translator: "Cadrage",
  analyst: "Analyste métier",
  architect: "Architecte",
  developer: "Développeur",
  qa: "Ingénieur QA",
  documenter: "Rédacteur doc.",
};

export function roleLabel(role: Role | null | undefined): string {
  return role ? (ROLE_LABEL[role] ?? role) : "";
}

export function phaseLabel(phase: string): string {
  return PHASE_LABEL[phase as Phase] ?? phase;
}

/**
 * The autonomy modes, in the interface's language.
 *
 * The list itself still comes from the backend — the UI must never offer a
 * policy the engine does not enforce. Only the wording is ours, and an id with
 * no entry here keeps the backend's own label rather than disappearing.
 */
const AUTONOMY: Record<string, string> = {
  ask: "Me demander pour tout",
  risky: "Me demander seulement si c'est irréversible",
  auto: "Vas-y, préviens-moi en cas de blocage",
};

const AUTONOMY_HINT: Record<string, string> = {
  ask: "Confirmation avant chaque écriture, commande et commit",
  risky: "Uniquement ce qu'un `git reset` ne peut pas défaire",
  auto: "Rien ne bloque ; le run escalade quand même à un plafond",
};

export function autonomyLabel(id: string, fallback: string): string {
  return AUTONOMY[id] ?? fallback;
}

export function autonomyHint(id: string): string | undefined {
  return AUTONOMY_HINT[id];
}

/** `175000` -> `175k`. Long numbers in a KPI box are read, not computed with. */
export function compactNumber(value: number): string {
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

export function durationLabel(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes} min ${String(rest).padStart(2, "0")}`;
}
