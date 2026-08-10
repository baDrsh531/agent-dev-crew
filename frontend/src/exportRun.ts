import { parseDiff, totals } from "./diff";
import { phaseLabel, statusLabel } from "./labels";
import type { Artifact, DiffResponse, Snapshot } from "./types";

/**
 * A run as Markdown, meant to be pasted into a pull request description.
 *
 * This is the bridge between the tool and the workflow it feeds: what changed,
 * why, what was verified, and what to watch. The diff itself is summarised
 * rather than inlined — a PR already shows its own diff, and repeating twenty
 * thousand characters of it would bury the part only this tool knows.
 */

function find(artifacts: Artifact[], kind: string): Record<string, any> | null {
  return artifacts.filter((a) => a.kind === kind).at(-1)?.payload ?? null;
}

function bullets(items: unknown, format: (item: any) => string): string {
  if (!Array.isArray(items) || items.length === 0) return "";
  return `${items.map((item) => `- ${format(item)}`).join("\n")}\n\n`;
}

export function runToMarkdown(snapshot: Snapshot, diff: DiffResponse | null): string {
  const { run, artifacts } = snapshot;
  const spec = find(artifacts, "spec");
  const plan = find(artifacts, "plan");
  const changeset = find(artifacts, "changeset");
  const qa = find(artifacts, "qa_report");
  const docs = find(artifacts, "docs_bundle");
  const evidence = find(artifacts, "evidence");
  const budget = snapshot.budget ?? {};

  const out: string[] = [];
  out.push(`# ${run.title || run.request}\n`);

  if (docs?.plain_language_diff) out.push(`${docs.plain_language_diff}\n`);

  out.push(
    `> ${statusLabel(run.status)} · phase ${phaseLabel(run.phase)} · ` +
      `branche \`${run.branch}\` · ${budget.tokens_used ?? run.tokens_used} tokens · ` +
      `${budget.tool_calls_used ?? 0} appels d'outils\n`,
  );

  if (docs?.report) {
    out.push("## Ce qui a changé\n");
    out.push(`${docs.report.what_changed}\n`);
    out.push("## Ce qui a été vérifié\n");
    out.push(`${docs.report.what_was_verified}\n`);
    out.push("## Ce qu'il faut surveiller\n");
    out.push(`${docs.report.what_to_watch}\n`);
  }

  if (spec) {
    out.push("## Spécification\n");
    if (spec.summary) out.push(`${spec.summary}\n`);
    out.push(
      bullets(
        spec.user_stories,
        (s) => `**${s.id}** — en tant que ${s.as_a}, je veux ${s.i_want}`,
      ),
    );
  }

  if (plan?.steps) {
    out.push("## Plan\n");
    out.push(bullets(plan.steps, (s) => `\`${s.action}\` **${s.target}** — ${s.intent}`));
  }

  if (changeset?.files_changed) {
    out.push("## Fichiers modifiés\n");
    out.push(bullets(changeset.files_changed, (f) => `\`${f.path}\` (${f.action}) — ${f.summary}`));
  }

  if (diff?.available && diff.diff.trim()) {
    const files = parseDiff(diff.diff);
    const sum = totals(files);
    out.push("## Diff\n");
    out.push(`${files.length} fichier(s), +${sum.added} / −${sum.removed}\n`);
    out.push(
      bullets(files, (f) => `\`${f.path}\` +${f.added} / −${f.removed}`),
    );
  }

  if (evidence?.checks) {
    out.push("## Contrôles machine\n");
    out.push(
      bullets(evidence.checks, (c: any) =>
        `${c.skipped ? "⊘" : c.passed ? "✅" : "❌"} **${c.name}** — ${String(c.detail).slice(0, 200)}`,
      ),
    );
  }

  if (qa) {
    out.push("## Verdict QA\n");
    out.push(`**${String(qa.verdict).toUpperCase()}** — ${qa.summary}\n`);
    if (Array.isArray(qa.findings) && qa.findings.length) {
      out.push(
        bullets(qa.findings, (f) => `[${f.severity}] \`${f.file}\` — ${f.summary}`),
      );
    }
  }

  if (run.error) out.push(`## Pourquoi le run s'est arrêté\n\n${run.error}\n`);

  out.push(`\n---\n*Généré par Agent Dev Crew · run \`${run.id.slice(0, 8)}\`*\n`);
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

/** Offer the text as a download; the clipboard is handled by the caller. */
export function downloadMarkdown(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
