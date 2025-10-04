from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Set

from fastapi import WebSocket


LOGGER = logging.getLogger(__name__)


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
        self._pending_json: Dict[str, list[dict]] = {}

    async def register(self, sid: str, ws: WebSocket) -> None:
        LOGGER.info("Registering TTS peer handshake sid=%s", sid)
        await ws.accept()
        LOGGER.debug("Accepted TTS websocket sid=%s", sid)
        readiness_reset = False
        async with self._lock:
            peers = self._peers.setdefault(sid, set())
            peers.add(ws)
            peer_count = len(peers)
            ready_event = self._ready_events.get(sid)
            if ready_event is None:
                ready_event = asyncio.Event()
                self._ready_events[sid] = ready_event
                readiness_reset = True
        LOGGER.info(
            "Registered TTS peer sid=%s peers=%d readiness_reset=%s ready=%s",
            sid,
            peer_count,
            readiness_reset,
            self._ready_events.get(sid).is_set() if self._ready_events.get(sid) else False,
        )
        try:
            await ws.send_json({"type": "tts_ready", "mime": "audio/mpeg"})
        except BaseException as exc:
            readiness_reset = False
            remaining = 0
            async with self._lock:
                peers = self._peers.get(sid)
                if peers and ws in peers:
                    peers.remove(ws)
                    remaining = len(peers)
                    if not peers:
                        self._peers.pop(sid, None)
                        current_event = self._ready_events.get(sid)
                        if current_event is not None and current_event.is_set():
                            self._ready_events[sid] = asyncio.Event()
                            readiness_reset = True
                else:
                    if not peers:
                        self._peers.pop(sid, None)

            await self._maybe_close_websocket(ws)

            LOGGER.warning(
                (
                    "Failed to send readiness for sid=%s; dropping peer remaining=%d "
                    "readiness_reset=%s client_state=%s app_state=%s close_code=%s exc_type=%s"
                ),
                sid,
                remaining,
                readiness_reset,
                getattr(ws, "client_state", None),
                getattr(ws, "application_state", None),
                getattr(ws, "close_code", None),
                type(exc).__name__,
                exc_info=True,
            )
            raise
        else:
            ready_event.set()
            LOGGER.info(
                "Marked TTS session sid=%s ready; notifying waiters peers=%d",
                sid,
                peer_count,
            )
            await self._flush_pending_json(sid)

    async def unregister(self, sid: str, ws: WebSocket) -> None:
        readiness_reset = False
        peer_count = 0
        async with self._lock:
            peers = self._peers.get(sid)
            if peers and ws in peers:
                peers.remove(ws)
                peer_count = len(peers)
                if not peers:
                    self._peers.pop(sid, None)
                    # reset readiness so future waiters block until a new socket arrives
                    self._ready_events[sid] = asyncio.Event()
                    readiness_reset = True
            else:
                peer_count = len(peers) if peers else 0
                self._peers.pop(sid, None)
                ready_event = self._ready_events.get(sid)
                if ready_event is not None and ready_event.is_set():
                    self._ready_events.pop(sid, None)
                    readiness_reset = True
        LOGGER.info(
            "Unregistered TTS peer sid=%s peers=%d readiness_reset=%s ready=%s",
            sid,
            peer_count,
            readiness_reset,
            self._ready_events.get(sid).is_set() if self._ready_events.get(sid) else False,
        )

    async def wait_until_ready(self, sid: str) -> None:
        created = False
        async with self._lock:
            event = self._ready_events.get(sid)
            if event is None:
                event = asyncio.Event()
                self._ready_events[sid] = event
                created = True
            already_ready = event.is_set()
        LOGGER.info(
            "Waiting for TTS readiness sid=%s created=%s already_ready=%s",
            sid,
            created,
            already_ready,
        )
        await event.wait()
        LOGGER.info(
            "TTS readiness satisfied sid=%s ready=%s",
            sid,
            event.is_set(),
        )

    async def _broadcast_bytes(self, sid: str, payload: bytes) -> None:
        peers = await self._snapshot_peers(sid)
        await self._send_bytes_to_peers(sid, peers, payload)

    async def _broadcast_json(self, sid: str, payload: dict) -> None:
        payload = self._normalize_control_payload(payload)  # ✅ 加这一行
        json_type = payload.get("type")
        queueable_payload = (
            payload if json_type in {"tts_error", "tts_fallback", "tts_end"} else None
        )
        peers = await self._snapshot_peers(
            sid,
            queue_if_absent=queueable_payload is not None,
            payload=queueable_payload,
        )
        if not peers:
            if queueable_payload is not None:
                LOGGER.debug(
                    "Queued JSON payload for sid=%s while no peers connected: %s",
                    sid,
                    payload,
                )
            return
        await self._send_json_to_peers(sid, peers, payload)

    async def _snapshot_peers(
        self, sid: str, *, queue_if_absent: bool = False, payload: dict | None = None
    ) -> list[WebSocket]:
        async with self._lock:
            peers = list(self._peers.get(sid, ()))
            if peers or not queue_if_absent:
                return peers
            if payload is not None:
                queue = self._pending_json.setdefault(sid, [])
                queue.append(payload)
            return peers


    async def _flush_pending_json(self, sid: str) -> None:
        async with self._lock:
            pending_raw = self._pending_json.pop(sid, deque())
            if not isinstance(pending_raw, deque):
                pending_raw = deque(pending_raw)
        pending: Deque = deque()
        for payload in pending_raw:
            if isinstance(payload, dict):
                pending.append(self._normalize_control_payload(payload))
            else:
                pending.append(payload)
        while pending:
            peers = await self._snapshot_peers(sid)
            if not peers:
                async with self._lock:
                    queue = self._pending_json.setdefault(sid, deque())
                    queue.extend(pending)
                return
            payload = pending.popleft()
            await self._send_json_to_peers(sid, peers, payload)

    async def _send_json_to_peers(
        self, sid: str, peers: list[WebSocket], payload: dict
    ) -> None:
        if not peers:
            return
        to_drop: list[WebSocket] = []
        for ws in peers:
            try:
                await ws.send_json(payload)
            except Exception:
                LOGGER.error("Dropping TTS peer sid=%s due to json send error", sid, exc_info=True)
                to_drop.append(ws)
        for ws in to_drop:
            await self.unregister(sid, ws)

    async def _maybe_close_websocket(self, ws: WebSocket) -> None:
        close_callable = getattr(ws, "close", None)
        if not close_callable:
            return
        try:
            result = close_callable()  # type: ignore[operator]
            if inspect.isawaitable(result):
                await result
        except Exception:
            LOGGER.debug("Suppressing websocket close error after failed register", exc_info=True)

    async def send_audio_chunk(self, sid: str, chunk: bytes) -> None:
        await self._broadcast_bytes(sid, chunk)

    async def send_tts_end(self, sid: str) -> None:
        await self._broadcast_json(sid, {"type": "tts_end"})

    async def send_tts_error(self, sid: str, message: str) -> None:
        await self._broadcast_json(sid, {"type": "tts_error", "message": message})

    async def _flush_pending_json(self, sid: str) -> None:
        async with self._lock:
            pending = deque(self._pending_json.pop(sid, []))
        while pending:
            peers = await self._snapshot_peers(sid)
            if not peers:
                async with self._lock:
                    queue = self._pending_json.setdefault(sid, [])
                    queue.extend(pending)
                return
            payload = pending.popleft()
            await self._send_json_to_peers(sid, peers, payload)

    async def send_tts_fallback(self, sid: str, text: str, message: str | None = None) -> None:
        payload = {"type": "tts_fallback", "text": text}
        await self._broadcast_json(sid, payload)

    def _normalize_control_payload(self, payload: dict) -> dict:
        """Strip extraneous keys from control payloads to keep them minimal."""
        msg_type = payload.get("type")
        if msg_type == "tts_error":
            return {"type": "tts_error", "message": payload.get("message", "")}
        elif msg_type == "tts_fallback":
            return {"type": "tts_fallback", "text": payload.get("text", "")}
        elif msg_type == "tts_end":
            return {"type": "tts_end"}
        return payload

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

    async def debug_snapshot(self) -> Dict[str, int]:
        if not LOGGER.isEnabledFor(logging.DEBUG):
            return {}
        async with self._lock:
            return {sid: len(peers) for sid, peers in self._peers.items()}

    async def diagnostic_state(self, sid: str) -> dict:
        async with self._lock:
            peers = list(self._peers.get(sid, ()))
            ready_event = self._ready_events.get(sid)
            task = self._curr_task.get(sid)
            token = self._cancel_token.get(sid)
        return {
            "peers": len(peers),
            "ready_event": bool(ready_event),
            "ready_event_is_set": ready_event.is_set() if ready_event else False,
            "has_active_task": task is not None and not task.done(),
            "cancelled": token.is_cancelled() if token else False,
        }


manager = WsTtsManager()
