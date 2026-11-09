from test_anthropic_backend import Turn, collect, make, text_block

from voice_assist_improver.memory import attach_tool_traces, expand_messages, index_interactions
from voice_assist_improver.ollama_api import MAX_RECORDED_RESULT


def row(ts, utterance, reply, tools, error=None):
    return {"ts": ts, "utterance": utterance, "reply": reply, "tools": tools, "error": error}


TURN_ON = {"id": "toolu_1", "name": "intent__HassTurnOn", "input": {"area": "Sala"}, "result": "ok", "is_error": False}


def test_trace_is_attached_to_the_assistant_message_that_followed_it():
    index = index_interactions([row(1, "Liga a luz da sala.", "Pronto, liguei.", [TURN_ON])])
    turns = [{"role": "user", "content": "liga a luz da sala"},          # spelling and punctuation differ
             {"role": "assistant", "content": "Pronto, liguei"},
             {"role": "user", "content": "e a cozinha?"}]
    out = attach_tool_traces(turns, index)
    assert out[1]["tools"] == [TURN_ON] and "tools" not in out[0] and "tools" not in out[2]
    assert "tools" not in turns[1]  # the caller's list is not modified


def test_no_trace_for_unknown_failed_or_toolless_interactions():
    index = index_interactions([row(1, "a", "b", [TURN_ON], error="boom"), row(2, "c", "d", [])])
    assert index == {}
    turns = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]
    assert "tools" not in attach_tool_traces(turns, index)[1]


def test_same_exchange_twice_uses_the_newest():
    older = {**TURN_ON, "id": "old"}
    index = index_interactions([row(5, "u", "r", [TURN_ON]), row(1, "u", "r", [older])])
    assert index[("u", "r")][0]["id"] == "toolu_1"


def test_expand_replays_tool_use_and_result_before_the_spoken_text():
    turns = [{"role": "user", "content": "liga"}, {"role": "assistant", "content": "Pronto.", "tools": [TURN_ON]},
             {"role": "user", "content": "e agora?"}]
    msgs = expand_messages(turns, {"intent__HassTurnOn"})
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[1]["content"] == [{"type": "tool_use", "id": "toolu_1", "name": "intent__HassTurnOn",
                                   "input": {"area": "Sala"}}]
    assert msgs[2]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok",
                                   "is_error": False}]
    assert msgs[3] == {"role": "assistant", "content": "Pronto."}


def test_expand_skips_a_trace_whose_tool_no_longer_exists_and_caps_long_results():
    turns = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b", "tools": [TURN_ON]}]
    assert expand_messages(turns, {"other"}) == [{"role": "user", "content": "a"},
                                                 {"role": "assistant", "content": "b"}]
    long = {**TURN_ON, "result": "x" * 9000, "id": ""}
    msgs = expand_messages(turns[:1] + [{"role": "assistant", "content": "b", "tools": [long]}], {"intent__HassTurnOn"})
    assert len(msgs[2]["content"][0]["content"]) == 1500
    assert msgs[1]["content"][0]["id"] == msgs[2]["content"][0]["tool_use_id"] != ""


def test_tool_ids_stay_unique_when_the_same_exchange_repeats():
    turns = [{"role": "user", "content": "liga"}, {"role": "assistant", "content": "Pronto.", "tools": [TURN_ON]},
             {"role": "user", "content": "liga"}, {"role": "assistant", "content": "Pronto.", "tools": [TURN_ON]}]
    msgs = expand_messages(turns, {"intent__HassTurnOn"})
    ids = [b["id"] for m in msgs if isinstance(m["content"], list) for b in m["content"] if b["type"] == "tool_use"]
    uses = [b["tool_use_id"] for m in msgs if isinstance(m["content"], list)
            for b in m["content"] if b["type"] == "tool_result"]
    assert len(ids) == 2 and len(set(ids)) == 2 and ids == uses


def test_recorded_results_keep_enough_to_see_failures():
    assert MAX_RECORDED_RESULT >= 2000


async def test_backend_sends_the_earlier_tools_to_the_model():
    backend, client, _ = make([Turn([text_block("Certo.")])])
    from voice_assist_improver.backends import ChatRequest
    request = ChatRequest(model="default", messages=[
        {"role": "user", "content": "liga"},
        {"role": "assistant", "content": "Pronto.", "tools": [{**TURN_ON, "name": "intent__HassTurnOn"}]},
        {"role": "user", "content": "obrigado"}])
    await collect(backend, request)
    sent = client.calls[0]["messages"]
    assert sent[1]["content"][0]["type"] == "tool_use" and sent[2]["content"][0]["type"] == "tool_result"


async def test_chat_endpoint_replays_the_previous_turn_tools(make_client):
    from voice_assist_improver.backends import Done, TextDelta, ToolCall, ToolResult

    seen = []

    class Recorder:
        name = "rec"

        async def stream(self, request):
            seen.append(request.messages)
            if len(seen) == 1:
                yield ToolCall("intent__HassTurnOn", {"area": "Sala"}, "toolu_9")
                yield ToolResult("toolu_9", "ok", False)
                yield TextDelta("Pronto, liguei a sala.")
            else:
                yield TextDelta("De nada.")
            yield Done(usage={"model": "m"})

        async def close(self):
            pass

    client, _ = make_client(backend=Recorder())
    async with client:
        first = {"model": "default", "stream": False, "messages": [{"role": "user", "content": "Liga a sala."}]}
        await client.post("/api/chat", json=first)
        second = {"model": "default", "stream": False, "messages": [
            {"role": "user", "content": "Liga a sala."}, {"role": "assistant", "content": "Pronto, liguei a sala."},
            {"role": "user", "content": "Valeu."}]}
        await client.post("/api/chat", json=second)
    tools = seen[1][1]["tools"]
    assert tools[0]["name"] == "intent__HassTurnOn" and tools[0]["result"] == "ok" and tools[0]["id"] == "toolu_9"
    assert "tools" not in seen[0][0]


async def test_backend_falls_back_to_plain_history_when_the_api_refuses_the_replay():
    backend, client, _ = make([Turn([text_block("Certo.")])])

    class Refused(Exception):
        status_code = 400

    real = client.beta.messages.stream  # the default model takes the fallback (beta) route
    calls = []

    def stream(**kwargs):
        calls.append(kwargs)
        if any(isinstance(m["content"], list) for m in kwargs["messages"]):
            raise Refused("bad history")
        return real(**kwargs)

    client.beta.messages.stream = stream
    from voice_assist_improver.backends import ChatRequest
    request = ChatRequest(model="default", messages=[
        {"role": "user", "content": "liga"},
        {"role": "assistant", "content": "Pronto.", "tools": [TURN_ON]},
        {"role": "user", "content": "obrigado"}])
    events = await collect(backend, request)
    assert "".join(getattr(e, "text", "") for e in events) == "Certo."
    assert len(calls) == 2 and all(isinstance(m["content"], str) for m in calls[1]["messages"])


async def test_other_api_errors_are_not_retried():
    backend, client, _ = make([])

    def stream(**kwargs):
        raise RuntimeError("down")

    client.beta.messages.stream = stream
    import pytest

    from voice_assist_improver.backends import ChatRequest
    with pytest.raises(RuntimeError):
        await collect(backend, ChatRequest(model="default", messages=[{"role": "user", "content": "oi"}]))
