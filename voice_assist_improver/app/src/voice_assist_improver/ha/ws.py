"""Minimal Home Assistant websocket client."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import websockets

from ..config import Settings


class HAError(Exception):
    pass


class HAWebSocket:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0

    async def call(self, msg: dict):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, **msg}))
        while True:
            reply = json.loads(await self.ws.recv())
            if reply.get("id") == self.n:
                if not reply.get("success", True):
                    raise HAError(str((reply.get("error") or {}).get("message", reply.get("error"))))
                return reply.get("result")


@asynccontextmanager
async def connect(settings: Settings) -> AsyncIterator[HAWebSocket]:
    url = settings.ha_url.replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(url, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": settings.ha_token}))
        if json.loads(await ws.recv()).get("type") != "auth_ok":
            raise HAError("authentication with Home Assistant failed")
        yield HAWebSocket(ws)
