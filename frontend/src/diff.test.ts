import { describe, expect, it } from "vitest";
import { parseDiff, totals } from "./diff";

/**
 * The parser's contract is narrow and absolute: **it must never show less than
 * the diff contains**. A renderer that silently drops a removed line is worse
 * than no renderer, because it is the one thing a reviewer trusts it for.
 *
 * The first two cases here are regressions. Both shipped, and neither looked
 * broken — which is the point of writing them down.
 */

const HEADER = "diff --git a/app/main.py b/app/main.py\nindex 0b98788..62820a4 100644\n--- a/app/main.py\n+++ b/app/main.py\n";

describe("parseDiff", () => {
  it("reads the file path and counts additions and removals", () => {
    const [file] = parseDiff(`${HEADER}@@ -1,3 +1,3 @@\n context\n-old\n+new\n+extra\n`);

    expect(file.path).toBe("app/main.py");
    expect(file.removed).toBe(1);
    expect(file.added).toBe(2);
  });

  it("keeps a removed line that starts with a comment marker", () => {
    // `-- name` removed renders as `--- name`, which the header test used to
    // swallow: the line disappeared from the view *and* from the count. SQL,
    // Lua, Haskell and Ada all write comments this way.
    const [file] = parseDiff(`${HEADER}@@ -1,2 +1,1 @@\n keep\n-- a SQL comment\n`);

    expect(file.removed).toBe(1);
    expect(file.lines.some((l) => l.kind === "del" && l.text === "- a SQL comment")).toBe(true);
  });

  it("keeps an added line that starts with two plus signs", () => {
    const [file] = parseDiff(`${HEADER}@@ -1,1 +1,2 @@\n keep\n++ still content\n`);

    expect(file.added).toBe(1);
    expect(file.lines.some((l) => l.kind === "add" && l.text === "+ still content")).toBe(true);
  });

  it("still treats the real --- and +++ lines as headers", () => {
    // The fix must not overshoot: before the first hunk these are headers and
    // counting them would inflate every file by one add and one removal.
    const [file] = parseDiff(`${HEADER}@@ -1,1 +1,1 @@\n unchanged\n`);

    expect(file.added).toBe(0);
    expect(file.removed).toBe(0);
  });

  it("splits a multi-file diff and keeps each file's own counts", () => {
    const second = "diff --git a/app/new.py b/app/new.py\n--- /dev/null\n+++ b/app/new.py\n@@ -0,0 +1,2 @@\n+one\n+two\n";
    const files = parseDiff(`${HEADER}@@ -1,1 +1,1 @@\n-gone\n${second}`);

    expect(files.map((f) => f.path)).toEqual(["app/main.py", "app/new.py"]);
    expect(files[0].removed).toBe(1);
    expect(files[1].added).toBe(2);
  });

  it("reports a rename with both paths", () => {
    const renamed = "diff --git a/old/name.py b/new/name.py\nsimilarity index 98%\nrename from old/name.py\nrename to new/name.py\n";
    const [file] = parseDiff(renamed);

    expect(file.path).toBe("new/name.py");
    expect(file.oldPath).toBe("old/name.py");
  });

  it("marks a binary file rather than pretending it has lines", () => {
    const [file] = parseDiff(
      "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n",
    );

    expect(file.binary).toBe(true);
    expect(file.lines).toHaveLength(0);
  });

  it("keeps hunk headers so the reader can see where they are", () => {
    const [file] = parseDiff(`${HEADER}@@ -22,7 +22,7 @@ def health():\n context\n`);
    expect(file.lines[0]).toEqual({ kind: "meta", text: "@@ -22,7 +22,7 @@ def health():" });
  });

  it("survives an empty or absent diff without throwing", () => {
    expect(parseDiff("")).toEqual([]);
    expect(parseDiff(undefined as unknown as string)).toEqual([]);
  });

  it("ignores anything before the first file header", () => {
    expect(parseDiff("stray text\n+not a real addition\n")).toEqual([]);
  });
});

describe("totals", () => {
  it("sums every file", () => {
    const files = parseDiff(
      `${HEADER}@@ -1,1 +1,2 @@\n-a\n+b\n+c\n` +
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-d\n",
    );
    expect(totals(files)).toEqual({ added: 2, removed: 2 });
  });

  it("is zero for no files rather than NaN", () => {
    expect(totals([])).toEqual({ added: 0, removed: 0 });
  });
});
