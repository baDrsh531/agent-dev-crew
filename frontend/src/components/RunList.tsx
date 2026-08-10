import { useMemo, useState } from "react";
import { statusLabel, statusTone } from "../labels";
import type { Run, RunStatus } from "../types";

type Filter = "all" | "live" | "done" | "attention";

const FILTERS: { id: Filter; label: string; title: string }[] = [
  { id: "all", label: "Tous", title: "Tous les runs" },
  { id: "live", label: "En cours", title: "Runs encore en train de travailler" },
  { id: "attention", label: "À voir", title: "Runs qui attendent une décision ou qui se sont arrêtés" },
  { id: "done", label: "Terminés", title: "Runs terminés avec succès" },
];

/** Which bucket a status falls into. Kept next to the filters it defines. */
function bucketOf(status: RunStatus): Filter[] {
  switch (status) {
    case "pending":
    case "running":
      return ["all", "live"];
    case "waiting_for_human":
      // Both: it is running *and* it is blocked on you, which is the one case
      // where being in a single bucket would hide it from whoever can unblock it.
      return ["all", "live", "attention"];
    case "succeeded":
      return ["all", "done"];
    case "escalated":
    case "failed":
      return ["all", "attention"];
    default:
      return ["all"];
  }
}

export function RunList({
  runs,
  activeId,
  onSelect,
}: {
  runs: Run[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => {
    const tally: Record<Filter, number> = { all: 0, live: 0, done: 0, attention: 0 };
    for (const run of runs) {
      for (const bucket of bucketOf(run.status)) tally[bucket] += 1;
    }
    return tally;
  }, [runs]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter((run) => {
      if (!bucketOf(run.status).includes(filter)) return false;
      if (!needle) return true;
      return `${run.title} ${run.request}`.toLowerCase().includes(needle);
    });
  }, [runs, filter, query]);

  if (runs.length === 0) {
    return <p className="empty">Aucun run pour l'instant.</p>;
  }

  return (
    <>
      <div className="run-filters" role="group" aria-label="Filtrer les runs">
        {FILTERS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="chip"
            aria-pressed={filter === entry.id}
            title={entry.title}
            onClick={() => setFilter(entry.id)}
          >
            {entry.label}
            <span className="chip-count">{counts[entry.id]}</span>
          </button>
        ))}
      </div>

      {runs.length > 5 && (
        <input
          type="search"
          className="run-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Chercher dans les demandes…"
          aria-label="Chercher dans les demandes"
        />
      )}

      {/* Ordering is the server's: newest first. Re-sorting here would make a
          run jump position the moment its status changed, under the cursor of
          whoever was about to click it. */}
      <div className="runs-scroll">
        {shown.map((run) => (
          <button
            key={run.id}
            type="button"
            className="run-item"
            aria-current={run.id === activeId}
            onClick={() => onSelect(run.id)}
          >
            <span className={`status-dot tone-${statusTone(run.status)}`} aria-hidden="true" />
            <span className="run-info">
              <span className="run-title">{run.title || run.request}</span>
              <span className="run-meta">
                <span>{statusLabel(run.status)}</span>
                <span aria-hidden="true">·</span>
                <span>${run.cost_usd.toFixed(4)}</span>
              </span>
            </span>
          </button>
        ))}
        {shown.length === 0 && (
          <p className="empty">
            {query.trim() ? "Aucun run ne correspond." : "Aucun run dans cette catégorie."}
          </p>
        )}
      </div>
    </>
  );
}
