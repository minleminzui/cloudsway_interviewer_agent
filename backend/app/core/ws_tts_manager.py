from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Set

from fastapi import WebSocket


@dataclass
class CancellationToken:
    _event: asyncio.Event = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class WsTtsManager:
    """Manage TTS websocket peers per session and allow stream cancellation."""

    def __init__(self) -> None:
        self._peers: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._ready_events: Dict[str, asyncio.Event] = {}
        self._curr_task: Dict[str, asyncio.Task] = {}
        self._cancel_token: Dict[str, CancellationToken] = {}

    async def register(self, sid: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            peers = self._peers.setdefault(sid, set())
            peers.add(ws)
            event = self._ready_events.get(sid)
            if event is None:
                event = asyncio.Event()
                self._ready_events[sid] = event
            event.set()
        await ws.send_json({"type": "tts_ready"})

    async def unregister(self, sid: str, ws: WebSocket) -> None:
        async with self._lock:
            peers = self._peers.get(sid)
            if peers and ws in peers:
                peers.remove(ws)
                if not peers:
                    self._peers.pop(sid, None)
                    # reset readiness so future waiters block until a new socket arrives
                    self._ready_events[sid] = asyncio.Event()
            else:
                self._peers.pop(sid, None)
                self._ready_events.pop(sid, None)

    async def wait_until_ready(self, sid: str) -> None:
        async with self._lock:
            event = self._ready_events.get(sid)
            if event is None:
                event = asyncio.Event()
                self._ready_events[sid] = event
        await event.wait()

    async def _broadcast_bytes(self, sid: str, payload: bytes) -> None:
        peers = list(self._peers.get(sid, ()))
        to_drop: list[WebSocket] = []
        for ws in peers:
            try:
                await ws.send_bytes(payload)
            except Exception:
                to_drop.append(ws)
        for ws in to_drop:
            await self.unregister(sid, ws)

    async def _broadcast_json(self, sid: str, payload: dict) -> None:
        peers = list(self._peers.get(sid, ()))
        to_drop: list[WebSocket] = []
        for ws in peers:
            try:
                await ws.send_json(payload)
            except Exception:
                to_drop.append(ws)
        for ws in to_drop:
            await self.unregister(sid, ws)

    async def send_audio_chunk(self, sid: str, chunk: bytes) -> None:
        await self._broadcast_bytes(sid, chunk)

    async def send_tts_end(self, sid: str) -> None:
        await self._broadcast_json(sid, {"type": "tts_end"})

    def start_stream(self, sid: str, task: asyncio.Task) -> CancellationToken:
        self.cancel(sid)
        token = CancellationToken()
        self._cancel_token[sid] = token
        self._curr_task[sid] = task
        return token

    def finish_stream(self, sid: str, task: asyncio.Task) -> None:
        if self._curr_task.get(sid) is task:
            self._curr_task.pop(sid, None)
            self._cancel_token.pop(sid, None)

    def is_cancelled(self, sid: str) -> bool:
        token = self._cancel_token.get(sid)
        return bool(token and token.is_cancelled())

    def cancel(self, sid: str) -> None:
        token = self._cancel_token.get(sid)
        if token and not token.is_cancelled():
            token.cancel()
        task = self._curr_task.get(sid)
        if task and not task.done():
            task.cancel()


manager = WsTtsManager()
