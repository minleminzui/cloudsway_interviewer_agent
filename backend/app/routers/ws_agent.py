from __future__ import annotations

import logging
import json

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.tts_client import stream_and_broadcast
from ..core.ws_tts_manager import manager as tts_manager
from ..services.agent import agent_orchestrator
from ..services.outline import outline_builder
from ..utils.ws_manager import WebSocketManager

LOGGER = logging.getLogger(__name__)
router = APIRouter()
manager = WebSocketManager()


@router.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "0"
    topic = websocket.query_params.get("topic") or "未命名采访"
    await manager.connect(session_id, websocket)
    outline = await outline_builder.build(topic)
    machine = await agent_orchestrator.ensure_session(session_id, topic, outline)
    await manager.send_json(session_id, {"type": "outline", "payload": outline.model_dump()})
    first_decision = await agent_orchestrator.bootstrap_decision(session_id)
    await manager.send_json(
        session_id,
        {
            "type": "policy",
            "action": first_decision.action,
            "question": first_decision.question,
            "stage": machine.data.stage.value,
            "notes": [],
            "rationale": first_decision.rationale,
        },
    )
    asyncio.create_task(stream_and_broadcast(session_id, first_decision.question))
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            if event_type == "user_turn":
                text = data.get("text", "")
                if not text:
                    continue
                decision = await agent_orchestrator.handle_user_turn(session_id, text)
                await manager.send_json(
                    session_id,
                    {
                        "type": "policy",
                        "action": decision.action,
                        "question": decision.question,
                        "stage": decision.stage.value,
                        "notes": decision.notes,
                        "rationale": decision.rationale,
                    },
                )
                asyncio.create_task(stream_and_broadcast(session_id, decision.question))
            elif event_type == "barge_in":
                tts_manager.cancel(session_id)
                await manager.send_json(session_id, {"type": "ack", "event": "barge_in"})
            elif event_type == "control":
                await manager.send_json(session_id, {"type": "ack", "event": data.get("command", "")})
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        if "WebSocket is not connected" in str(exc):
            LOGGER.debug("Agent websocket closed before accept: %s", exc)
        else:
            LOGGER.exception("Unexpected agent websocket runtime error")
            raise
    finally:
        manager.disconnect(session_id)
