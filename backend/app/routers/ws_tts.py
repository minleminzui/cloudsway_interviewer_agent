from __future__ import annotations

import logging

import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.ws_tts_manager import manager

router = APIRouter()

LOGGER = logging.getLogger(__name__)


@router.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "default"
    LOGGER.info("Incoming TTS websocket connection sid=%s", session_id)
    try:
        await manager.register(session_id, websocket)
    except WebSocketDisconnect as exc:
        LOGGER.info(
            "TTS websocket disconnected during registration sid=%s code=%s", session_id, exc.code
        )
        with contextlib.suppress(Exception):
            await manager.unregister(session_id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
        return
    except Exception:
        LOGGER.exception("TTS websocket registration failed sid=%s", session_id)
        await manager.unregister(session_id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
        raise
    LOGGER.info("TTS websocket registered sid=%s", session_id)
    try:
        while True:
            await websocket.receive_text()
            LOGGER.debug("Discarded inbound message on TTS websocket sid=%s", session_id)
    except WebSocketDisconnect as exc:
        LOGGER.info("TTS websocket disconnected sid=%s code=%s", session_id, exc.code)
        await manager.unregister(session_id, websocket)
