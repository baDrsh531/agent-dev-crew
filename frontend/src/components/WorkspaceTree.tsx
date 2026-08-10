import { useEffect, useState } from "react";
import { api } from "../api";
import type { WorkspaceListing } from "../types";

interface Node {
  name: string;
  path: string;
  touched: boolean;
  children: Map<string, Node>;
}

function build(files: { path: string; touched: boolean }[]): Node {
  const root: Node = { name: "", path: "", touched: false, children: new Map() };
  for (const file of files) {
    let node = root;
    const parts = file.path.split("/");
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let child = node.children.get(part);
      if (!child) {
        child = { name: part, path, touched: false, children: new Map() };
        node.children.set(part, child);
      }
      // A directory is marked as touched when anything under it is, so a
      // collapsed tree still shows where to look.
      if (file.touched) child.touched = true;
      node = child;
    });
  }
  return root;
}

function Branch({ node, depth }: { node: Node; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const isFile = node.children.size === 0;

  if (isFile) {
    return (
      <li className={`tree-file ${node.touched ? "touched" : ""}`} style={{ paddingLeft: depth * 14 }}>
        <span className="tree-icon" aria-hidden="true">·</span>
        <span className="tree-name">{node.name}</span>
        {node.touched && <span className="tree-badge">modifié</span>}
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        className={`tree-dir ${node.touched ? "touched" : ""}`}
        style={{ paddingLeft: depth * 14 }}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="chevron" data-open={open} aria-hidden="true">⌄</span>
        <span className="tree-name">{node.name}/</span>
        {node.touched && <span className="tree-badge">modifié</span>}
      </button>
      {open && (
        <ul className="tree-list">
          {[...node.children.values()]
            .sort((a, b) => {
              const aDir = a.children.size > 0;
              const bDir = b.children.size > 0;
              // Directories first: it is the order a file browser trained
              // everyone to expect, and it keeps files from hiding between them.
              if (aDir !== bDir) return aDir ? -1 : 1;
              return a.name.localeCompare(b.name);
            })
            .map((child) => (
              <Branch key={child.path} node={child} depth={depth + 1} />
            ))}
        </ul>
      )}
    </li>
  );
}

/**
 * The run's workspace, as the agents were allowed to see it.
 *
 * Path containment is an architectural claim in this project — a model-supplied
 * path is canonicalised and refused if it escapes — and a claim that cannot be
 * seen is a claim nobody can check. So this lists through the same Sandbox the
 * tools go through, and names what it will not show rather than omitting it
 * silently.
 */
export function WorkspaceTree({ runId }: { runId: string }) {
  const [listing, setListing] = useState<WorkspaceListing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setListing(null);
    setError(null);
    api
      .workspace(runId)
      .then((l) => alive && setListing(l))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [runId]);

  if (error) {
    return (
      <div className="notice bad">
        <h4>Le workspace n'a pas pu être lu</h4>
        <p>{error}</p>
      </div>
    );
  }
  if (!listing) return <p className="empty">Lecture du workspace…</p>;
  if (!listing.available) {
    return (
      <div className="notice info">
        <h4>Workspace indisponible</h4>
        <p>{listing.reason ?? "Ce run n'a pas de checkout."}</p>
      </div>
    );
  }

  const touched = listing.files.filter((f) => f.touched).length;
  const tree = build(listing.files);

  return (
    <div className="workspace">
      <div className="workspace-head">
        <div>
          <strong>{listing.files.length} fichiers</strong>
          {touched > 0 && <span className="tree-badge"> {touched} modifiés par ce run</span>}
        </div>
        <code>{listing.root}</code>
      </div>

      <ul className="tree-list root">
        {[...tree.children.values()]
          .sort((a, b) => {
            const aDir = a.children.size > 0;
            const bDir = b.children.size > 0;
            if (aDir !== bDir) return aDir ? -1 : 1;
            return a.name.localeCompare(b.name);
          })
          .map((child) => (
            <Branch key={child.path} node={child} depth={0} />
          ))}
      </ul>

      <p className="workspace-note">
        Cette liste passe par le même bac à sable que les agents. Ce qui n'y
        figure pas leur est également invisible&nbsp;:{" "}
        {listing.blocked?.map((b) => <code key={b}>{b}</code>).reduce(
          (acc: any, el, i) => (i === 0 ? [el] : [...acc, ", ", el]),
          [],
        )}
        .
      </p>
    </div>
  );
}
