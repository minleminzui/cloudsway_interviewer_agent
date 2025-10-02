from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services import tts
from ..utils.ws_manager import WebSocketManager

router = APIRouter()
manager = WebSocketManager()


@router.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "default"
    await manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id)


async def stream_text(session_id: str, text: str) -> None:
    payload = tts.synthesize(text)
    chunk_size = 4096
    for start in range(0, len(payload), chunk_size):
        await manager.send_bytes(session_id, payload[start:start + chunk_size])
    await manager.send_json(session_id, {"type": "tts_end"})
