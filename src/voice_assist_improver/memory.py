"""Remember what the assistant did in earlier turns of the same conversation.

Home Assistant's Ollama agent resends the conversation each time, but only as text: the tool calls this app
ran for a turn never reach it (HA has no tools of its own here), so they never come back. Without them the
model sees "Done, I turned it on" with no action behind it, concludes it was lying and "corrects" itself,
sometimes by doing something the user did not ask for.

The app keeps every interaction with its tool calls and results, so it can put them back: each earlier
assistant message is matched to the stored interaction that produced it and gets its tool trace attached.
"""
from __future__ import annotations

from .text import norm

MAX_REPLAYED_RESULT = 1500
LOOKBACK_SECONDS = 24 * 3600


def index_interactions(interactions: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Tool traces by (utterance, reply), newest wins. Failed interactions and ones without tools are
    skipped."""
    index: dict[tuple[str, str], list[dict]] = {}
    for row in sorted(interactions, key=lambda r: r["ts"]):
        if row.get("error") or not row.get("tools"):
            continue
        index[(norm(row["utterance"]), norm(row.get("reply") or ""))] = row["tools"]
    return index


def attach_tool_traces(turns: list[dict], index: dict[tuple[str, str], list[dict]]) -> list[dict]:
    """Copy of `turns` where an assistant message that followed a known interaction carries `tools`."""
    out: list[dict] = []
    for i, turn in enumerate(turns):
        turn = dict(turn)
        if turn["role"] == "assistant" and i > 0 and turns[i - 1]["role"] == "user":
            tools = index.get((norm(turns[i - 1]["content"]), norm(turn["content"])))
            if tools:
                turn["tools"] = tools
        out.append(turn)
    return out


def expand_messages(turns: list[dict], available: set[str]) -> list[dict]:
    """Anthropic messages for `turns`: an assistant message with a trace becomes
    assistant tool_use blocks, the user tool_result blocks, then the assistant's spoken text.

    A trace is replayed only if every tool in it still exists; replaying one that does not would invite the
    model to call something it no longer has."""
    messages: list[dict] = []
    used: set[str] = set()  # the API rejects a request that repeats a tool_use id
    for turn in turns:
        tools = turn.get("tools")
        if turn["role"] == "assistant" and tools and all(t.get("name") in available for t in tools):
            calls, results = [], []
            for n, t in enumerate(tools):
                call_id = t.get("id") or f"toolu_history_{len(messages)}_{n}"
                while call_id in used:  # the same exchange said twice reuses one stored trace
                    call_id += "_again"
                used.add(call_id)
                calls.append({"type": "tool_use", "id": call_id, "name": t["name"],
                              "input": t.get("input") or {}})
                content = str(t.get("result") or "(no result recorded)")[:MAX_REPLAYED_RESULT]
                results.append({"type": "tool_result", "tool_use_id": call_id, "content": content,
                                "is_error": bool(t.get("is_error"))})
            messages += [{"role": "assistant", "content": calls}, {"role": "user", "content": results}]
        messages.append({"role": turn["role"], "content": turn["content"]})
    return messages
