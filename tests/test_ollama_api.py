import json

from voice_assist_improver.backends import ChatRequest, Done, TextDelta, ToolCall, ToolResult


def chat_body(*messages, stream=True, model="default:latest"):
    return {"model": model, "stream": stream, "messages": [{"role": r, "content": c} for r, c in messages]}


def ndjson(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def test_discovery_endpoints(make_client):
    client, _ = make_client()
    assert (await client.get("/")).text == "Ollama is running"
    assert "version" in (await client.get("/api/version")).json()
    names = [m["name"] for m in (await client.get("/api/tags")).json()["models"]]
    assert names == ["default:latest", "other:latest"]
    assert (await client.post("/api/show", json={"model": "default"})).status_code == 200
    assert (await client.post("/api/show", json={"model": "nope"})).status_code == 404


async def test_network_filter(make_client):
    client, _ = make_client(client_ip="192.168.9.9")
    assert (await client.get("/api/version")).status_code == 403
    client, _ = make_client(client_ip="10.0.0.7")
    assert (await client.get("/api/version")).status_code == 200


async def test_streaming_chat_ends_with_done(make_client):
    client, _ = make_client()
    r = await client.post("/api/chat", json=chat_body(("user", "hello")))
    assert r.headers["content-type"].startswith("application/x-ndjson")
    chunks = ndjson(r.text)
    assert chunks[-1]["done"] is True and chunks[-1]["message"]["content"] == ""
    assert "".join(c["message"]["content"] for c in chunks) == "Echo: hello"


async def test_non_streaming_chat(make_client):
    client, _ = make_client()
    data = (await client.post("/api/chat", json=chat_body(("user", "hi"), stream=False))).json()
    assert data["done"] is True and data["message"]["content"] == "Echo: hi"


async def test_unknown_model_is_404(make_client):
    client, _ = make_client()
    assert (await client.post("/api/chat", json=chat_body(("user", "x"), model="llama3"))).status_code == 404


class RecordingBackend:
    name = "recording"

    def __init__(self):
        self.requests: list[ChatRequest] = []

    async def stream(self, request):
        self.requests.append(request)
        yield ToolCall("turn_on", {"entity_id": "light.a"}, id="t1")
        yield ToolResult("t1", "ok")
        yield TextDelta("Done.")
        yield Done()

    async def close(self):
        return None


async def test_caller_system_prompt_is_passed_to_the_backend_and_history_is_clean(make_client):
    backend = RecordingBackend()
    client, _ = make_client(backend)
    await client.post("/api/chat", json=chat_body(("system", "Be brief."), ("user", "a"), ("assistant", "b"), ("user", "c")))
    req = backend.requests[0]
    assert req.system == "Be brief."
    assert [m["role"] for m in req.messages] == ["user", "assistant", "user"]


async def test_interaction_is_recorded_with_tools(make_client):
    client, store = make_client(RecordingBackend())
    await client.post("/api/chat", json=chat_body(("user", "turn on the light")))
    rec = store.interactions_since(0)[0]
    assert rec["utterance"] == "turn on the light" and rec["reply"] == "Done." and rec["backend"] == "recording"
    assert rec["tools"][0]["name"] == "turn_on" and rec["tools"][0]["result"] == "ok" and rec["error"] is None


class FailingBackend:
    name = "failing"

    async def stream(self, request):
        raise RuntimeError("upstream down")
        yield  # pragma: no cover

    async def close(self):
        return None


async def test_backend_failure_speaks_an_apology_and_is_recorded(make_client):
    client, store = make_client(FailingBackend())
    r = await client.post("/api/chat", json=chat_body(("user", "hello")))
    text = "".join(c["message"]["content"] for c in ndjson(r.text))
    assert "couldn't reach" in text
    assert "upstream down" in store.interactions_since(0)[0]["error"]


async def test_apology_follows_the_configured_language(make_client):
    client, _ = make_client(FailingBackend(), language="pt-BR")
    r = await client.post("/api/chat", json=chat_body(("user", "oi")))
    assert "Desculpe" in "".join(c["message"]["content"] for c in ndjson(r.text))
