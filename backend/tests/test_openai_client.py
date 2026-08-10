"""The OpenAI-compatible adapter.

The translation between the two message shapes is where this provider can go
silently wrong, so it is tested directly rather than only through a live call.
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMRequest, Sampling
from app.llm.openai_client import (
    OpenAICompatibleClient,
    _to_openai_messages,
    _to_openai_tools,
    _usage_from,
)

# asyncio_mode=auto in pytest.ini picks up the async tests; a module-level
# asyncio mark would wrongly tag the synchronous ones too.


def make_client(**kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="http://localhost:1/v1", model="local-model", **kwargs
    )


class RecordingClient(OpenAICompatibleClient):
    """Captures outgoing payloads and replays canned responses."""

    def __init__(self, responses: list[dict], **kwargs) -> None:
        super().__init__(base_url="http://localhost:1/v1", model="local-model", **kwargs)
        self.responses = list(responses)
        self.sent: list[dict] = []

    async def _post(self, payload):
        self.sent.append(payload)
        return self.responses.pop(0)


def chat_response(*, content=None, reasoning=None, tool_calls=None, finish="stop", usage=None):
    message = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "model": "local-model",
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
    }


# -- tool schema translation -------------------------------------------------


def test_tools_are_converted_to_the_function_shape() -> None:
    converted = _to_openai_tools(
        [{"name": "read_file", "description": "Read it.",
          "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}]
    )
    assert converted == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read it.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]


# -- message translation -----------------------------------------------------


def test_system_prompt_becomes_the_first_message() -> None:
    out = _to_openai_messages("you are a bot", [{"role": "user", "content": "hi"}])
    assert out[0] == {"role": "system", "content": "you are a bot"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_assistant_tool_use_becomes_tool_calls() -> None:
    out = _to_openai_messages(
        "sys",
        [
            {"role": "user", "content": "read it"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "on it"},
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}},
            ]},
        ],
    )
    assistant = out[-1]
    assert assistant["content"] == "on it"
    assert assistant["tool_calls"][0]["id"] == "t1"
    assert assistant["tool_calls"][0]["function"] == {
        "name": "read_file", "arguments": '{"path": "a.py"}'
    }


def test_each_tool_result_becomes_its_own_tool_message() -> None:
    """Anthropic batches results in one user turn; OpenAI wants one each."""
    out = _to_openai_messages(
        "sys",
        [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "file A"},
                {"type": "tool_result", "tool_use_id": "t2", "content": "file B"},
            ]},
        ],
    )
    tool_messages = [m for m in out if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["t1", "t2"]
    assert [m["content"] for m in tool_messages] == ["file A", "file B"]


def test_thinking_blocks_are_not_replayed() -> None:
    out = _to_openai_messages(
        "sys",
        [{"role": "assistant", "content": [
            {"type": "thinking", "thinking": "long private reasoning"},
            {"type": "text", "text": "answer"},
        ]}],
    )
    assert "long private reasoning" not in str(out)
    assert out[-1]["content"] == "answer"


# -- response translation ----------------------------------------------------


async def test_reasoning_content_becomes_a_thinking_block() -> None:
    client = RecordingClient([chat_response(content="hello", reasoning="because")])
    response = await client.complete(LLMRequest(model="m", system="s", messages=[]))

    assert [b["type"] for b in response.content] == ["thinking", "text"]
    assert response.thinking_text == "because"
    assert response.text == "hello"


async def test_tool_calls_become_tool_use_blocks() -> None:
    client = RecordingClient([chat_response(
        finish="tool_calls",
        tool_calls=[{"id": "c1", "type": "function",
                     "function": {"name": "read_file", "arguments": '{"path":"x.py"}'}}],
    )])
    response = await client.complete(
        LLMRequest(model="m", system="s", messages=[],
                   tools=[{"name": "read_file", "description": "", "input_schema": {}}])
    )

    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0]["name"] == "read_file"
    assert response.tool_calls[0]["input"] == {"path": "x.py"}


async def test_malformed_tool_arguments_do_not_crash_the_run() -> None:
    client = RecordingClient([chat_response(
        finish="tool_calls",
        tool_calls=[{"id": "c1", "type": "function",
                     "function": {"name": "read_file", "arguments": "{not json"}}],
    )])
    response = await client.complete(
        LLMRequest(model="m", system="s", messages=[],
                   tools=[{"name": "read_file", "description": "", "input_schema": {}}])
    )
    assert response.tool_calls[0]["input"] == {}


def test_cached_tokens_are_split_out_of_the_prompt_count() -> None:
    usage = _usage_from({"usage": {
        "prompt_tokens": 300, "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 258},
    }})
    assert usage.input_tokens == 42
    assert usage.cache_read_input_tokens == 258
    assert usage.output_tokens == 50


def test_length_finish_reason_maps_to_max_tokens() -> None:
    client = make_client()
    response = client._to_response(chat_response(content="cut off", finish="length"))
    assert response.stop_reason == "max_tokens"


# -- the two-phase completion ------------------------------------------------


async def test_tool_phase_never_sends_a_grammar() -> None:
    """A response_format grammar suppresses tool calling on llama.cpp."""
    client = RecordingClient([chat_response(
        finish="tool_calls",
        tool_calls=[{"id": "c1", "type": "function",
                     "function": {"name": "read_file", "arguments": "{}"}}],
    )])
    await client.complete(LLMRequest(
        model="m", system="s", messages=[],
        tools=[{"name": "read_file", "description": "", "input_schema": {}}],
        output_format={"type": "json_schema", "schema": {"type": "object"}},
    ))

    assert len(client.sent) == 1
    assert "tools" in client.sent[0]
    assert "response_format" not in client.sent[0]


async def test_artifact_phase_runs_once_the_model_stops_calling_tools() -> None:
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    client = RecordingClient([
        chat_response(content="I have everything I need."),   # phase 1: no tool calls
        chat_response(content='{"summary":"done"}'),          # phase 2: constrained
    ])

    response = await client.complete(LLMRequest(
        model="m", system="s", messages=[{"role": "user", "content": "go"}],
        tools=[{"name": "read_file", "description": "", "input_schema": {}}],
        output_format={"type": "json_schema", "schema": schema},
    ))

    assert len(client.sent) == 2
    explore, emit = client.sent
    assert "tools" in explore and "response_format" not in explore
    # Phase 2 drops the tools and applies the grammar.
    assert "tools" not in emit
    assert emit["response_format"]["json_schema"]["schema"] == schema
    assert emit["chat_template_kwargs"]["enable_thinking"] is False
    # The exploration turn is carried forward so the artifact reflects it.
    assert any(m.get("content") == "I have everything I need." for m in emit["messages"])
    assert response.text == '{"summary":"done"}'


async def test_both_phases_are_billed() -> None:
    client = RecordingClient([
        chat_response(content="done exploring", usage={"prompt_tokens": 100, "completion_tokens": 10}),
        chat_response(content="{}", usage={"prompt_tokens": 200, "completion_tokens": 20}),
    ])
    response = await client.complete(LLMRequest(
        model="m", system="s", messages=[],
        tools=[{"name": "t", "description": "", "input_schema": {}}],
        output_format={"type": "json_schema", "schema": {"type": "object"}},
    ))
    assert response.usage.input_tokens == 300
    assert response.usage.output_tokens == 30


async def test_artifact_only_request_skips_the_tool_phase() -> None:
    client = RecordingClient([chat_response(content='{"summary":"x"}')])
    await client.complete(LLMRequest(
        model="m", system="s", messages=[],
        output_format={"type": "json_schema", "schema": {"type": "object"}},
    ))
    assert len(client.sent) == 1
    assert "response_format" in client.sent[0]


# -- context ceiling ---------------------------------------------------------


async def test_output_budget_is_capped_by_the_server_context() -> None:
    client = RecordingClient([chat_response(content="ok")], max_context_tokens=8_000)
    await client.complete(LLMRequest(model="m", system="s", messages=[], max_tokens=32_000))
    assert client.sent[0]["max_tokens"] == 2_000


async def test_thinking_toggle_is_forwarded() -> None:
    client = RecordingClient([chat_response(content="ok")], enable_thinking=False)
    await client.complete(LLMRequest(model="m", system="s", messages=[]))
    assert client.sent[0]["chat_template_kwargs"] == {"enable_thinking": False}


# -- sampling ----------------------------------------------------------------
#
# Unset sampling was most of this project's measured run-to-run variance: the
# server applied its own random defaults, and three identical requests returned
# three different plans.


async def test_unset_sampling_is_not_sent_at_all() -> None:
    """The server's own defaults must stay reachable — absent, not overridden."""
    client = RecordingClient([chat_response(content="ok")])
    await client.complete(LLMRequest(model="m", system="s", messages=[]))

    sent = client.sent[0]
    assert "temperature" not in sent and "top_p" not in sent
    assert "top_k" not in sent and "seed" not in sent


async def test_pinned_sampling_is_forwarded() -> None:
    client = RecordingClient(
        [chat_response(content="ok")],
        sampling=Sampling(temperature=0, top_k=1, seed=42),
    )
    await client.complete(LLMRequest(model="m", system="s", messages=[]))

    sent = client.sent[0]
    assert sent["temperature"] == 0
    assert sent["top_k"] == 1
    assert sent["seed"] == 42
    assert "top_p" not in sent, "an unset field must not be invented"


async def test_temperature_zero_is_sent_not_treated_as_unset() -> None:
    """0 is falsy; a naive truthiness check would silently drop the one value
    that makes a benchmark readable."""
    client = RecordingClient([chat_response(content="ok")], sampling=Sampling(temperature=0.0))
    await client.complete(LLMRequest(model="m", system="s", messages=[]))
    assert client.sent[0]["temperature"] == 0.0


def test_greedy_is_recognised() -> None:
    assert Sampling(temperature=0).is_greedy is True
    assert Sampling(temperature=0.7).is_greedy is False
    assert Sampling().is_greedy is False


async def test_both_phases_share_the_sampling() -> None:
    """A deterministic explore phase and a sampled emit phase would be worse
    than either — the whole run has to be pinned, or none of it."""
    client = RecordingClient(
        [chat_response(content="done"), chat_response(content="{}")],
        sampling=Sampling(temperature=0),
    )
    await client.complete(LLMRequest(
        model="m", system="s", messages=[],
        tools=[{"name": "t", "description": "", "input_schema": {}}],
        output_format={"type": "json_schema", "schema": {"type": "object"}},
    ))
    assert all(payload["temperature"] == 0 for payload in client.sent)


# -- asking a server what it serves ------------------------------------------


class StubTransport:
    """Answers /models with a canned payload, without a network."""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload, self.status = payload, status

    async def get(self, _path: str):
        class Response:
            status_code = self.status
            def json(_self) -> dict:  # noqa: N805 - closure over the stub
                return self.payload
        return Response()


async def models_of(payload: dict) -> list[str]:
    client = make_client()
    client._client = StubTransport(payload)
    return await client.list_models()


async def test_the_openai_model_list_shape_is_read() -> None:
    assert await models_of({"data": [{"id": "qwen"}, {"id": "llama"}]}) == ["llama", "qwen"]


async def test_the_ollama_model_list_shape_is_read() -> None:
    """The llama.cpp server this was written against answers in this shape;
    reading only the OpenAI one made a healthy server look unreachable."""
    payload = {"models": [{"name": "E:/gguf/qwen.gguf", "model": "E:/gguf/qwen.gguf"}]}
    assert await models_of(payload) == ["E:/gguf/qwen.gguf"]


async def test_a_server_listing_nothing_returns_nothing() -> None:
    assert await models_of({"data": []}) == []


async def test_an_error_status_is_reported_as_unavailable() -> None:
    from app.llm.openai_client import EndpointUnavailable

    client = make_client()
    client._client = StubTransport({}, status=503)
    with pytest.raises(EndpointUnavailable):
        await client.list_models()
