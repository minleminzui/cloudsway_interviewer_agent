from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.agent import agent_orchestrator
from ..services.outline import outline_builder
from ..utils.ws_manager import WebSocketManager
from .ws_tts import stream_text

router = APIRouter()
manager = WebSocketManager()


@router.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "0"
    topic = websocket.query_params.get("topic") or "未命名采访"
    await manager.connect(session_id, websocket)
    outline = outline_builder.build(topic)
    machine = await agent_orchestrator.ensure_session(session_id, topic, outline)
    await manager.send_json(session_id, {"type": "outline", "payload": outline.model_dump()})
    first_question = machine.next_question()
    await manager.send_json(
        session_id,
        {
            "type": "policy",
            "action": "ask",
            "question": first_question,
            "stage": machine.data.stage.value,
            "notes": [],
        },
    )
    await stream_text(session_id, first_question)
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
                    },
                )
                await stream_text(session_id, decision.question)
            elif event_type == "barge_in":
                await manager.send_json(session_id, {"type": "ack", "event": "barge_in"})
            elif event_type == "control":
                await manager.send_json(session_id, {"type": "ack", "event": data.get("command", "")})
    except WebSocketDisconnect:
        manager.disconnect(session_id)
