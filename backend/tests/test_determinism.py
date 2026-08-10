"""Volatile values must not reach the model's own conversation.

Two repetitions of one benchmark task were compared event by event: the model
produced thirty-nine byte-identical exchanges, then diverged on a tool result
reading `7 passed, 1 warning in 2.03s` against `in 1.34s`. The model was
deterministic; its environment was not.
"""

from __future__ import annotations

from app.tools.determinism import stabilise


# -- what must be neutralised ------------------------------------------------


def test_two_runs_of_the_same_suite_read_identically() -> None:
    """The exact divergence that was measured, reduced to one assertion."""
    assert stabilise("7 passed, 1 warning in 2.03s") == stabilise(
        "7 passed, 1 warning in 1.34s"
    )


def test_a_whole_number_of_seconds_is_neutralised_too() -> None:
    assert stabilise("12 passed in 3s") == stabilise("12 passed in 9s")


def test_a_commit_can_never_repeat_so_its_name_is_dropped() -> None:
    # The commit timestamp is part of what git hashes: two identical runs
    # cannot produce the same object name, ever.
    a = stabilise("Committed 6ebc4f4: Add pagination")
    b = stabilise("Committed 6442f07: Add pagination")
    assert a == b
    assert "6ebc4f4" not in a


def test_the_diff_index_line_is_neutralised() -> None:
    assert stabilise("index 0b98788..62820a4 100644") == stabilise(
        "index aaaaaaa..bbbbbbb 100644"
    )


def test_the_rest_of_the_output_is_left_alone() -> None:
    """Only the volatile part goes; the message is what the model reasons from."""
    out = stabilise("Committed 6ebc4f4: Add limit/offset pagination to GET /notes")
    assert "Add limit/offset pagination to GET /notes" in out


# -- what must NOT be touched ------------------------------------------------


def test_hex_that_belongs_to_the_code_survives() -> None:
    """Blanking every hex run would corrupt the code under test — turning a
    determinism fix into the worse bug."""
    for kept in (
        'COLOUR = "#a1b2c3d"',
        'CHECKSUM = "deadbeefcafe"',
        'uuid = "3f2a1b4c5d6e7f80"',
        "index_of_first = 0",
    ):
        assert stabilise(kept) == kept


def test_a_sentence_merely_containing_in_and_a_number_survives() -> None:
    assert stabilise("retry in 3 seconds") == "retry in 3 seconds"
    assert stabilise("defined in 3s_module.py") == "defined in 3s_module.py"


def test_the_word_committed_without_a_hash_survives() -> None:
    assert stabilise("Committed nothing: the tree was clean") == (
        "Committed nothing: the tree was clean"
    )


def test_empty_and_missing_output_are_returned_unchanged() -> None:
    assert stabilise("") == ""
    assert stabilise(None) is None  # type: ignore[arg-type]


# -- where it is applied -----------------------------------------------------


async def test_the_log_keeps_the_truth_while_the_model_reads_the_stable_copy(
    sandbox,
) -> None:
    """The two must differ, and in exactly one direction.

    A log that recorded the placeholder instead of what a tool actually printed
    would stop being a record of the run — the replay, the diff and the cost
    table all read it. So this checks both halves at once, by running a real
    tool through a real agent rather than by reading the source.
    """
    from app.agents.base import Agent, AgentContext, Budget
    from app.domain.artifacts import Spec, output_format_for
    from app.domain.roles import AgentRole
    from app.llm.base import LLMResponse, Usage
    from app.tools.registry import tools_for_role
    from conftest import make_spec

    volatile = "Committed 6ebc4f4: done in 2.03s\n"
    (sandbox.root / "note.txt").write_text(volatile, encoding="utf-8")

    recorded: list[dict] = []

    async def emit(event_type, payload) -> None:
        recorded.append(payload)

    replies = [
        LLMResponse(
            content=[{"type": "tool_use", "id": "t1", "name": "read_file",
                      "input": {"path": "note.txt"}}],
            stop_reason="tool_use", usage=Usage(input_tokens=1, output_tokens=1), model="fake",
        ),
        LLMResponse(
            content=[{"type": "text", "text": make_spec().model_dump_json()}],
            stop_reason="end_turn", usage=Usage(input_tokens=1, output_tokens=1), model="fake",
        ),
    ]

    class Replaying:
        provider = "fake"
        def __init__(self) -> None:
            self.seen: list = []
        async def complete(self, request):
            self.seen.append(request)
            return replies.pop(0) if len(replies) > 1 else replies[0]

    client = Replaying()
    agent = Agent(
        role=AgentRole.ANALYST,
        system_prompt="s",
        output_model=Spec,
        output_format=output_format_for(Spec),
        tools=tools_for_role(AgentRole.ANALYST),
        model="fake",
    )
    await agent.run(
        "do it",
        AgentContext(
            run_id="r", sandbox=sandbox, llm=client,
            budget=Budget(max_tokens=1_000_000, max_tool_calls=10),
            emit=emit, request_approval=None, approval_mode="auto",
        ),
    )

    logged = [p["output"] for p in recorded if "output" in p]
    assert any("6ebc4f4" in out and "2.03s" in out for out in logged), (
        "the event log must carry what the tool actually printed"
    )

    conversation = str(client.seen[-1].messages)
    assert "6ebc4f4" not in conversation and "2.03s" not in conversation, (
        "the model must never see a value that cannot recur"
    )
    assert "<commit>" in conversation or "<duration>" in conversation
