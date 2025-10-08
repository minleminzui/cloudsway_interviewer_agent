# app/utils/ws_manager.py
from __future__ import annotations
import asyncio
import contextlib
import logging
import time
from typing import Dict, List, Optional
from fastapi import WebSocket, WebSocketDisconnect
import aiohttp, base64, json, os, asyncio
from app.core.tts_client import stream_and_broadcast
LOGGER = logging.getLogger(__name__)

class WebSocketManager:
    """统一管理 Agent / ASR / TTS 的 WebSocket 会话"""
    def __init__(self):
        self._lock = asyncio.Lock()
        self._connections: Dict[str, List[WebSocket]] = {}
        self._ready: Dict[str, Dict[str, asyncio.Event]] = {}

    # ============================================================
    # 🔹 基础连接管理
    # ============================================================
    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        try:
            if websocket.client_state.name != "CONNECTED":
                await websocket.accept()
        except RuntimeError as e:
            if "websocket.accept" not in str(e):
                raise
        async with self._lock:
            self._connections.setdefault(session_id, []).append(websocket)
        LOGGER.info(f"[ws_manager] connected sid={session_id} total={len(self._connections[session_id])}")

    async def disconnect(self, session_id: str, websocket: Optional[WebSocket] = None) -> None:
        async with self._lock:
            peers = self._connections.get(session_id, [])
            if websocket:
                if websocket in peers:
                    peers.remove(websocket)
                    with contextlib.suppress(Exception):
                        await websocket.close()
            else:
                for ws in peers:
                    with contextlib.suppress(Exception):
                        await ws.close()
                peers.clear()
            if not peers:
                self._connections.pop(session_id, None)
                self._ready.pop(session_id, None)
        LOGGER.info(f"[ws_manager] disconnected sid={session_id}")

    async def send_json(self, session_id: str, data: dict) -> None:
        async with self._lock:
            peers = list(self._connections.get(session_id, []))
        for ws in peers:
            try:
                await ws.send_json(data)
            except WebSocketDisconnect:
                await self.disconnect(session_id, ws)
            except Exception as e:
                LOGGER.warning(f"[ws_manager] send_json failed sid={session_id}: {e}")
                await self.disconnect(session_id, ws)

    async def send_bytes(self, session_id: str, data: bytes) -> None:
        async with self._lock:
            peers = list(self._connections.get(session_id, []))
        for ws in peers:
            try:
                await ws.send_bytes(data)
            except WebSocketDisconnect:
                await self.disconnect(session_id, ws)
            except Exception as e:
                LOGGER.warning(f"[ws_manager] send_bytes failed sid={session_id}: {e}")
                await self.disconnect(session_id, ws)

    # ============================================================
    # 🔹 Ready 状态管理
    # ============================================================
    def _get_ready_event(self, sid: str, role: str) -> asyncio.Event:
        if sid not in self._ready:
            self._ready[sid] = {}
        if role not in self._ready[sid]:
            self._ready[sid][role] = asyncio.Event()
        return self._ready[sid][role]

    async def notify_ready(self, sid: str, role: str) -> None:
        ev = self._get_ready_event(sid, role)
        ev.set()
        LOGGER.info(f"[ws_manager] ✅ {role.upper()} ready sid={sid}")

    async def wait_ready(self, sid: str, role: str, timeout: float = 15.0) -> bool:
        ev = self._get_ready_event(sid, role)
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            LOGGER.info(f"[ws_manager] ⏳ wait_ready success for {role} sid={sid}")
            return True
        except asyncio.TimeoutError:
            LOGGER.warning(f"[ws_manager] ⚠️ wait_ready timeout for {role} sid={sid}")
            return False

    async def wait_all_ready(self, sid: str, roles: list[str], timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready_roles = {r for r, ev in self._ready.get(sid, {}).items() if ev.is_set()}
            if all(r in ready_roles for r in roles):
                LOGGER.info(f"[ws_manager] ✅ all ready {roles} sid={sid}")
                return True
            await asyncio.sleep(0.05)
        LOGGER.warning(f"[ws_manager] ⚠️ wait_all_ready timeout {roles} sid={sid}")
        return False

    # ============================================================
    # 🔹 调试辅助
    # ============================================================
    def active_sessions(self) -> Dict[str, int]:
        return {sid: len(peers) for sid, peers in self._connections.items()}

    # ============================================================
    # 🔹 TTS：火山引擎语音合成 + WebSocket 推送
    # ============================================================
    async def send_to_tts(self, session_id: str, text: str) -> None:
        if not text or not text.strip():
            return
        try:
            # 直接 await，出错能打到后台日志
            await stream_and_broadcast(session_id, text.strip())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LOGGER.exception(f"[ws_manager] send_to_tts failed sid={session_id}: {e}")