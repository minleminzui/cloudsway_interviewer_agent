# app/routers/ws_tts.py
from __future__ import annotations
import logging, contextlib
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..core.ws_tts_manager import manager as local_tts_manager
from ..utils.ws_manager import WebSocketManager

router = APIRouter()
LOGGER = logging.getLogger(__name__)

# 本地兜底（运行时由 app.state.ws_manager 覆盖）
manager = WebSocketManager()


@router.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket) -> None:
    await websocket.accept()   # ✅ 必须加上这一行
    session_id = websocket.query_params.get("session") or "default"
    mgr: WebSocketManager = getattr(websocket.app.state, "ws_manager", manager)
    LOGGER.info(f"[tts] 🔵 connected sid={session_id}")

    try:
        # ⚠️ 不要再 accept，这个在 ws_tts_manager.register 里会自动 accept
        await local_tts_manager.register(session_id, websocket)

        # ✅ 通知全局 manager：TTS ready
        await mgr.notify_ready(session_id, "tts")
        LOGGER.info(f"[tts] ✅ ready sid={session_id}")

        # 循环监听客户端消息（如心跳）
        while True:
            msg = await websocket.receive_text()
            LOGGER.debug(f"[tts] ↩️ msg sid={session_id}: {msg[:100]}")
    except WebSocketDisconnect:
        LOGGER.info(f"[tts] 🔴 disconnected sid={session_id}")
    except Exception as e:
        LOGGER.exception(f"[tts] ❌ error sid={session_id}: {e}")
    finally:
        with contextlib.suppress(Exception):
            await local_tts_manager.unregister(session_id, websocket)
        await mgr.disconnect(session_id)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
        LOGGER.info(f"[tts] 🧹 cleaned sid={session_id}")
