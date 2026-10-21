"""Ollama-compatible HTTP API (what Home Assistant's Ollama integration talks to).

The app sits behind HA's "Ollama" conversation agent. Every request that reaches it is a fallback: Assist
could not handle the phrase locally. Each one is answered by the backend and recorded for later analysis.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .backends import Backend, ChatRequest, Done, TextDelta, ToolCall, ToolResult
from .budget import Budget
from .config import Settings
from .i18n import t
from .store import Store

log = logging.getLogger(__name__)

OLLAMA_VERSION = "0.12.0"
MAX_RECORDED_RESULT = 600


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_app(settings: Settings, backend: Backend, store: Store, budget: Budget | None = None) -> FastAPI:
    networks = [ipaddress.ip_network(n, strict=False) for n in settings.allowed_networks]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await backend.close()

    app = FastAPI(title="voice-assist-improver", lifespan=lifespan)

    @app.middleware("http")
    async def network_filter(request: Request, call_next):
        host = request.client.host if request.client else ""
        try:
            ip = ipaddress.ip_address(host)
            allowed = any(ip in n for n in networks)
        except ValueError:
            allowed = False
        if not allowed:
            log.warning("request denied for %s", host or "?")
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)

    def resolve_model(name: str | None) -> str | None:
        base = (name or settings.models[0]).split(":")[0]
        return base if base in settings.models else None

    @app.get("/")
    async def root():
        return PlainTextResponse("Ollama is running")

    @app.get("/api/version")
    async def version():
        return {"version": OLLAMA_VERSION}

    @app.get("/api/tags")
    async def tags():
        return {"models": [
            {"name": f"{m}:latest", "model": f"{m}:latest", "modified_at": _now(), "size": 0, "digest": "",
             "details": {"format": "api", "family": "llm", "families": ["llm"],
                         "parameter_size": "", "quantization_level": ""}}
            for m in settings.models
        ]}

    @app.post("/api/show")
    async def show(request: Request):
        body = await request.json()
        if resolve_model(body.get("model") or body.get("name")) is None:
            return JSONResponse({"error": "model not found"}, status_code=404)
        return {"details": {"family": "llm"}, "model_info": {}, "capabilities": ["completion"]}

    @app.post("/api/chat")
    async def chat(request: Request):
        body = await request.json()
        model = resolve_model(body.get("model"))
        if model is None:
            return JSONResponse({"error": f"model '{body.get('model')}' not found"}, status_code=404)
        raw_messages = body.get("messages") or []
        system = "\n".join(
            m["content"] for m in raw_messages if m.get("role") == "system" and m.get("content")) or None
        turns = [m for m in raw_messages
                 if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()]
        stream = body.get("stream", True)
        name = body.get("model") or model
        caller = request.client.host if request.client else "unknown"
        req = ChatRequest(model=model, messages=turns, system=system, client=caller)
        started = time.monotonic()

        async def events() -> AsyncIterator[str]:
            """Yield reply text chunks; record the interaction when the stream ends, however it ends."""
            parts: list[str] = []
            tools: list[dict] = []
            first_ms: int | None = None
            error: str | None = None
            usage: dict | None = None
            try:
                if budget is not None and budget.exceeded():
                    error = "budget_exceeded"
                    message = t(settings.language, "budget_reached")
                    parts.append(message)
                    yield message
                    return
                async for ev in backend.stream(req):
                    if isinstance(ev, TextDelta):
                        if first_ms is None:
                            first_ms = int((time.monotonic() - started) * 1000)
                        parts.append(ev.text)
                        yield ev.text
                    elif isinstance(ev, ToolCall):
                        tools.append({"id": ev.id, "name": ev.name, "input": ev.input})
                    elif isinstance(ev, ToolResult):
                        for tool in tools:
                            if ev.id and tool.get("id") == ev.id:
                                tool["result"] = ev.output[:MAX_RECORDED_RESULT]
                                tool["is_error"] = ev.is_error
                    elif isinstance(ev, Done):
                        usage = ev.usage
                        break
            except Exception as exc:  # fail soft: speak an apology instead of an HTTP error
                error = f"{type(exc).__name__}: {exc}"
                log.error("backend failed: %s", error)
                if not parts:
                    apology = t(settings.language, "backend_error")
                    parts.append(apology)
                    yield apology
            finally:
                try:
                    last_user = next((m["content"] for m in reversed(turns) if m["role"] == "user"), "")
                    store.add_interaction(
                        utterance=last_user.strip(), reply="".join(parts), client=caller,
                        model=(usage or {}).get("model", model),
                        backend=backend.name, tools=tools,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        first_text_ms=first_ms, error=error, usage=usage)
                except Exception:  # recording must never break the voice path
                    log.exception("could not record the interaction")

        def chunk(text: str) -> bytes:
            return (json.dumps({"model": name, "created_at": _now(),
                                "message": {"role": "assistant", "content": text}, "done": False},
                               ensure_ascii=False) + "\n").encode()

        def final(total: str) -> dict:
            elapsed = int((time.monotonic() - started) * 1e9)
            return {"model": name, "created_at": _now(),
                    "message": {"role": "assistant", "content": "" if stream else total},
                    "done": True, "done_reason": "stop", "total_duration": elapsed,
                    "load_duration": 0, "prompt_eval_count": 0, "prompt_eval_duration": 0,
                    "eval_count": len(total.split()), "eval_duration": 0}

        if not stream:
            text = "".join([c async for c in events()])
            return JSONResponse(final(text))

        async def body_stream():
            total: list[str] = []
            async for text in events():
                total.append(text)
                yield chunk(text)
            yield (json.dumps(final("".join(total)), ensure_ascii=False) + "\n").encode()

        return StreamingResponse(body_stream(), media_type="application/x-ndjson")

    return app
