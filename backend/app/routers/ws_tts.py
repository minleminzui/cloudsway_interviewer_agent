from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.ws_tts_manager import manager

router = APIRouter()


@router.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "default"
    await manager.register(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.unregister(session_id, websocket)
