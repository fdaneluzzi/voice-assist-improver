"""Backend that calls the Anthropic Messages API directly, running the tool loop itself.

Design notes:
- A manual loop with streaming: tools come from Home Assistant at runtime, and text must reach the speaker as
  soon as it is generated.
- The built-in voice prompt is the first system block and carries the cache breakpoint; the caller's own
  system message (the "Instructions" field of Home Assistant's Ollama agent) follows it, so a dynamic
  template there never invalidates the cached prefix (tools + base prompt).
- Voice requests only see the voice tool registry (plus web search when explicitly enabled).
- Thinking is left to the model's default; `effort` keeps latency low for voice.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..config import Settings
from ..cost import Usage, usage_record
from ..i18n import t
from ..prompts import load_voice_prompt
from ..tools import VoiceToolRegistry
from .base import ChatRequest, Done, Event, TextDelta, ToolCall, ToolResult

BETA_FALLBACK = "server-side-fallback-2026-07-01"
# Server-side fallback ("default") exists on these models only. Haiku 5.5 has none: sending the parameter
# there either does nothing or is rejected.
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")
WEB_SEARCH_TOOL = "web_search_20260209"


class TooManySteps(Exception):
    pass


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, settings: Settings, registry: VoiceToolRegistry, client: Any, extra_close=()):
        self.s = settings
        self.registry = registry
        self.client = client
        self._extra_close = extra_close

    # ----- request construction (kept separate so it can be tested without any network) -----

    def pick_model(self, requested: str | None) -> str:
        return requested if requested and requested.startswith("claude-") else self.s.model

    def system_blocks(self, caller_system: str | None) -> list[dict]:
        base = load_voice_prompt(self.s.language, self.s.custom_voice_prompt_file or None)
        blocks: list[dict] = [{"type": "text", "text": base, "cache_control": {"type": "ephemeral"}}]
        if caller_system and caller_system.strip():
            blocks.append({"type": "text", "text": caller_system.strip()})
        return blocks

    def tool_list(self) -> list[dict]:
        tools = self.registry.api_tools()
        if self.s.web_search:
            tools.append(
                {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": self.s.web_search_max_uses})
        return tools

    def request_kwargs(self, model: str, system: list[dict], messages: list[dict], tools: list[dict]) -> dict:
        kwargs: dict[str, Any] = {
            "model": model, "max_tokens": self.s.max_output_tokens, "system": system, "messages": messages,
            "output_config": {"effort": self.s.effort},
        }
        if tools:
            kwargs["tools"] = tools
        if self.s.refusal_fallback and model in FALLBACK_MODELS:
            kwargs["betas"] = [BETA_FALLBACK]
            kwargs["fallbacks"] = "default"
        return kwargs

    @staticmethod
    def _api(client: Any, kwargs: dict):
        return client.beta.messages if "betas" in kwargs else client.messages

    # ----- the conversation -----

    async def stream(self, request: ChatRequest) -> AsyncIterator[Event]:
        await self.registry.refresh()
        model = self.pick_model(request.model)
        system = self.system_blocks(request.system)
        tools = self.tool_list()
        messages: list[dict] = [{"role": m["role"], "content": m["content"]} for m in request.messages]
        usage = Usage()
        spoke = False
        ends_clean = True

        async with asyncio.timeout(self.s.request_timeout):
            for _ in range(self.s.max_tool_iterations):
                kwargs = self.request_kwargs(model, system, messages, tools)
                new_block = False
                async with self._api(self.client, kwargs).stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type == "content_block_start" and event.content_block.type == "text":
                            new_block = True
                        elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                            text = event.delta.text
                            if new_block and spoke and not ends_clean and not text[:1].isspace():
                                text = " " + text  # keep words from different text blocks apart
                            new_block = False
                            spoke, ends_clean = True, text[-1:].isspace()
                            yield TextDelta(text)
                    final = await stream.get_final_message()
                usage.add(final.usage)

                if final.stop_reason == "refusal":
                    if not spoke:
                        yield TextDelta(t(self.s.language, "refusal"))
                    break
                if final.stop_reason == "pause_turn":  # a server tool (web search) paused: resume it
                    messages.append({"role": "assistant", "content": final.content})
                    continue
                tool_uses = [b for b in final.content if b.type == "tool_use"]
                if not tool_uses:
                    break
                if final.stop_reason == "max_tokens":
                    raise RuntimeError("tool input truncated by max_tokens")

                messages.append({"role": "assistant", "content": final.content})
                results = []
                for block in tool_uses:
                    arguments = dict(block.input) if isinstance(block.input, dict) else {}
                    yield ToolCall(block.name, arguments, block.id)
                    text, is_error = await self.registry.execute(block.name, arguments)
                    yield ToolResult(block.id, text, is_error)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": text,
                                    "is_error": is_error})
                messages.append({"role": "user", "content": results})
            else:
                yield TextDelta(t(self.s.language, "too_many_steps"))
        yield Done(usage={"model": model, **usage_record(model, usage)})

    async def close(self) -> None:
        for closer in (self.client.close, *self._extra_close):
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
