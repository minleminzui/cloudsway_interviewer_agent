# app/routers/ws_agent.py
from __future__ import annotations
import asyncio, contextlib, json, logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..utils.ws_manager import WebSocketManager
from ..services.agent import agent_orchestrator
from ..core.ws_tts_manager import manager as tts_manager

LOGGER = logging.getLogger(__name__)
router = APIRouter()
manager = WebSocketManager()


@router.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    """Agent WebSocket 主入口：负责协调 ASR / TTS / LLM"""
    session_id = websocket.query_params.get("session") or "default"
    topic = websocket.query_params.get("topic") or ""
    LOGGER.info(f"[agent] 🧠 accepted ws sid={session_id} topic={topic}")

    ws_manager: WebSocketManager = getattr(websocket.app.state, "ws_manager", manager)

    try:
        # ✅ 接入管理器
        await ws_manager.connect(session_id, websocket)
        await ws_manager.send_json(session_id, {"type": "agent_connected", "topic": topic})

        # ✅ Step 1: 初始化采访状态机与首轮问题
        machine = await agent_orchestrator.ensure_session(session_id, topic)
        decision = await agent_orchestrator.bootstrap_decision(session_id)
        first_question = decision.question.strip()
        LOGGER.info(f"[agent] 🎬 first question sid={session_id}: {first_question[:80]}...")

        # ✅ Step 2: 推送给前端（文本 + 语音）
        await ws_manager.send_json(session_id, {
            "type": "agent_reply",
            "text": first_question,
            "stage": decision.stage.value,
        })

        # ✅ Step 3: 调用火山引擎 TTS 播报采访人开场白
        await tts_manager.wait_until_ready(session_id)
        await ws_manager.send_to_tts(session_id, first_question)
        LOGGER.info(f"[agent] 🔊 sent first question to TTS sid={session_id}")

        # 主循环：等受访者发 query
        while True:
            # 🧩 检查 websocket 状态
            if websocket.client_state == WebSocketState.DISCONNECTED:
                LOGGER.warning(f"[agent] ⚠️ websocket already closed sid={session_id}")
                break

            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                LOGGER.info(f"[agent] 🔴 disconnected sid={session_id}")
                break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                # 🧩 关键修复点：出现 “not connected” 时直接 break
                if "not connected" in str(e).lower():
                    LOGGER.warning(f"[agent] ⚠️ websocket broken sid={session_id}, stop loop.")
                    break
                LOGGER.warning(f"[agent] ⚠️ receive error sid={session_id}: {e}")
                await asyncio.sleep(0.2)
                continue

            msg_type = data.get("type")
            LOGGER.info(f"[agent] 📩 recv {msg_type} sid={session_id}")

            if msg_type == "query":
                query_text = data.get("text", "").strip()
                if not query_text:
                    continue
                await ws_manager.send_json(session_id, {"type": "agent_ack", "text": query_text})

                # 由 Orchestrator 决策下一问
                decision = await agent_orchestrator.handle_user_turn(session_id, query_text)
                next_question = decision.question.strip()

                await ws_manager.send_json(session_id, {
                    "type": "agent_reply",
                    "text": next_question,
                    "stage": decision.stage.value,
                })
                await ws_manager.send_to_tts(session_id, next_question)
                LOGGER.info(f"[agent] 🔊 sent follow-up to TTS sid={session_id}")

            elif msg_type == "stop":
                await ws_manager.send_json(session_id, {"type": "agent_stopped"})
                break

            else:
                await ws_manager.send_json(session_id, {"type": "agent_unknown", "data": data})

    except Exception as e:
        LOGGER.exception(f"[agent] ❌ exception sid={session_id}: {e}")
        with contextlib.suppress(Exception):
            await websocket.close()

    finally:
        await ws_manager.disconnect(session_id)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
        LOGGER.info(f"[agent] 🧹 cleaned sid={session_id}")
