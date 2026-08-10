import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, streamRun } from "./api";
import { ApprovalGate } from "./components/ApprovalGate";
import { Artifacts } from "./components/Artifacts";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { Compare } from "./components/Compare";
import { CostTable } from "./components/CostTable";
import { DiffView } from "./components/DiffView";
import { Home } from "./components/Home";
import { ModelServers, shortModel } from "./components/ModelServers";
import { NewTask } from "./components/NewTask";
import { PipelineStrip } from "./components/PipelineStrip";
import { ReplayControls } from "./components/ReplayControls";
import { RunKpis } from "./components/RunKpis";
import { RunList } from "./components/RunList";
import { RunOutcome } from "./components/RunOutcome";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { WorkspaceTree } from "./components/WorkspaceTree";
import { downloadMarkdown, runToMarkdown } from "./exportRun";
import { useNotifier } from "./notify";
import { useTemplates } from "./templates";
import { phaseLabel, statusLabel, statusTone } from "./labels";
import { project } from "./projection";
import { useTheme } from "./theme";
import type { AppConfig, Run, Snapshot } from "./types";

type Page = "home" | "runs" | "compare";

type TabId = "timeline" | "artifacts" | "diff" | "workspace" | "costs";

const TABS: { id: TabId; label: string }[] = [
  { id: "timeline", label: "Timeline" },
  { id: "artifacts", label: "Artefacts" },
  { id: "diff", label: "Diff" },
  { id: "workspace", label: "Workspace" },
  { id: "costs", label: "Coûts" },
];

export default function App() {
  const [theme, setTheme] = useTheme();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replayCursor, setReplayCursor] = useState<number | null>(null);
  const [autonomy, setAutonomy] = useState<string>("");
  const [tab, setTab] = useState<TabId>("timeline");
  const [page, setPage] = useState<Page>("home");
  // Simple by default: phases, budgets and the permission matrix are the
  // author's concerns, not the concerns of the person asking for the work.
  const [expert, setExpert] = useState(false);
  const [permsOpen, setPermsOpen] = useState(true);
  // Discarding a run cannot be undone, so the button asks once before doing it.
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  // Cancelling is reversible — a cancelled run can be resumed — but it still
  // throws away whatever the current agent was mid-way through.
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [compare, setCompare] = useState<{ left: string | null; right: string | null }>({
    left: null, right: null,
  });
  const [copied, setCopied] = useState(false);
  const timelineEnd = useRef<HTMLDivElement>(null);
  const notifier = useNotifier();
  const { templates, saved, save: saveTemplate, remove: removeTemplate } = useTemplates();

  const [request, setRequest] = useState("");
  useEffect(() => {
    if (!request && templates.length) setRequest(templates[0].request);
  }, [request, templates]);

  useEffect(() => {
    api
      .config()
      .then((c) => {
        setConfig(c);
        setAutonomy(c.approval_mode);
      })
      .catch((e) => setError(String(e)));
    api.listRuns().then(setRuns).catch(() => undefined);
  }, []);

  const refreshRuns = useCallback(() => {
    api.listRuns().then(setRuns).catch(() => undefined);
  }, []);

  // A pending confirmation belongs to one run; switching runs must not carry
  // it over to the next one.
  useEffect(() => {
    setConfirmDiscard(false);
    setConfirmCancel(false);
    setTab("timeline");
  }, [activeId]);

  const discardRun = useCallback(
    (runId: string) => {
      setConfirmDiscard(false);
      api
        .rollback(runId)
        .then(() => api.snapshot(runId).then(setSnapshot))
        .then(refreshRuns)
        .catch((e) => setError(String(e)));
    },
    [refreshRuns],
  );

  // Load the full snapshot, then tail the live stream from its last seq.
  useEffect(() => {
    if (!activeId) return;
    let stop: (() => void) | undefined;
    let cancelled = false;

    api.snapshot(activeId).then((initial) => {
      if (cancelled) return;
      setSnapshot(initial);
      const lastSeq = initial.events.at(-1)?.seq ?? 0;
      if (!initial.live) return;

      stop = streamRun(activeId, lastSeq, (event) => {
        setSnapshot((current) => {
          if (!current || current.events.some((e) => e.seq === event.seq)) return current;
          const next: Snapshot = { ...current, events: [...current.events, event] };
          if (event.type === "artifact.produced") {
            next.artifacts = [
              ...current.artifacts.filter(
                (a) => !(a.kind === event.payload.kind && a.iteration === event.payload.iteration),
              ),
              {
                kind: event.payload.kind,
                iteration: event.payload.iteration,
                payload: event.payload.artifact,
                created_at: event.at,
              },
            ];
          }
          if (event.type === "run.status_changed") {
            next.run = { ...current.run, status: event.payload.status };
          }
          if (event.type === "phase.started") {
            next.run = { ...next.run, phase: event.payload.phase };
          }
          if (event.type === "budget.updated") {
            next.budget = event.payload;
          }
          if (event.type === "approval.requested") {
            // The whole point of "ask me about everything" is that someone
            // answers; a gate nobody sees is a run stuck forever.
            notifier.notify(
              "waiting",
              "Une validation est attendue",
              String(event.payload.summary ?? event.payload.tool ?? ""),
            );
            next.pending_approvals = [
              ...current.pending_approvals,
              {
                id: event.payload.approval_id,
                run_id: current.run.id,
                tool: event.payload.tool,
                summary: event.payload.summary,
                tool_input: event.payload.input,
                status: "pending",
                reason: "",
                created_at: event.at,
              },
            ];
          }
          if (event.type === "approval.resolved") {
            next.pending_approvals = current.pending_approvals.filter(
              (a) => a.id !== event.payload.approval_id,
            );
          }
          if (event.type === "run.finished") {
            next.live = false;
            next.run = { ...next.run, status: event.payload.status };
            notifier.notify(
              "finished",
              `Run ${statusLabel(event.payload.status)}`,
              current.run.title || current.run.request,
            );
            refreshRuns();
          }
          return next;
        });
      });
    });

    return () => {
      cancelled = true;
      stop?.();
    };
  }, [activeId, refreshRuns, notifier]);

  useEffect(() => {
    if (tab !== "timeline") return;
    timelineEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [snapshot?.events.length, tab]);

  const start = useCallback(
    async (text: string = request, maxTokens: number | null = null) => {
      setError(null);
      setStarting(true);
      try {
        const { run_id } = await api.createRun(text, autonomy || undefined, maxTokens);
        setActiveId(run_id);
        setPage("runs");
        refreshRuns();
      } catch (e) {
        setError(String(e));
      } finally {
        setStarting(false);
      }
    },
    [request, autonomy, refreshRuns],
  );

  /** An escalation becomes the next action rather than a dead end. */
  const relaunch = useCallback(
    (text: string, maxTokens: number | null) => {
      setRequest(text);
      setPage("runs");
      start(text, maxTokens);
    },
    [start],
  );

  const exportMarkdown = useCallback(
    async (copyToClipboard: boolean) => {
      if (!snapshot) return;
      const diff = await api.diff(snapshot.run.id).catch(() => null);
      const text = runToMarkdown(snapshot, diff);
      if (copyToClipboard) {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        return;
      }
      downloadMarkdown(`run-${snapshot.run.id.slice(0, 8)}.md`, text);
    },
    [snapshot],
  );

  // Cmd/Ctrl+K anywhere. Registered on the window rather than a container so
  // it works no matter what currently has focus.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const commands: Command[] = useMemo(() => {
    const list: Command[] = [
      { id: "go-home", group: "Aller à", label: "Accueil", run: () => setPage("home") },
      { id: "go-runs", group: "Aller à", label: "Runs", run: () => setPage("runs") },
      { id: "go-compare", group: "Aller à", label: "Comparer deux runs", run: () => setPage("compare") },
      {
        id: "theme",
        group: "Affichage",
        label: `Basculer en thème ${theme === "dark" ? "clair" : "sombre"}`,
        run: () => setTheme(theme === "dark" ? "light" : "dark"),
      },
      {
        id: "expert",
        group: "Affichage",
        label: expert ? "Quitter le mode expert" : "Passer en mode expert",
        run: () => setExpert(!expert),
      },
      {
        id: "sound",
        group: "Affichage",
        label: notifier.soundOn ? "Couper le son des notifications" : "Activer le son des notifications",
        run: () => notifier.setSoundOn(!notifier.soundOn),
      },
    ];

    for (const template of templates) {
      list.push({
        id: `tpl-${template.id}`,
        group: "Lancer une tâche",
        label: template.label,
        hint: template.request.slice(0, 70),
        run: () => {
          setRequest(template.request);
          setPage("runs");
        },
      });
    }

    if (snapshot) {
      list.push({
        id: "export-copy",
        group: "Run courant",
        label: "Copier le résumé Markdown",
        run: () => exportMarkdown(true),
      });
      list.push({
        id: "export-file",
        group: "Run courant",
        label: "Télécharger le résumé Markdown",
        run: () => exportMarkdown(false),
      });
    }

    for (const run of runs.slice(0, 20)) {
      list.push({
        id: `run-${run.id}`,
        group: "Ouvrir un run",
        label: run.title || run.request,
        hint: statusLabel(run.status),
        run: () => {
          setActiveId(run.id);
          setPage("runs");
        },
      });
    }
    return list;
  }, [templates, runs, snapshot, theme, expert, notifier, setTheme, exportMarkdown]);

  const resolve = async (approvalId: string, approved: boolean, reason: string) => {
    if (!activeId) return;
    await api.resolveApproval(activeId, approvalId, approved, reason);
  };

  // Replay is the same projection the live view uses, over a truncated event
  // list — so anything the live view can show, the scrubber can show too.
  const replaying = replayCursor !== null && snapshot !== null;
  const view = useMemo(() => {
    if (!snapshot) return null;
    if (!replaying) {
      return {
        events: snapshot.events,
        artifacts: snapshot.artifacts,
        phase: snapshot.run.phase,
        status: snapshot.run.status,
        budget: snapshot.budget,
        qaIterations: snapshot.run.qa_iterations,
      };
    }
    const projected = project(snapshot.events.slice(0, replayCursor ?? 0), snapshot.run);
    return {
      events: projected.events,
      artifacts: projected.artifacts,
      phase: projected.phase,
      status: projected.status,
      budget: projected.budget,
      qaIterations: projected.qaIterations,
    };
  }, [snapshot, replaying, replayCursor]);

  const pending = replaying ? [] : (snapshot?.pending_approvals ?? []);
  const status = view?.status ?? snapshot?.run.status ?? "pending";
  const activeSeconds = useMemo(() => {
    const finished = view?.events.find((e) => e.type === "run.finished");
    return finished ? Number(finished.payload.elapsed_seconds) : null;
  }, [view?.events]);

  return (
    <>
      <TopBar
        config={config}
        expert={expert}
        onExpert={setExpert}
        theme={theme}
        onTheme={setTheme}
      />

      <nav className="navbar" aria-label="Sections">
        {([
          { id: "home", label: "Accueil", icon: "◔" },
          { id: "runs", label: "Runs", icon: "⚡" },
          { id: "compare", label: "Comparer", icon: "⇄" },
        ] as const).map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="nav-item"
            aria-current={page === entry.id ? "page" : undefined}
            onClick={() => setPage(entry.id)}
          >
            <span aria-hidden="true">{entry.icon}</span>
            {entry.label}
            {entry.id === "runs" && runs.length > 0 && (
              <span className="nav-count">{runs.length}</span>
            )}
          </button>
        ))}
        <button
          type="button"
          className="nav-palette"
          onClick={() => setPaletteOpen(true)}
          title="Palette de commandes"
        >
          Chercher… <kbd>Ctrl</kbd><kbd>K</kbd>
        </button>
      </nav>

      <CommandPalette
        open={paletteOpen}
        commands={commands}
        onClose={() => setPaletteOpen(false)}
      />

      {/* Asked for once, and only once there is something worth being told
          about — permission prompts on page load are what train people to
          click "block". */}
      {notifier.permission === "default" && runs.some((r) => r.status === "waiting_for_human") && (
        <div className="notice info" style={{ margin: "16px 32px 0" }}>
          <h4>Être prévenu quand un run vous attend ?</h4>
          <p>
            Un run dure plusieurs minutes et s'arrête aux gates. Sans notification,
            personne ne voit la demande.
          </p>
          <div className="run-actions" style={{ marginTop: 10 }}>
            <button type="button" className="btn small" onClick={notifier.requestPermission}>
              Autoriser les notifications
            </button>
            <button
              type="button"
              className="btn small ghost"
              aria-pressed={notifier.soundOn}
              onClick={() => notifier.setSoundOn(!notifier.soundOn)}
            >
              {notifier.soundOn ? "Son activé" : "Activer le son"}
            </button>
          </div>
        </div>
      )}

      {page === "compare" && (
        <Compare
          runs={runs}
          leftId={compare.left}
          rightId={compare.right}
          onPick={(side, id) => setCompare((c) => ({ ...c, [side]: id || null }))}
        />
      )}

      {page === "home" && (
        <Home
          runs={runs}
          config={config}
          onOpenRun={(id) => {
            setActiveId(id);
            setPage("runs");
          }}
          onNewTask={() => setPage("runs")}
        />
      )}

      <div className="layout" hidden={page !== "runs"}>
        <aside className="sidebar">
          {config && (
            <NewTask
              request={request}
              onRequest={setRequest}
              modes={config.approval_modes}
              autonomy={autonomy}
              onAutonomy={setAutonomy}
              onStart={() => start()}
              busy={starting}
              templates={templates}
              savedIds={new Set(saved.map((t) => t.id))}
              onSaveTemplate={saveTemplate}
              onRemoveTemplate={removeTemplate}
            />
          )}

          <section className="card">
            <h2 className="card-title">
              Runs <span className="count">({runs.length})</span>
            </h2>
            <RunList runs={runs} activeId={activeId} onSelect={setActiveId} />
          </section>

          {config && expert && (
            <section className="card">
              <button
                type="button"
                className="collapsible-header"
                aria-expanded={permsOpen}
                onClick={() => setPermsOpen(!permsOpen)}
              >
                <h2 className="card-title" style={{ margin: 0 }}>Qui peut faire quoi</h2>
                <span className="chevron" data-open={permsOpen} aria-hidden="true">⌄</span>
              </button>
              {permsOpen && (
                <div style={{ paddingTop: 12 }}>
                  {config.roles
                    .filter((role) => role.id !== "orchestrator")
                    .map((role) => {
                      const perms = config.permissions[role.id] ?? {};
                      const write = perms.write_file ?? perms.write_doc ?? "denied";
                      const shell = perms.run_command ?? "denied";
                      return (
                        <div className="perm-row" key={role.id}>
                          <div className="perm-role">{role.label}</div>
                          <div>
                            <div className="perm-tags">
                              <span className={`tag ${write}`}>écriture</span>
                              <span className={`tag ${shell}`}>shell</span>
                            </div>
                            <div className="perm-model" title={role.model}>
                              {shortModel(role.model)}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                </div>
              )}
            </section>
          )}

          {expert && (
            <section className="card">
              <h2 className="card-title">Serveurs de modèles</h2>
              <ModelServers />
            </section>
          )}
        </aside>

        <main className="main">
          {config?.provider === "fake" && (
            <div className="notice warn">
              <h4>Le fournisseur « fake » est actif</h4>
              <p>
                Aucune clé n'est configurée. L'orchestration, les gates et le flux
                d'événements sont réels ; le contenu des artefacts est un
                remplissage valide au schéma mais vide de sens.
              </p>
            </div>
          )}
          {error && (
            <div className="notice bad">
              <h4>Le backend n'a pas répondu</h4>
              <p>{error}</p>
            </div>
          )}

          {!snapshot && (
            <div className="empty-state">
              <div className="icon-circle" aria-hidden="true">⚡</div>
              <h3>Aucun run sélectionné</h3>
              <p>
                Démarrez une nouvelle tâche à gauche, ou choisissez un run existant
                dans la liste pour en voir le détail.
              </p>
            </div>
          )}

          {snapshot && view && (
            <>
              <div className="run-header">
                <div>
                  <h2>{snapshot.run.request}</h2>
                  <div className="subtitle">
                    <span className={`status-chip tone-${statusTone(status)}`}>
                      <span className={`status-dot tone-${statusTone(status)}`} aria-hidden="true" />
                      {statusLabel(status)}
                    </span>
                    <span>Phase&nbsp;: {phaseLabel(view.phase)}</span>
                    {snapshot.run.branch && <code>{snapshot.run.branch}</code>}
                  </div>
                </div>
                <div className="run-actions">
                  {snapshot.live && !confirmCancel && (
                    <button
                      type="button"
                      className="btn small danger"
                      onClick={() => setConfirmCancel(true)}
                    >
                      Annuler
                    </button>
                  )}
                  {!snapshot.live && !replaying && snapshot.events.length > 0 && (
                    <button type="button" className="btn small" onClick={() => setReplayCursor(0)}>
                      ▶ Rejouer
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => exportMarkdown(true)}
                    title="Résumé complet, collable dans une pull request"
                  >
                    {copied ? "✓ Copié" : "Copier en Markdown"}
                  </button>
                  {!snapshot.live && snapshot.run.worktree_path && !confirmDiscard && (
                    <button
                      type="button"
                      className="btn small danger"
                      onClick={() => setConfirmDiscard(true)}
                    >
                      Jeter ce run
                    </button>
                  )}
                </div>
              </div>

              {confirmCancel && (
                <div className="notice warn" role="alertdialog" aria-label="Annuler ce run">
                  <h4>Arrêter ce run maintenant ?</h4>
                  <p>
                    L'agent en cours termine son tour, puis le run s'arrête. Ce qui
                    a déjà été écrit reste sur la branche <code>{snapshot.run.branch}</code>
                    {" "}— rien n'est supprimé. Un run annulé peut être repris.
                  </p>
                  <div className="run-actions" style={{ marginTop: 12 }}>
                    <button
                      type="button"
                      className="btn small danger-solid"
                      onClick={() => {
                        setConfirmCancel(false);
                        api.cancel(snapshot.run.id).catch((e) => setError(String(e)));
                      }}
                    >
                      Arrêter le run
                    </button>
                    <button
                      type="button"
                      className="btn small"
                      onClick={() => setConfirmCancel(false)}
                    >
                      Continuer
                    </button>
                  </div>
                </div>
              )}

              {confirmDiscard && (
                <div className="notice bad" role="alertdialog" aria-label="Jeter ce run">
                  <h4>Supprimer tout le travail de ce run ?</h4>
                  <p>
                    Efface chaque fichier écrit par ce run et la branche{" "}
                    <code>{snapshot.run.branch}</code>. Vos autres runs ne sont pas
                    touchés. C'est irréversible.
                  </p>
                  <div className="run-actions" style={{ marginTop: 12 }}>
                    <button
                      type="button"
                      className="btn small danger-solid"
                      onClick={() => discardRun(snapshot.run.id)}
                    >
                      Supprimer le travail
                    </button>
                    <button
                      type="button"
                      className="btn small"
                      onClick={() => setConfirmDiscard(false)}
                    >
                      Le garder
                    </button>
                  </div>
                </div>
              )}

              <RunKpis
                events={view.events}
                artifacts={view.artifacts}
                budget={view.budget}
                live={snapshot.live && !replaying}
                activeSeconds={activeSeconds}
                limits={config?.limits ?? null}
              />

              {replaying && (
                <ReplayControls
                  events={snapshot.events}
                  cursor={replayCursor ?? 0}
                  onCursor={setReplayCursor}
                  onExit={() => setReplayCursor(null)}
                  phase={view.phase}
                />
              )}

              {/* Not behind expert mode: "how far along is it?" is the one
                  question everybody has, expert or not. */}
              <PipelineStrip
                events={view.events}
                current={view.phase}
                qaIterations={view.qaIterations}
                status={status}
                live={snapshot.live && !replaying}
              />

              {pending.map((approval) => (
                <ApprovalGate
                  key={approval.id}
                  approval={approval}
                  onResolve={(approved, reason) => resolve(approval.id, approved, reason)}
                />
              ))}

              {!replaying && (
                <RunOutcome
                  run={snapshot.run}
                  events={snapshot.events}
                  artifacts={snapshot.artifacts}
                  onRelaunch={relaunch}
                />
              )}

              <div className="tabs" role="tablist" aria-label="Détail du run">
                {TABS.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    role="tab"
                    id={`tab-${entry.id}`}
                    className="tab"
                    aria-selected={tab === entry.id}
                    aria-controls={`panel-${entry.id}`}
                    onClick={() => setTab(entry.id)}
                  >
                    {entry.label}
                    {entry.id === "artifacts" && view.artifacts.length > 0 && (
                      <span className="tab-count"> ({view.artifacts.length})</span>
                    )}
                  </button>
                ))}
              </div>

              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
                {tab === "timeline" && (
                  <>
                    <Timeline events={view.events} />
                    <div ref={timelineEnd} />
                  </>
                )}
                {tab === "artifacts" && <Artifacts artifacts={view.artifacts} />}
                {tab === "diff" && (
                  <DiffView runId={snapshot.run.id} live={snapshot.live} />
                )}
                {tab === "workspace" && <WorkspaceTree runId={snapshot.run.id} />}
                {tab === "costs" && (
                  <CostTable
                    events={view.events}
                    selfHosted={(view.budget?.cost_usd ?? 0) === 0}
                  />
                )}
              </div>
            </>
          )}
        </main>
      </div>
    </>
  );
}
