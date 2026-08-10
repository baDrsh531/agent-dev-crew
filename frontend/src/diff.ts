/**
 * Parse a unified diff into files and lines.
 *
 * Written by hand rather than pulled in as a dependency: the input is git's
 * own output, the shapes that matter are few, and a parser small enough to
 * read is small enough to trust. What it must not do is silently drop a line —
 * anything it does not recognise is kept as context so the rendered diff can
 * never be shorter than the real one.
 */

export type LineKind = "add" | "del" | "context" | "meta";

export interface DiffLine {
  kind: LineKind;
  text: string;
}

export interface DiffFile {
  path: string;
  /** Set when git reports a rename; the path above is the destination. */
  oldPath?: string;
  added: number;
  removed: number;
  binary: boolean;
  lines: DiffLine[];
}

const FILE_HEADER = /^diff --git a\/(.+?) b\/(.+)$/;

function pathsOf(header: string): { from: string; to: string } | null {
  const match = FILE_HEADER.exec(header);
  return match ? { from: match[1], to: match[2] } : null;
}

/** Headers git emits between the file header and the first hunk. */
const PREAMBLE = [
  "index ", "new file", "deleted file", "old mode", "new mode",
  "similarity index", "rename ",
];

export function parseDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  // `--- ` and `+++ ` are file headers *before* the first hunk and ordinary
  // content after it — the marker character is the same either way. Treating
  // them as headers everywhere meant removing a line that starts with `-- `
  // (a SQL, Lua or Haskell comment) produced `--- foo`, which was swallowed:
  // the line vanished from the diff and from the count. This flag is the whole
  // difference between the two readings.
  let inHunk = false;

  for (const raw of (text ?? "").split("\n")) {
    const header = pathsOf(raw);
    if (header) {
      current = {
        path: header.to,
        oldPath: header.from !== header.to ? header.from : undefined,
        added: 0,
        removed: 0,
        binary: false,
        lines: [],
      };
      files.push(current);
      inHunk = false;
      continue;
    }
    if (!current) continue;

    if (raw.startsWith("Binary files")) {
      current.binary = true;
      continue;
    }
    if (!inHunk && (PREAMBLE.some((p) => raw.startsWith(p)) ||
                    raw.startsWith("--- ") || raw.startsWith("+++ "))) {
      continue;
    }
    if (raw.startsWith("@@")) {
      current.lines.push({ kind: "meta", text: raw });
      inHunk = true;
      continue;
    }
    if (raw.startsWith("+")) {
      current.added += 1;
      current.lines.push({ kind: "add", text: raw.slice(1) });
      continue;
    }
    if (raw.startsWith("-")) {
      current.removed += 1;
      current.lines.push({ kind: "del", text: raw.slice(1) });
      continue;
    }
    current.lines.push({ kind: "context", text: raw.startsWith(" ") ? raw.slice(1) : raw });
  }

  // A trailing empty line from the final split is not part of the last file.
  for (const file of files) {
    while (file.lines.length && file.lines.at(-1)!.text === "" &&
           file.lines.at(-1)!.kind === "context") {
      file.lines.pop();
    }
  }
  return files;
}

export function totals(files: DiffFile[]): { added: number; removed: number } {
  return files.reduce(
    (acc, f) => ({ added: acc.added + f.added, removed: acc.removed + f.removed }),
    { added: 0, removed: 0 },
  );
}
