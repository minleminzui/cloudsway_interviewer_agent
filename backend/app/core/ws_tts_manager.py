# app/core/ws_tts_manager.py
from __future__ import annotations
import asyncio
import logging
from typing import Dict, List
from fastapi import WebSocket

LOGGER = logging.getLogger(__name__)


class TTSStreamToken:
    """Handle to cancel or check a running TTS stream task."""
    def __init__(self, task: asyncio.Task):
        self.task = task
        self._cancelled = False

    def cancel(self):
        if not self._cancelled:
            self._cancelled = True
            if not self.task.done():
                self.task.cancel()

    def is_cancelled(self) -> bool:
        return self._cancelled


class TTSManager:
    def __init__(self):
        self.active_peers: Dict[str, List[WebSocket]] = {}
        self.ready_events: Dict[str, asyncio.Event] = {}
        self.stream_tasks: Dict[str, asyncio.Task] = {}

    # ------------------------------
    # 注册 & 注销
    # ------------------------------
    async def register(self, sid: str, ws: WebSocket):
        """Accept a WebSocket and mark it as ready."""
        await ws.accept()
        peers = self.active_peers.setdefault(sid, [])
        peers.append(ws)
        LOGGER.info(f"[TTS] 🟢 Registered peer sid={sid}, total={len(peers)}")

        ready_event = self.ready_events.setdefault(sid, asyncio.Event())
        try:
            await ws.send_json({"type": "tts_ready", "mime": "audio/mpeg"})
            LOGGER.info(f"[TTS] ✅ sent tts_ready for sid={sid}")
        except Exception as e:
            LOGGER.exception(f"[TTS] ❌ Failed to send ready for sid={sid}: {e}")

        ready_event.set()
        LOGGER.info(f"[TTS] 🔔 ready_event.set() sid={sid}")

    async def unregister(self, sid: str, ws: WebSocket):
        peers = self.active_peers.get(sid, [])
        if ws in peers:
            peers.remove(ws)
            LOGGER.info(f"[TTS] 🧹 Unregistered peer sid={sid}, remaining={len(peers)}")
        if not peers:
            self.active_peers.pop(sid, None)
            self.ready_events.pop(sid, None)
            LOGGER.info(f"[TTS] ⚪ No remaining peers for sid={sid}, cleaned up")

    # ------------------------------
    # 广播方法
    # ------------------------------
    async def _broadcast_json(self, sid: str, payload: dict):
        peers = self.active_peers.get(sid, [])
        if not peers:
            LOGGER.warning(f"[TTS] ⚠️ no peers to send JSON sid={sid}")
            return
        for ws in list(peers):
            try:
                await ws.send_json(payload)
            except Exception as e:
                LOGGER.warning(f"[TTS] ❌ send_json failed sid={sid}: {e}")
                await self.unregister(sid, ws)

    async def _broadcast_binary(self, sid: str, chunk: bytes):
        peers = self.active_peers.get(sid, [])
        if not peers:
            LOGGER.warning(f"[TTS] ⚠️ no peers to send binary sid={sid}")
            return
        for ws in list(peers):
            try:
                await ws.send_bytes(chunk)
            except Exception as e:
                LOGGER.warning(f"[TTS] ❌ send_bytes failed sid={sid}: {e}")
                await self.unregister(sid, ws)

    # ------------------------------
    # 控制接口
    # ------------------------------
    async def send_tts_end(self, sid: str):
        LOGGER.debug(f"[TTS] 📤 send_tts_end sid={sid}")
        await self._broadcast_json(sid, {"type": "tts_end"})

    async def send_tts_error(self, sid: str, message: str):
        LOGGER.debug(f"[TTS] 📤 send_tts_error sid={sid}, msg={message}")
        await self._broadcast_json(sid, {"type": "tts_error", "message": message})

    async def send_tts_fallback(self, sid: str, text: str, message: str):
        LOGGER.debug(f"[TTS] 📤 send_tts_fallback sid={sid}, reason={message}")
        await self._broadcast_json(sid, {"type": "tts_fallback", "text": text, "message": message})

    async def send_audio_chunk(self, sid: str, chunk: bytes):
        LOGGER.debug(f"[TTS] 📤 send_audio_chunk sid={sid}, len={len(chunk)}")
        await self._broadcast_binary(sid, chunk)

    # ------------------------------
    # 状态控制
    # ------------------------------
    async def wait_until_ready(self, sid: str):
        event = self.ready_events.setdefault(sid, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=15)
            LOGGER.info(f"[TTS] ✅ wait_until_ready completed sid={sid}")
        except asyncio.TimeoutError:
            LOGGER.warning(f"[TTS] ⏰ wait_until_ready timeout sid={sid}")

    def start_stream(self, sid: str, task: asyncio.Task) -> TTSStreamToken:
        LOGGER.debug(f"[TTS] ▶️ start_stream sid={sid}")
        token = TTSStreamToken(task)
        self.stream_tasks[sid] = task
        return token

    def is_cancelled(self, sid: str) -> bool:
        task = self.stream_tasks.get(sid)
        return not task or task.done()

    def finish_stream(self, sid: str, task: asyncio.Task):
        existing = self.stream_tasks.get(sid)
        if existing == task:
            self.stream_tasks.pop(sid, None)
            LOGGER.info(f"[TTS] 🏁 finish_stream sid={sid}")


# ✅ 全局单例
manager = TTSManager()
