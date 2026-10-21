"""Manual checks against the real services (nothing here runs in the test suite).

    python -m voice_assist_improver.smoke tools            # list Home Assistant tools (no API key needed)
    python -m voice_assist_improver.smoke ask "question"   # one full round trip via the configured backend
"""
from __future__ import annotations

import asyncio
import sys
import time

from .backends import ChatRequest, Done, TextDelta, ToolCall, ToolResult, create_backend
from .config import Settings
from .ha.mcp import MCPClient


async def list_tools(settings: Settings) -> int:
    token = settings.ha_mcp_token or settings.ha_token
    if not token:
        print("ERROR: set VAI_HA_MCP_TOKEN (or VAI_HA_TOKEN)")
        return 1
    client = MCPClient(settings.ha_mcp_url, token)
    try:
        started = time.monotonic()
        tools = await client.list_tools()
        print(f"{len(tools)} tools from {settings.ha_mcp_url} in {time.monotonic() - started:.2f}s")
        for tool in sorted(tools, key=lambda x: x["name"]):
            print(f"  - {tool['name']}")
        return 0
    finally:
        await client.close()


async def ask(settings: Settings, question: str) -> int:
    backend = create_backend(settings)
    started = time.monotonic()
    try:
        return await _ask(backend, settings, question, started)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        detail = getattr(exc, "message", None) or str(exc)
        request_id = getattr(exc, "request_id", None)
        print(f"\nERROR ({type(exc).__name__}{f', HTTP {status}' if status else ''}): {detail}"
              + (f"\n  request id: {request_id}" if request_id else ""))
        return 1
    finally:
        await backend.close()


async def _ask(backend, settings: Settings, question: str, started: float) -> int:
    first = None
    request = ChatRequest(model=settings.model, messages=[{"role": "user", "content": question}])
    async for event in backend.stream(request):
        if isinstance(event, TextDelta):
            first = first if first is not None else time.monotonic() - started
            print(event.text, end="", flush=True)
        elif isinstance(event, ToolCall):
            print(f"\n[tool call] {event.name} {event.input}", flush=True)
        elif isinstance(event, ToolResult):
            flag = " (error)" if event.is_error else ""
            print(f"[tool result{flag}] {event.output[:120]!r}", flush=True)
        elif isinstance(event, Done) and event.usage:
            first_text = first if first is not None else float("nan")
            print(f"\n\n[done] total {time.monotonic() - started:.2f}s, first text {first_text:.2f}s, "
                  f"usage {event.usage}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    settings = Settings.load()
    if argv[:1] == ["tools"]:
        return asyncio.run(list_tools(settings))
    if argv[:1] == ["ask"] and len(argv) >= 2:
        return asyncio.run(ask(settings, " ".join(argv[1:])))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
