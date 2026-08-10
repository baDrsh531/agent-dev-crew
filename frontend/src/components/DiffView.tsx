import { useEffect, useState } from "react";
import { api } from "../api";
import { parseDiff, totals, type DiffFile } from "../diff";
import type { DiffResponse } from "../types";

function FileBlock({ file, openByDefault }: { file: DiffFile; openByDefault: boolean }) {
  const [open, setOpen] = useState(openByDefault);
  return (
    <div className="diff-file">
      <button
        type="button"
        className="diff-file-head"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="chevron" data-open={open} aria-hidden="true">⌄</span>
        <code className="diff-path">
          {file.oldPath && <span className="diff-old-path">{file.oldPath} → </span>}
          {file.path}
        </code>
        <span className="diff-counts">
          <span className="diff-add">+{file.added}</span>
          <span className="diff-del">−{file.removed}</span>
        </span>
      </button>

      {open && (
        <div className="diff-body">
          {file.binary ? (
            <p className="empty" style={{ padding: "10px 14px" }}>
              Fichier binaire — pas de diff textuel.
            </p>
          ) : (
            <pre>
              {file.lines.map((line, i) => (
                <div key={i} className={`diff-line ${line.kind}`}>
                  <span className="diff-marker" aria-hidden="true">
                    {line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}
                  </span>
                  <span>{line.text || " "}</span>
                </div>
              ))}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The run's changes, grouped by file.
 *
 * Fetched on demand rather than carried in the snapshot: a diff is large, most
 * of the time nobody opens this tab, and it is recomputed from git anyway so
 * there is nothing to keep in sync.
 */
export function DiffView({ runId, live }: { runId: string; live: boolean }) {
  const [state, setState] = useState<DiffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setState(null);
    setError(null);
    api
      .diff(runId)
      .then((d) => alive && setState(d))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [runId]);

  if (error) {
    return (
      <div className="notice bad">
        <h4>Le diff n'a pas pu être récupéré</h4>
        <p>{error}</p>
      </div>
    );
  }
  if (!state) return <p className="empty">Lecture du diff…</p>;

  if (!state.available) {
    return (
      <div className="notice info">
        <h4>Pas de diff à montrer</h4>
        <p>{state.reason ?? "Ce run n'a rien modifié."}</p>
      </div>
    );
  }

  const files = parseDiff(state.diff);
  if (files.length === 0) {
    return (
      <p className="empty">
        {live
          ? "Aucun fichier modifié pour l'instant — le diff apparaîtra dès la première écriture."
          : "Ce run n'a modifié aucun fichier."}
      </p>
    );
  }

  const sum = totals(files);
  // Small changes are more useful open; a twenty-file changeset is more useful
  // as a list you can scan before choosing what to read.
  const openByDefault = files.length <= 3;

  return (
    <div className="diff">
      <div className="diff-summary">
        <strong>
          {files.length} fichier{files.length > 1 ? "s" : ""}
        </strong>
        <span className="diff-add">+{sum.added}</span>
        <span className="diff-del">−{sum.removed}</span>
        {state.branch && <code>{state.branch}</code>}
        {state.truncated && (
          <span className="diff-truncated">
            diff tronqué — les derniers fichiers peuvent manquer
          </span>
        )}
      </div>
      {files.map((file) => (
        <FileBlock key={file.path} file={file} openByDefault={openByDefault} />
      ))}
    </div>
  );
}
