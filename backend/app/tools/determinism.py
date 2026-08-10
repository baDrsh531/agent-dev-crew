"""Keep volatile values out of the model's own conversation.

A run is only reproducible if the same inputs recur, and an agent's inputs are
mostly *its own tool results*. Comparing two repetitions of one benchmark task
event by event showed the model producing thirty-nine byte-identical exchanges
and then diverging — not because it sampled differently, but because
`run_tests` came back with `7 passed in 2.03s` on one side and `in 1.34s` on
the other. Everything after that point is a different conversation.

Three classes of value cannot repeat, measured over 2,503 real tool outputs:

* **durations** — 7% of outputs, almost all from `run_tests`;
* **git object names** — 4%, and structurally impossible to reproduce, since
  the commit timestamp is part of what is hashed;
* absolute paths — 7%, but stable when the workspace is, so left alone rather
  than normalised on suspicion.

This is applied to the copy handed back to the model and to nothing else. The
event log keeps the real output: a log that recorded a placeholder instead of
what a tool actually printed would stop being a record of the run.

The substitutions are deliberately narrow. Blanking every 7-to-40 character
hex run would also mangle colour literals, UUIDs and checksums that are part
of the code under test — turning a determinism fix into a corruption bug.
"""

from __future__ import annotations

import re

# `7 passed, 1 warning in 2.03s` — pytest, and anything else reporting a wall
# clock. The unit is kept so the sentence still reads as a duration.
_DURATION = re.compile(r"\bin \d+(?:\.\d+)?s\b")

# `Committed 6ebc4f4: <message>` — the shape this project's own git tool emits.
# Not anchored to the start of a line: the same text arrives indented, quoted
# inside another tool's output, or read back out of a file, and an anchor that
# only matched the pristine case left the hash in every other one.
_COMMITTED = re.compile(r"\bCommitted [0-9a-f]{7,40}:")

# `index 0b98788..62820a4 100644` — git's own diff header. The two dots and the
# pair of object names are what make this specific; `index` alone is not.
_DIFF_INDEX = re.compile(r"\bindex [0-9a-f]{7,40}\.\.[0-9a-f]{7,40}")

PLACEHOLDER_DURATION = "in <duration>"
PLACEHOLDER_COMMIT = "Committed <commit>:"
PLACEHOLDER_INDEX = "index <before>..<after>"


def stabilise(text: str) -> str:
    """Replace values that cannot recur, leaving everything else untouched."""
    if not text:
        return text
    text = _DURATION.sub(PLACEHOLDER_DURATION, text)
    text = _COMMITTED.sub(PLACEHOLDER_COMMIT, text)
    return _DIFF_INDEX.sub(PLACEHOLDER_INDEX, text)
