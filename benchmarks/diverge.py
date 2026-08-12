"""Find where two runs of the same task stopped agreeing.

Repetitions of one benchmark task should produce the same conversation, and
when they do not, the useful question is not *how much* they differ but
*where they first did* — everything after that point is a consequence.

    python benchmarks/diverge.py search
    python benchmarks/diverge.py jwt_auth --db data/benchmarks.db

It compares what the model actually read, which is not what the event log
stores. The log deliberately keeps raw tool output — a log that recorded a
placeholder would stop being a record — while the conversation receives the
copy with volatile values removed. Comparing the log instead of the
conversation makes every run look like it diverged on a pytest duration,
which is exactly the false trail this script was written to stop following.

What it has found so far:

* a pytest duration (`7 passed in 2.03s`) reaching the model, which moved the
  first divergence from exchange 40 to 86 once removed;
* git object names, structurally unrepeatable since the commit timestamp is
  part of the hash;
* and, once both were gone, the model's own reasoning diverging from an
  identical prefix — which is the inference server's non-determinism, not
  the harness's, and is what repetitions exist to absorb.
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.tools.determinism import stabilise  # noqa: E402

Exchange = tuple[str, str, str]


def conversation(db: sqlite3.Connection, run_id: str) -> list[Exchange]:
    """The exchanges as the model saw them, in order."""
    rows = db.execute(
        "SELECT type, payload FROM events WHERE run_id = ? AND type IN "
        "('agent.message', 'tool.requested', 'tool.executed') ORDER BY seq",
        (run_id,),
    )
    out: list[Exchange] = []
    for row in rows:
        payload = json.loads(row["payload"])
        if row["type"] == "agent.message":
            out.append(("the model says", payload.get("kind", ""), payload.get("text", "")))
        elif row["type"] == "tool.requested":
            out.append((
                "the model calls", payload.get("tool", ""),
                json.dumps(payload.get("input"), sort_keys=True),
            ))
        else:
            # Stabilised, because that is the form the model was given.
            out.append((
                "a tool answers", payload.get("tool", ""),
                stabilise(str(payload.get("output", ""))),
            ))
    return out


def latest_runs(db: sqlite3.Connection, task: str, count: int) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT id, tokens_used, created_at FROM runs WHERE title = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (f"benchmark:{task}", count),
    ).fetchall()


def report(left: list[Exchange], right: list[Exchange], context: int) -> int:
    """Print the first difference. Returns the exchange number, or 0 if none."""
    for i, (a, b) in enumerate(itertools.zip_longest(left, right), start=1):
        if a is None or b is None:
            longer = "the first" if b is None else "the second"
            print(f"  identical for {i - 1} exchanges, then {longer} run continues alone")
            return i
        if a == b:
            continue
        print(f"  first divergence at exchange {i} — {a[0]} ({a[1]})")
        if (a[0], a[1]) != (b[0], b[1]):
            print(f"    left  : {a[0]} ({a[1]})")
            print(f"    right : {b[0]} ({b[1]})")
            return i
        for line in difflib.unified_diff(
            a[2].splitlines(), b[2].splitlines(), "left", "right", n=context, lineterm=""
        ):
            if line.startswith(("+++", "---", "@@")):
                continue
            print(f"    {line[:170]}")
        return i
    print(f"  identical throughout — {len(left)} exchanges, byte for byte")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("task", help="benchmark task id, e.g. search")
    parser.add_argument("--db", default="data/benchmarks.db")
    parser.add_argument("--runs", type=int, default=3,
                        help="how many of the most recent runs to compare pairwise")
    parser.add_argument("--context", type=int, default=0,
                        help="lines of context around the differing text")
    args = parser.parse_args(argv)

    path = Path(args.db)
    if not path.is_file():
        print(f"no database at {path}")
        return 1

    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row

    runs = latest_runs(db, args.task, args.runs)
    if len(runs) < 2:
        print(f"need at least two runs of {args.task!r}; found {len(runs)}")
        return 1

    print(f"{args.task}: {len(runs)} most recent runs")
    for r in runs:
        print(f"  {r['id'][-6:]}  {r['tokens_used']:>9,} tokens  {r['created_at'][:19]}")
    print()

    for a, b in itertools.combinations(runs, 2):
        print(f"{a['id'][-6:]} vs {b['id'][-6:]}"
              f"  ({a['tokens_used']:,} vs {b['tokens_used']:,} tokens)")
        report(conversation(db, a["id"]), conversation(db, b["id"]), args.context)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
