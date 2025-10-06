# app/routers/ws_tts.py
from __future__ import annotations

import logging
import contextlib
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.ws_tts_manager import manager

router = APIRouter()
LOGGER = logging.getLogger(__name__)


@router.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket) -> None:
    """Handle TTS WebSocket connections from frontend."""
    session_id = websocket.query_params.get("session") or "default"
    LOGGER.info(f"[ws_tts] 🔵 Incoming TTS websocket connection sid={session_id}")

    try:
        await manager.register(session_id, websocket)
    except WebSocketDisconnect as exc:
        LOGGER.warning(f"[ws_tts] ⚠️ TTS websocket disconnected early sid={session_id}, code={exc.code}")
        with contextlib.suppress(Exception):
            await manager.unregister(session_id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
        return
    except Exception as e:
        LOGGER.exception(f"[ws_tts] ❌ Registration failed sid={session_id}: {e}")
        await manager.unregister(session_id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
        raise

    LOGGER.info(f"[ws_tts] ✅ Registered sid={session_id}, start receiving loop")
    try:
        while True:
            msg = await websocket.receive_text()
            LOGGER.debug(f"[ws_tts] ↩️ Received inbound msg sid={session_id}: {msg[:100]}")
    except WebSocketDisconnect as exc:
        LOGGER.info(f"[ws_tts] 🔴 WebSocket closed sid={session_id}, code={exc.code}")
        await manager.unregister(session_id, websocket)
    except Exception as e:
        LOGGER.exception(f"[ws_tts] ❌ Error in receive loop sid={session_id}: {e}")
        await manager.unregister(session_id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
