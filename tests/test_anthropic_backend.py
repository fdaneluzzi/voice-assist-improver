from types import SimpleNamespace as NS

import pytest

from voice_assist_improver.backends import ChatRequest, Done, TextDelta, ToolCall, ToolResult
from voice_assist_improver.backends.anthropic_api import BETA_FALLBACK, AnthropicBackend
from voice_assist_improver.config import Settings
from voice_assist_improver.tools import VoiceToolRegistry


def usage(i=100, o=10, cr=0, cw=0):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw)


def text_block(text):
    return NS(type="text", text=text)


def tool_block(id_, tool_name, **input_):
    return NS(type="tool_use", id=id_, name=tool_name, input=input_)


class Turn:
    def __init__(self, content, stop_reason="end_turn", text=None, u=None):
        self.content, self.stop_reason, self.usage = content, stop_reason, u or usage()
        self.text = text


class FakeStream:
    def __init__(self, turn):
        self.turn = turn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            # One text block per text part; each part is split into two deltas, like a real stream would.
            for block in self.turn.content:
                if block.type != "text":
                    continue
                yield NS(type="content_block_start", content_block=NS(type="text"))
                for piece in (block.text[:3], block.text[3:]):
                    yield NS(type="content_block_delta", delta=NS(type="text_delta", text=piece))
        return gen()

    async def get_final_message(self):
        return self.turn


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    def stream(self, **kwargs):
        self.owner.calls.append(kwargs)
        return FakeStream(self.owner.turns.pop(0))


class FakeClient:
    def __init__(self, turns):
        self.turns, self.calls = list(turns), []
        self.messages = FakeMessages(self)
        self.beta = NS(messages=FakeMessages(self))
        self.closed = False

    def close(self):
        self.closed = True


class FakeSource:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [{"name": "intent__HassTurnOn", "description": "on", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "a_tool", "description": "a", "inputSchema": {"type": "object", "properties": {}}}]

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return ("light is on", False) if name == "intent__HassTurnOn" else ("boom", True)


def make(turns, **overrides):
    s = Settings(anthropic_api_key="k", **overrides)
    source = FakeSource()
    client = FakeClient(turns)
    return AnthropicBackend(s, VoiceToolRegistry(source), client), client, source


async def collect(backend, request):
    return [e async for e in backend.stream(request)]


def req(text="hi", system=None, model="default", history=()):
    return ChatRequest(model=model, messages=[*history, {"role": "user", "content": text}], system=system)


async def test_plain_answer_streams_text_and_reports_usage():
    backend, client, _ = make([Turn([text_block("Hello there")])])
    events = await collect(backend, req())
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Hello there"
    done = events[-1]
    assert isinstance(done, Done) and done.usage["model"] == "claude-sonnet-5-5"
    assert done.usage["input_tokens"] == 100 and done.usage["cost_usd"] > 0 and done.usage["price_known"]


async def test_tool_loop_runs_tools_and_feeds_results_back():
    turn1 = Turn([tool_block("t1", "intent__HassTurnOn", name="lamp")], stop_reason="tool_use")
    turn2 = Turn([text_block("Done, the lamp is on.")])
    backend, client, source = make([turn1, turn2])
    events = await collect(backend, req("turn on the lamp"))
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["ToolCall", "ToolResult", "TextDelta", "TextDelta", "Done"]
    assert events[0] == ToolCall("intent__HassTurnOn", {"name": "lamp"}, "t1")
    assert events[1] == ToolResult("t1", "light is on", False)
    assert source.calls == [("intent__HassTurnOn", {"name": "lamp"})]
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["content"] == turn1.content
    assert second[-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "light is on", "is_error": False}]}
    assert events[-1].usage["input_tokens"] == 200  # usage is summed across the tool turns


async def test_tool_error_is_reported_to_the_model_not_raised():
    turn1 = Turn([tool_block("t1", "a_tool")], stop_reason="tool_use")
    backend, client, _ = make([turn1, Turn([text_block("That failed.")])])
    events = await collect(backend, req())
    assert events[1] == ToolResult("t1", "boom", True)
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True


async def test_chunks_of_one_block_are_not_split_but_blocks_are_kept_apart():
    # Deltas split mid-word must be joined as-is; only a NEW text block gets a separating space.
    backend, _, _ = make([Turn([text_block("Checking"), tool_block("t1", "a_tool")], stop_reason="tool_use"),
                          Turn([text_block("All good")])])
    events = await collect(backend, req())
    deltas = [e.text for e in events if isinstance(e, TextDelta)]
    assert deltas == ["Che", "cking", " All", " good"] or "".join(deltas) == "Checking All good"
    assert "".join(deltas) == "Checking All good"


async def test_text_from_different_turns_is_kept_apart():
    turn1 = Turn([text_block("Checking"), tool_block("t1", "a_tool")], stop_reason="tool_use")
    backend, _, _ = make([turn1, Turn([text_block("All good")])])
    events = await collect(backend, req())
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Checking All good"


async def test_gives_up_after_too_many_tool_iterations():
    def loop_turn():
        return Turn([tool_block("t", "a_tool")], stop_reason="tool_use")

    backend, _, _ = make([loop_turn() for _ in range(3)], max_tool_iterations=3)
    events = await collect(backend, req())
    assert "too many steps" in "".join(e.text for e in events if isinstance(e, TextDelta))


async def test_refusal_speaks_a_message():
    backend, _, _ = make([Turn([], stop_reason="refusal")])
    events = await collect(backend, req())
    assert "can't help" in "".join(e.text for e in events if isinstance(e, TextDelta))


async def test_pause_turn_resumes():
    paused = Turn([text_block("Looking")], stop_reason="pause_turn")
    backend, client, _ = make([paused, Turn([text_block("done")])])
    await collect(backend, req())
    assert len(client.calls) == 2 and client.calls[1]["messages"][-1]["role"] == "assistant"


async def test_max_tokens_during_a_tool_call_is_an_error():
    backend, _, _ = make([Turn([tool_block("t", "a_tool")], stop_reason="max_tokens")])
    with pytest.raises(RuntimeError, match="truncated"):
        await collect(backend, req())


async def test_request_shape_prompt_blocks_tools_effort_and_history():
    backend, client, _ = make([Turn([text_block("ok")])], effort="low")
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    await collect(backend, req("c", system="Be funny.", history=history))
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5" and call["output_config"] == {"effort": "low"}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"} and "voice assistant" in call["system"][0]["text"]
    assert call["system"][1] == {"type": "text", "text": "Be funny."}  # after the cache breakpoint
    assert [t["name"] for t in call["tools"]] == ["a_tool", "intent__HassTurnOn"]  # sorted: stable cache
    assert [m["content"] for m in call["messages"]] == ["a", "b", "c"]
    assert "tool_choice" not in call and "thinking" not in call


async def test_caller_system_prompt_is_optional():
    backend, client, _ = make([Turn([text_block("ok")])])
    await collect(backend, req())
    assert len(client.calls[0]["system"]) == 1


async def test_language_selects_the_builtin_prompt():
    backend, client, _ = make([Turn([text_block("ok")])], language="pt-BR")
    await collect(backend, req())
    assert "assistente de voz" in client.calls[0]["system"][0]["text"]


def test_model_selection():
    backend, _, _ = make([])
    assert backend.pick_model("default") == "claude-sonnet-5-5"
    assert backend.pick_model("claude-haiku-5-5") == "claude-haiku-5-5"
    assert backend.pick_model(None) == "claude-sonnet-5-5"


async def test_refusal_fallback_uses_the_beta_endpoint_only_for_supported_models():
    backend, client, _ = make([Turn([text_block("ok")]), Turn([text_block("ok")]), Turn([text_block("ok")])])
    await collect(backend, req(model="default"))  # sonnet 5.5: supported
    first = client.calls[0]
    assert first["betas"] == [BETA_FALLBACK] and first["fallbacks"] == "default"
    await collect(backend, req(model="claude-haiku-5-5"))  # haiku 5.5 has no server-side fallback
    assert "betas" not in client.calls[1] and "fallbacks" not in client.calls[1]
    backend.s = Settings(anthropic_api_key="k", refusal_fallback=False)
    await collect(backend, req())
    assert "betas" not in client.calls[2]


async def test_web_search_is_off_by_default_and_a_server_tool_when_enabled():
    backend, client, _ = make([Turn([text_block("ok")])])
    await collect(backend, req())
    assert all(t.get("name") != "web_search" for t in client.calls[0]["tools"])
    backend, client, _ = make([Turn([text_block("ok")])], web_search=True, web_search_max_uses=2)
    await collect(backend, req())
    assert client.calls[0]["tools"][-1] == {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}


async def test_close_closes_the_client_and_extras():
    closed = []
    s = Settings(anthropic_api_key="k")
    client = FakeClient([])
    backend = AnthropicBackend(s, VoiceToolRegistry(FakeSource()), client, extra_close=(lambda: closed.append(1),))
    await backend.close()
    assert client.closed and closed == [1]
