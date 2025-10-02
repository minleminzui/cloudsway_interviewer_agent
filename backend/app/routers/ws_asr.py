from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..utils.ws_manager import WebSocketManager

router = APIRouter()
manager = WebSocketManager()


@router.websocket("/ws/asr")
async def websocket_asr(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "default"
    await manager.connect(session_id, websocket)
    try:
        while True:
            message = await websocket.receive()
            if "text" in message:
                payload = message["text"].strip()
                if not payload:
                    continue
                await manager.send_json(session_id, {"type": "asr_final", "text": payload})
            elif "bytes" in message:
                await manager.send_json(session_id, {"type": "asr_partial", "text": "[音频数据接收]"})
    except WebSocketDisconnect:
        manager.disconnect(session_id)
