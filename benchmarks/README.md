# Benchmarks

Measures what the crew actually delivers, not what it claims. Four tasks on the
demo repository, each scored by **hidden acceptance tests** the crew never sees.

```bash
python benchmarks/harness.py --validate            # check the tasks themselves — no model calls
python benchmarks/harness.py                       # run everything, once
python benchmarks/harness.py --repeat 3            # run everything three times — do this
python benchmarks/harness.py --tasks pagination    # one task
python benchmarks/harness.py --max-tokens 1200000 --max-tool-calls 80   # different ceilings
python benchmarks/harness.py --compare results/BASELINE.json            # judge a change
LLM_PROVIDER=fake python benchmarks/harness.py     # smoke-test the harness, offline and free
```

Results land in `results/latest.md` and `results/latest.json`.

`--max-tokens` and `--max-tool-calls` are harness flags rather than edits to
`.env` because they change *what is being measured*. "Does this task fit in 400k
tokens and 40 tool calls?" and "can the crew do it at all, given room?" are
different questions, and an answer is only meaningful next to the ceilings it
was measured under — so both are recorded in every result file.

Sweeping them is how you find which ceiling actually binds. On `jwt_auth` the
token budget looked like the constraint; raising it revealed the real one was
the per-agent tool-call limit, and the crew had been producing correct code all
along.

## Why hidden tests

A crew that writes its own tests can pass them by writing weak ones. So each
task ships a `hidden_test.py` that is copied into the workspace **only after
the run finishes**. The crew cannot see it, tune to it, or delete it.

A task is judged on two suites:

- **hidden** — did the feature actually get built, to the specified behaviour?
- **own** — is the pre-existing suite still green? A crew that deletes a failing
  test to go green scores `regression`, which is worse than `fail`.

## Scores

| Score | Meaning |
|---|---|
| `pass` | hidden tests green, nothing regressed, run finished cleanly |
| `partial` | some hidden tests green — or all of them, but the run escalated (deliverable there, process not) |
| `regression` | the pre-existing suite is broken. The worst outcome: it damaged working code |
| `fail` | no hidden test passes |

`pass` and `partial` are deliberately separated from run `status`, which stays
its own column. "The code works but the run blew its token budget" and "the run
produced nothing" are different problems with different fixes, and a benchmark
that scores both `fail` cannot tell you which lever to pull.

## Why `--validate` exists

A benchmark whose tests are wrong measures nothing while looking authoritative.
`--validate` proves two properties for every task, without calling a model:

1. the hidden tests **fail** on the untouched template — otherwise the task is
   already satisfied and measures nothing;
2. they **pass** on a reference solution, and that solution does not break the
   pre-existing suite — otherwise the task is unfair, and a failure would say
   more about the tests than about the crew.

It found two real defects when it was first run: `jwt_auth` skipped its whole
file instead of failing when `app/auth.py` was missing (so doing nothing scored
"not applicable"), and its request demanded the existing suite stay green while
adding auth necessarily breaks a suite that writes anonymously — the migration
had to become part of the stated task.

Run `--validate` in CI. It is fast and needs no API key.

## The tasks

| Task | Difficulty | What it exercises |
|---|---|---|
| `tag_validation` | low | field validation, de-duplication with order preserved, applying rules to two routes |
| `pagination` | low–medium | query parameters, a cap that is silent rather than an error, ordering interactions with an existing filter |
| `search` | medium | a new route, plus the FastAPI trap that `/notes/search` must be declared before `/notes/{note_id}` |
| `jwt_auth` | high | a new dependency, a new module with a contracted interface, per-route authorisation, and migrating a suite that writes anonymously |

## Adding a task

```
tasks/<id>/
  request.md        what the user asks for — precise enough that the hidden tests are fair
  hidden_test.py    acceptance tests, copied in after the run
  solution/         reference implementation, mirroring the workspace layout
```

Write `request.md` to pin down every behaviour the hidden tests assert. If a
test checks that an over-large limit is capped rather than rejected, the request
must say so — otherwise the benchmark measures guessing, not capability. Then
run `--validate` before trusting a single number.

## A caveat on the results committed here

Every measurement taken with `--repeat` greater than one, before the fix in
`Un run travaille dans SON dépôt, sur SA branche`, ran with colliding branch
names: the readable part of a branch is the run id prefix plus a slug of the
request, which is identical for every repetition of one task. The second and
third repetitions failed to create their branch, the return code was never
read, and they carried on inside the first one's.

Tokens and tool calls are unlikely to have moved much — the agents work in the
filesystem, not in git — but the run's diff, and therefore the change-size
check handed to QA, was wrong for those repetitions. The figures in
`GREEDY-2x.md` and the documenter comparison should be read with that in mind,
and re-measured before anything is concluded from them.

## What it has actually caught

**A measurement that reversed itself once it was done properly.** The benchmark
showed agents spending tool calls rediscovering the repository layout, so a
static map (routes, classes, functions — built with `ast`, no model) was
injected into every system prompt.

The first measurement said it made things worse, and it shipped off. That
measurement was **one run per task** — and this harness's own rule is that a
difference is real only when the observed ranges do not overlap. With no
repetitions there are no ranges, and `--compare` says so itself: every row
comes back `unrepeated`. It could not support a conclusion in either
direction, including the one it was used for.

Re-measured at **three repetitions per task**, greedy, one server, one process
from end to end, the ranges stopped overlapping and the verdicts became real:

| task | tokens | tool calls | verdict |
|---|---|---|---|
| `tag_validation` | 404k -> 241k (**-40%**) | 41 -> 29 (-29%) | better, and 0/3 -> 3/3 passing |
| `pagination` | 234k -> 206k (-12%) | 31 -> 27 (-13%) | better |
| `search` | 294k -> 271k | 40 -> 32 (-20%) | fewer tool calls; tokens indistinguishable |
| `jwt_auth` | 331k -> 408k (**+24%**) | 47 -> 49 | **worse** |

| | tokens | tool calls | tasks passing every repetition |
|---|---:|---:|:---:|
| without the map | 3,790,052 | 467 | 2/4 |
| with the map | **3,392,329** | **414** | **3/4** |

So it ships **on** (`REPO_MAP_ENABLED=true`).

**The exception is not a rounding error.** `jwt_auth` has the longest
conversation of the four, and the map's per-turn context cost pushes it from
290-337k tokens to 406-427k — straight through the 400k ceiling, turning three
passes into three escalations. A task with that much back-and-forth needs a
larger budget, or this switched off.

**What this measurement does not show.** It predates the change that keeps
volatile values — pytest durations, git object names — out of the model's own
conversation, so the runs still diverge from one another: `jwt_auth` without
the map spans 290–337k tokens across three repetitions, a 16% spread. The
comparison holds because both passes ran in one process under identical
conditions, not because the runs were reproducible. Re-running it with that
change active should tighten every range, and is worth doing.

The lesson is about the instrument, not the feature: a plausible optimisation
was rejected on evidence that never existed, and only a repeated measurement
could say so.

That is what this harness is for — and it cuts both ways. It was used once to
refuse a change that sounded right, and once to accept the same change after
the refusal turned out to rest on nothing. A single run per task is an
anecdote; `--repeat 3` is the smallest thing that can disagree with you.

**Run-to-run variance is large and must be respected.** `pagination` scored
11/11, then 3/11, then 11/11 on the same code with the same settings.

That is why `--repeat N` and `--compare` exist, and why the comparison rule is
mechanical rather than left to judgement:

> A difference is only called real when the two observed **ranges do not
> overlap**. One run per side is reported as `unrepeated` no matter how large
> the gap.

Run the comparison above through it and every row comes back `unrepeated` —
including the +317% one. That is the correct answer, and it is the answer the
tool gives whether or not it is the one you were hoping for. It is easy, having
just spent an afternoon on a change, to look at 181 → 240 and narrate a reason;
encoding the rule removes that opportunity.

A task whose repetitions disagree is marked **flaky** in the report. Knowing
which tasks are flaky matters more than any single score: tuning against a
flaky task measures the dice.

## Floor and ceiling

`LLM_PROVIDER=fake` is the floor: it changes nothing, so only the hidden tests
asserting unchanged behaviour pass. Any real model must beat it. The reference
solutions are the ceiling — `--validate` proves every task is reachable.
