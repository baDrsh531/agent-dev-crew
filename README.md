# Agent Dev Crew

A simulated software team. Five specialised agents — Business Analyst, Software
Architect, Developer, QA Engineer, Documentation Writer — hand **typed
artifacts** to one another under a **deterministic orchestrator**, each with its
own tool permissions, inside a confined workspace, with human approval gates on
anything hard to reverse.

The interesting part is not that five agents talk to each other. It is that the
collaboration is *engineered*: schema-validated hand-offs, a state machine
instead of a model deciding what happens next, least privilege per role, and a
repair loop that is provably bounded.

```
                              ┌──────────────────────────┐
       user request ─────────▶│  Orchestrator (in code)  │
                              └────────────┬─────────────┘
                                           │
   ANALYZE ──▶ DESIGN ──▶ [human gate] ──▶ IMPLEMENT ──▶ REVIEW ──▶ DOCUMENT ──▶ DONE
      │           │                            ▲            │
   Analyst    Architect                        └─── FIX ◀────┘   bounded: max 3 loops
    spec        plan                          Developer      QA
                                                             │
                                              any limit hit ──▶ ESCALATED
```

---

## What makes it more than a demo

**1. Typed hand-offs, not prose.** Each agent emits a Pydantic artifact whose
JSON Schema is sent to the API as `output_config.format`, so a malformed
hand-off is rejected before it reaches our code. The spec's user-story ids flow
into the plan's `covers`, which QA checks against for `uncovered_stories` — the
chain is verifiable, not narrative. See
[`backend/app/domain/artifacts.py`](backend/app/domain/artifacts.py).

**2. The Project Manager is a state machine, not a model.** Models do the
cognitive work inside nodes; they never choose the next node. That makes the
run inspectable and testable — every transition below is covered by a test in
[`backend/tests/test_orchestrator.py`](backend/tests/test_orchestrator.py).

**3. Least privilege per role.** Capability is a property of the role, not of a
prompt telling an agent to behave. The analyst *cannot* write a file, because
`write_file` is absent from its tool list; a call to it comes back as an error
the model must adapt to.

| Role | read/search | write | shell | git commit | run tests |
|---|:--:|:--:|:--:|:--:|:--:|
| Business Analyst | ✅ | ❌ | ❌ | ❌ | ❌ |
| Software Architect | ✅ | ❌ | ❌ | ❌ | ❌ |
| Developer | ✅ | 🔶 approval | 🔶 approval | 🔶 approval | ✅ |
| QA Engineer | ✅ | ❌ | ❌ | ❌ | ✅ |
| Documentation Writer | ✅ | 🔶 `*.md` / `docs/` only | ❌ | ❌ | ❌ |

**4. Every limit is a ceiling, not a hint.** Token budget, wall clock, tool
calls per agent, and QA repair iterations. Crossing one ends the run in
`ESCALATED` with the reason recorded — never in a silent loop. Time spent
waiting on a human is explicitly excluded from the clock.

**5. Reversible by construction.** Each run works on its own `agent/<id>-<slug>`
branch from a recorded base commit, in a scratch workspace copied from the
pristine demo repo. A bad run is a `git reset` or a directory delete.

**6. Confinement is tested adversarially.** Every model-supplied path goes
through `Sandbox.resolve()`; every command through an executable allowlist that
refuses shell metacharacters outright. The tests assert what is *refused*.

**7. Event-sourced.** Every fact is appended to SQLite before it is acted on, so
the UI is a projection, a reconnecting client backfills by sequence number, and
a finished run can be replayed.

**8. Cost is first-class.** Per-role model routing (Opus for design, Sonnet for
implementation, Haiku for documentation), prompt caching on the system prefix,
and per-agent token/cost accounting surfaced in the UI.

**9. The provider is swappable.** Agents talk to an `LLMClient` protocol, never
to an SDK. That is what let a local llama.cpp server be added as a provider
without touching a single agent, tool or orchestration file — including working
around two incompatibilities in its API (see *Running against a local model*).

**10. It is measured, not asserted.** Four benchmark tasks scored by hidden
acceptance tests the crew never sees, plus a `--validate` mode that proves the
tasks themselves are neither trivial nor unfair. See
[`benchmarks/`](benchmarks/README.md).

It has already earned its cost, and in a more interesting way than a slogan.
A plausible optimisation — injecting a static map of the repository into every
prompt to save exploration tool calls — summed **worse** over the four tasks:
240 tool calls against 181, 2.36M tokens against 1.49M, for the same number of
passes. But that was one run per task, and the harness's own rule is that a
difference is real only when the observed ranges do not overlap; with no
repetitions `--compare` reports every row as `unrepeated`. So the finding is
not "the map costs 58% more" — it is **"there is no evidence the map helps"**,
which is still enough to ship it disabled. Without the harness it would have
shipped on, because the reasoning behind it was sound.

**11. The user talks in their own words.** A run starts with intake: an agent
restates the request in plain language, proposes what it will do, and asks at
most three clarifications *with the answer it intends to assume* — so one click
confirms and only the wrong parts need correcting. The engineering team works
from its precise rewrite, and the run ends with a diff explained in prose and a
three-block report (what changed, what was verified, what to watch).

**12. Autonomy is a dial, not a checkbox.** Three settings, per run rather than
global. The middle one — *ask me only when it cannot be undone* — rests on a
criterion that can be checked instead of argued about: a run works on its own
git branch from a recorded commit, so **anything `git reset` undoes is
reversible**. Editing a file is; `pip install` is not, because its effects
outlive the branch. That makes the label a promise the system can keep, and it
lives in one function so the engine, the API and the UI cannot disagree about it.

**12b. Each run gets its own checkout, so undo is a delete.** A run works in
its own git worktree — its own files, its own branch, the same object store.
Two consequences worth the plumbing: runs no longer have to be sequential,
because they do not share a working tree; and *discard this run* removes a
directory and a branch rather than reverting commits out from under whatever
else was standing on them. Resetting the workspace removes every checkout
first, since deleting the base `.git` would otherwise strand them all.

**12c. Several model servers, one run each.** `OPENAI_BASE_URL` takes a list.
The routing unit is the *run*, not the request: a local server caches the
prompt prefix, and every turn of a run shares all but its tail with the
previous one, so a run is pinned to one server for its whole life. Balancing
individual requests would spread each conversation across every server and
leave all their caches cold. A server that cannot answer leaves the rotation
for a cooldown and the call moves — but only for a transport failure or a 5xx;
a 400 is the request's own fault and retrying it elsewhere would hide a bug
behind a failover. `benchmarks/harness.py --concurrency N` uses this to run N
tasks at once, each in its own worktree on its own server.

The mirror-image case has its own setting. `OPENAI_ROLE_ENDPOINTS` sends named
roles to a server running a *different* model — a small fast one for mechanical
work, keeping the big one for the phases that need reasoning. The two rules
compose in one function, `lease_client()`, because getting that composition
wrong the obvious way (lease a server, then ignore the role routes) would
silently send the documenter to the big model and nothing would look broken.
Whether a smaller model is good enough for a role is a benchmark question, not
an assumption; `/api/health/endpoints` reports the routing either way.

**13. Two readings of the same run.** Simple mode — the default — shows the
request, the dial, and what the team produced. Expert mode adds the phase
pipeline, the budgets, the collaboration timeline and the permission matrix.
Same engine; the difference is whose concerns are on screen.

**14. Any finished run can be watched back.** Play, pause, scrub, ×1 to ×40.
Playback follows the run's own timing, so the pause while an agent thinks and
the burst while it calls three tools read as they happened. It cost almost
nothing to build because the UI was already a projection of the event log —
replay is that same projection over a truncated list, not a second
implementation.

**15. An interrupted run is not a lost run.** The resume point is *derived* from
the persisted artifacts, so a crash costs the phase that was in flight and
nothing more. Any finished run can also be replayed against the orchestration
for free — see *Resume and replay*.

---

## Running it

### Requirements
Python 3.11+, Node 18+, git.

### Windows — one script

```bat
start.bat
```

Double-click it, or run it from a terminal. On first launch it creates the
virtual environment, installs both dependency sets and copies `.env.example` to
`.env`; afterwards it skips straight to launching.

**One process, one port, one window: http://127.0.0.1:8000.** The interface is
built once and served by the API itself. Two servers on two ports was an
accident of how this was developed, not a design — it meant two things to
start, two to stop, one of them able to die unnoticed, and CORS to configure
for a UI that is not actually cross-origin.

| Command | Effect |
|---|---|
| `start.bat` | Build the UI, then serve everything on port 8000 |
| `start.bat api` | API only, skip the UI build (opens `/docs`) |
| `start.bat dev` | Add Vite hot reload on its own port, for editing the UI |
| `start.bat setup` | Install dependencies, launch nothing |
| `stop.bat` | Stop it and verify the ports are free |

Closing the server window stops everything; `stop.bat` exists for the case
where a worker outlives its console and keeps a port bound.

`--reload` is deliberately off by default: it runs uvicorn as a supervisor plus
a worker child, and a closed console can leave the child holding port 8000. Use
`start.bat dev` when you are editing backend code.

### Manual — any platform

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt

cp .env.example .env            # then set ANTHROPIC_API_KEY

cd frontend && npm install && npm run build && cd ..

cd backend
uvicorn app.main:app --port 8000     # UI and API both on http://127.0.0.1:8000
```

While working on the interface, run Vite alongside for hot reload — it proxies
`/api` to the backend, so it is still one API:

```bash
cd frontend && npm run dev           # http://localhost:5173
```

### Providers

Set `LLM_PROVIDER` in `.env`. A provider whose settings are incomplete falls
back to `fake` **at startup** rather than failing halfway through a run.

| Provider | Needs | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | Per-role model routing, adaptive thinking, native structured outputs |
| `openai_compatible` | `OPENAI_BASE_URL`, `OPENAI_MODEL` | Any `/v1/chat/completions` server: llama.cpp, vLLM, SGLang, LM Studio, Ollama |
| `fake` | nothing | Synthesises schema-valid artifacts. Offline, deterministic, free — the whole test suite runs on it |

With `fake`, orchestration, gates, permissions, the event stream and the UI are
all real and exercisable; only the artifact *contents* are placeholders.

### Running against a local model

Verified end to end against a llama.cpp server running **Qwen3.6-35B-A3B**
(GGUF Q4_K_M, 65k context):

```ini
LLM_PROVIDER=openai_compatible
OPENAI_BASE_URL=http://127.0.0.1:8080/v1
OPENAI_MODEL=E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf
OPENAI_ENABLE_THINKING=true
OPENAI_MAX_CONTEXT_TOKENS=65536
```

A full run — *"add limit/offset pagination to GET /notes, cap limit at 100, keep
the tag filter working"* — produced a spec with 2 user stories, a 3-step plan,
a working implementation across 3 files, 10 new tests, and a QA pass verified
independently (17/17 green). **178s, 175k tokens, 34 tool calls, 0 repair
iterations, $0.**

Three findings from probing that server shaped
[`openai_client.py`](backend/app/llm/openai_client.py), and they generalise to
most local servers:

1. **Its Anthropic-compatible `/v1/messages` silently drops
   `output_config.format`** — it answers `200` with prose instead of the
   requested JSON. A partial shim that fails *silently* is worse than none, so
   the provider targets `/v1/chat/completions`, where `response_format` is
   enforced by grammar-constrained decoding. That is a *stronger* guarantee than
   the hosted API's: the tokens cannot leave the grammar.
2. **Grammar-constrained decoding and tool calling are mutually exclusive.**
   With a grammar active the model cannot emit `tool_calls` — it fills the
   schema with nonsense instead. Hence a two-phase completion: explore with
   tools and no grammar, then emit the artifact under the grammar with no tools.
   Both phases are billed.
3. **Reasoning arrives in `reasoning_content`,** and `thinking: {"type":
   "disabled"}` is ignored; the Qwen3 toggle is `chat_template_kwargs`.
   Reasoning is mapped to a `thinking` block so the timeline looks the same
   whichever provider is running.

4. **Sampling has to be pinned, or the server picks for you.** Sending no
   `temperature` does not mean "deterministic" — it means the server applies
   its own, and three identical requests came back as three different plans.
   That noise was most of this project's measured run-to-run variance, and it
   was self-inflicted. `temperature=0` made the same requests byte-identical.
   Production keeps the model's recommended sampling; benchmarks pin it to 0
   so a comparison measures the change rather than the dice.

Per-role model routing is Anthropic-only — one local server serves one model,
so every role shares it rather than showing a fictional model name in the UI.
Cost is reported as `$0` for self-hosted models instead of being guessed at
hosted rates.

### Tests

```bash
cd backend && python -m pytest              # 261 tests
cd demo-repo && python -m pytest            # the workspace's own suite
cd frontend && npm run build                # typecheck + build
python benchmarks/harness.py --validate     # the benchmark tasks themselves
```

Running the benchmark itself, once several servers are configured:

```bash
python benchmarks/harness.py --repeat 3                  # one run per server
python benchmarks/harness.py --repeat 3 --concurrency 1  # sequential, for comparable times
```

`--concurrency` defaults to the number of servers in `OPENAI_BASE_URL`. Tokens,
tool calls and scores do not depend on it; **times do**, so the report records
the concurrency it was measured at and a comparison across two different ones
would read queueing as a regression.

---

## The demo task

[`demo-repo/`](demo-repo/) is a small FastAPI notes service with working CRUD, a
green test suite, and **no authentication at all** — including a
`DELETE /admin/notes` that wipes everything and that anyone can call.

The demo request is:

> *Add JWT authentication: keep read routes public, require a valid token for
> writes, and require an admin role for `/admin/*`.*

`demo-repo/` is a **template, never a working directory**. On startup it is
copied to `data/workspace/`, which is where the crew actually works. That keeps
the committed demo repo pristine, makes every run start identically, and avoids
a nested git repository in this project. `POST /api/workspace/reset` restores it.

---

## Working on your own project

By default the crew works in a disposable copy of `demo-repo/`. To point it at a
repository you care about, clear the template and opt in explicitly:

```ini
WORKSPACE_ROOT=/path/to/your/project
WORKSPACE_TEMPLATE=
ALLOW_EXTERNAL_WORKSPACE=true
```

The opt-in is separate from the path on purpose: the crew branches and commits
in that repository, and that must never happen because a path was left
misconfigured. Before any run starts, preflight refuses the situations a run
would be hard to undo — and every refusal names the fix:

| Refused | Why |
|---|---|
| not a git repository | there would be no way back. The crew initialises a repo it provisioned, never one it found |
| uncommitted changes | the agents' work would mix with yours, and the run's diff would stop being the run's |
| a detached HEAD | the branch the run creates would dangle |
| the crew's own source tree | an agent editing the orchestrator it is running on |

`GET /api/workspace/preflight` reports the same thing, so the UI can show it
before you start rather than after. A missing test directory is a *warning*, not
a refusal: QA can still read the diff, it will just have nothing to run.

## Resume and replay

**Resume** — `POST /api/runs/{id}/resume` continues an interrupted run. The
resume point is derived from the persisted artifacts, never stored as a separate
cursor that could disagree with them: a spec but no plan resumes at DESIGN, a
changeset but no report resumes at REVIEW. It rejoins the original branch rather
than branching again, and carries the repair counter forward so a crash cannot
silently reset the bound on the QA loop. Resume is phase-level — an interrupted
agent restarts from the top of its phase, because a half-finished conversation
is not a state anyone can verify.

**Replay** — `POST /api/runs/{id}/replay` re-drives the orchestration on a
recorded run's artifacts, calling no model. Every real run becomes a regression
fixture: change the state machine, replay a run that cost real tokens, and see
whether it still reaches the same outcome — free, offline, and against genuine
model output rather than hand-written doubles. It verifies the *state machine*,
not file effects: no tool calls are made and the workspace is untouched.

## Layout

```
backend/app/
  domain/artifacts.py     The hand-off contracts. Start reading here.
  domain/events.py        Event log types
  agents/base.py          One loop, driven by role data
  agents/prompts.py       System prompts
  orchestrator/engine.py  The state machine, budgets and gates
  tools/base.py           Tool definitions + the permission matrix
  tools/{fs,shell,vcs}.py Tool implementations
  workspace/sandbox.py    Path confinement
  workspace/provision.py  Scratch workspace provisioning
  llm/                    Provider abstraction, Anthropic client, fake provider
  store/                  SQLite event store + SSE broker
  api/routes.py           HTTP + SSE
frontend/src/             React UI: pipeline, timeline, artifacts, gates
demo-repo/                The workspace template
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Provider, approval mode, workspace state, model servers |
| `GET` | `/api/health/endpoints` | Per-server load and whether they agree on the model |
| `GET` | `/api/config` | Roles, models, limits, permission matrix |
| `POST` | `/api/runs` | Start a run |
| `GET` | `/api/runs/{id}` | Full snapshot (run, events, artifacts, pending gates) |
| `GET` | `/api/runs/{id}/stream` | SSE; replays from `?after_seq=` then tails |
| `GET` | `/api/runs/{id}/diff` | Working-tree diff for the run's branch |
| `POST` | `/api/runs/{id}/approvals/{approval_id}` | Approve or deny, with a reason |
| `POST` | `/api/runs/{id}/cancel` | Cancel a live run |
| `GET` | `/api/runs/{id}/resumable` | Whether it can be resumed, and from which phase |
| `POST` | `/api/runs/{id}/resume` | Continue an interrupted run |
| `POST` | `/api/runs/{id}/replay` | Re-drive the orchestration on its artifacts, no model call |
| `POST` | `/api/runs/{id}/rollback` | Discard the run: its checkout and its branch both go |
| `GET` | `/api/workspace/preflight` | Whether a run may start, and what to fix if not |
| `POST` | `/api/workspace/reset` | Re-provision the scratch workspace |

Interactive docs at `/docs`.

---

## Design decisions worth defending

**Why not more agents?** Security and performance analysis are *checks*, not
collaborators — folding them into QA gets the value without another
orchestration edge. The cost of an agent is a context window and a hand-off
that can go wrong; five earn their keep.

**Why a state machine instead of an LLM router?** A model choosing the next
phase is unpredictable and untestable. Every transition here is a line of code
with a test. The models are used where judgement is genuinely needed.

**Why per-role tools instead of one agent with everything?** Because "the
analyst shouldn't edit code" enforced by a prompt is a request, and enforced by
an absent tool is a guarantee.

**Why copy the workspace instead of working in place?** Reproducibility.
Benchmarks and demos need an identical starting state, and a template that is
never mutated is the simplest way to get one.

## Limits, stated plainly

- The QA agent verifies against the spec and the test suite; it is not a
  substitute for human review of security-sensitive code.
- The command allowlist permits package installation, which can execute
  postinstall scripts. Approval gates are the mitigation; a container would be
  the stronger one.
- `python`/`pip`/`pytest` resolve to a `.venv` inside the workspace if one
  exists, otherwise to the interpreter running the server. This keeps an agent's
  `pip install` out of the machine's global site-packages — a real defect caught
  on the first live run — but it is not a per-workspace sandbox: packages an
  agent installs land in the server's environment.
- Runs are single-workspace and sequential. Concurrent runs against the same
  workspace are not supported.
- On a 65k-context local model the ceilings bind much sooner than on the hosted
  API: the verified run used 34 of 40 permitted tool calls. Harder tasks will
  escalate rather than finish, which is the intended failure mode but is worth
  knowing before judging the crew on one.
- Resume is phase-level, not turn-level: an interrupted agent redoes its phase
  from the top rather than rebuilding a half-finished conversation.
- Replay verifies the orchestration, not the file effects — it returns recorded
  artifacts directly, so no tools run and the workspace is untouched.

## Still to build

- **Container execution**, to turn the approval-gate mitigation into real
  isolation. Everything else on this list is smaller than it.
