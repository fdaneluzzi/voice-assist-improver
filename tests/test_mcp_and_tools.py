import json

import httpx
import pytest

from voice_assist_improver.ha.mcp import MCPClient, MCPError
from voice_assist_improver.tools import MAX_RESULT_CHARS, VoiceToolRegistry

TOOLS = [
    {"name": "intent__HassTurnOn", "description": "turn on", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}}},
    {"name": "homeassistant__GetLiveContext", "description": "state", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "assist_satellite__HassBroadcast", "description": "broadcast", "inputSchema": {"type": "object", "properties": {}}},
]


def mcp_handler(requests, *, sse=False, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.headers.get("authorization"), body))
        method = body["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "ha"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif body["params"]["name"] == "boom":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"message": "nope"}})
        elif body["params"]["name"] == "bad":
            result = {"content": [{"type": "text", "text": "it failed"}], "isError": True}
        else:
            result = {"content": [{"type": "text", "text": "line1"}, {"type": "image"}, {"type": "text", "text": "line2"}]}
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if sse:
            return httpx.Response(status, text=f"event: message\ndata: {json.dumps(payload)}\n\n",
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(status, json=payload)
    return handler


def make_client(handler):
    return MCPClient("http://ha/api/mcp", "tok", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_initialize_once_then_list_and_call():
    seen = []
    client = make_client(mcp_handler(seen))
    assert [t["name"] for t in await client.list_tools()] == [t["name"] for t in TOOLS]
    assert await client.call_tool("x", {"a": 1}) == ("line1\nline2", False)
    assert [b["method"] for _, b in seen] == ["initialize", "tools/list", "tools/call"]
    assert all(auth == "Bearer tok" for auth, _ in seen)


async def test_sse_responses_are_parsed():
    client = make_client(mcp_handler([], sse=True))
    assert len(await client.list_tools()) == 3


async def test_tool_error_flag_and_rpc_error():
    client = make_client(mcp_handler([]))
    assert await client.call_tool("bad") == ("it failed", True)
    with pytest.raises(MCPError, match="nope"):
        await client.call_tool("boom")


async def test_rejected_token_is_a_clear_error():
    client = make_client(mcp_handler([], status=401))
    with pytest.raises(MCPError, match="rejected the MCP token"):
        await client.list_tools()


class FakeSource:
    def __init__(self):
        self.list_calls = 0
        self.fail_list = False
        self.calls = []

    async def list_tools(self):
        self.list_calls += 1
        if self.fail_list:
            raise ConnectionError("down")
        return TOOLS

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == "intent__HassTurnOn":
            return "x" * (MAX_RESULT_CHARS + 50), False
        raise MCPError("failed")


async def test_registry_sorts_filters_and_converts_tools():
    registry = VoiceToolRegistry(FakeSource(), denylist=("assist_satellite__*",))
    await registry.refresh()
    tools = registry.api_tools()
    assert [t["name"] for t in tools] == ["homeassistant__GetLiveContext", "intent__HassTurnOn"]  # sorted, filtered
    assert tools[1]["input_schema"]["properties"]["name"] == {"type": "string"}


async def test_registry_caches_and_survives_a_refresh_failure():
    source = FakeSource()
    registry = VoiceToolRegistry(source, cache_seconds=300)
    await registry.refresh()
    await registry.refresh()
    assert source.list_calls == 1
    source.fail_list = True
    await registry.refresh(force=True)  # keeps the previous list instead of failing the voice request
    assert len(registry.api_tools()) == 3


async def test_registry_fails_on_first_load_when_home_assistant_is_down():
    source = FakeSource()
    source.fail_list = True
    with pytest.raises(ConnectionError):
        await VoiceToolRegistry(source).refresh()


async def test_execute_never_raises_and_caps_result_size():
    source = FakeSource()
    registry = VoiceToolRegistry(source)
    await registry.refresh()
    text, is_error = await registry.execute("intent__HassTurnOn", {})
    assert not is_error and text.endswith("[truncated]") and len(text) < MAX_RESULT_CHARS + 20
    assert await registry.execute("homeassistant__GetLiveContext", {}) == ("Tool failed: failed", True)
    assert await registry.execute("not_a_tool", {}) == ("Unknown tool: not_a_tool", True)
    assert source.calls and all(name in {t["name"] for t in TOOLS} for name, _ in source.calls)
