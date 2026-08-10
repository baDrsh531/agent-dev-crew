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

## What it has actually caught

**A plausible optimisation that made things worse.** The benchmark showed agents
spending tool calls rediscovering the repository layout, so a static map
(routes, classes, functions — built with `ast`, no model) was injected into
every system prompt. Measured over the four tasks under identical ceilings:

| | tool calls | tokens | passes |
|---|---:|---:|---:|
| without the map | 181 | 1,494,789 | 3/4 |
| with the map | 240 | 2,358,223 | 3/4 |
| | **+33%** | **+58%** | unchanged |

Split by task, the two simple ones improved and the two hard ones blew up —
plausibly because the extra context pushes a 65k-window model into re-reading.

**Read those totals with the caveat they deserve.** They are one run per task,
and this harness's own rule is that a difference is real only when the observed
ranges do not overlap. With no repetitions there are no ranges, and
`--compare` says so itself — every row comes back `unrepeated`, the verdict
`indistinguishable`. So the honest reading is not "the map costs 58% more
tokens"; it is **"there is no evidence the map helps"**.

That is still enough to decide. The feature is kept but **off by default**
(`REPO_MAP_ENABLED=false`), because without evidence that a change helps, the
default that changes nothing is the one to ship. Re-measuring it under
`--repeat 3` and greedy decoding would settle it properly.

That is what this harness is for. Without it the change would have shipped,
because the reasoning behind it was sound.

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
