import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.routers import ws_agent
from app.schemas import PlanQuestion, PlanResponse, PlanSection
from app.services.agent import AgentDecision
from app.services.state_machine import InterviewStage


class DummyWebSocket:
    def __init__(self) -> None:
        self.query_params = {"session": "123", "topic": "demo"}

    async def receive_json(self) -> dict:
        raise WebSocketDisconnect()


class DummyManager:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def connect(self, session_id: str, websocket: DummyWebSocket) -> None:
        return None

    async def send_json(self, session_id: str, payload: dict) -> None:
        self.sent.append((session_id, payload))

    def disconnect(self, session_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_initial_tts_uses_question(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_manager = DummyManager()
    monkeypatch.setattr(ws_agent, "manager", dummy_manager)

    outline = PlanResponse(
        topic="demo",
        sections=[
            PlanSection(stage="背景", questions=[PlanQuestion(question="q1")])
        ],
    )
    async def fake_build(topic: str) -> PlanResponse:
        return outline

    monkeypatch.setattr(ws_agent.outline_builder, "build", fake_build)

    machine = SimpleNamespace(data=SimpleNamespace(stage=InterviewStage.OPENING))

    async def fake_ensure(session_id: str, topic: str, received_outline: PlanResponse):
        assert received_outline is outline
        return machine

    monkeypatch.setattr(ws_agent.agent_orchestrator, "ensure_session", fake_ensure)

    decision = AgentDecision(
        action="followup",
        question="请介绍一下公司的产品亮点",
        stage=InterviewStage.OPENING,
        rationale="test",
    )

    async def fake_bootstrap(session_id: str) -> AgentDecision:
        return decision

    monkeypatch.setattr(ws_agent.agent_orchestrator, "bootstrap_decision", fake_bootstrap)

    calls: list[tuple[str, str]] = []

    async def fake_stream(session_id: str, text: str) -> None:
        calls.append((session_id, text))

    monkeypatch.setattr(ws_agent, "stream_and_broadcast", fake_stream)

    await ws_agent.websocket_agent(DummyWebSocket())
    await asyncio.sleep(0)

    assert calls == [("123", "请介绍一下公司的产品亮点")]
