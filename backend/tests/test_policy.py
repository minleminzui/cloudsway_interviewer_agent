import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.config import settings
from app.core import llm
from app.services.agent import AgentOrchestrator
from app.services.policy import PolicyError, decide_policy
from app.services.state_machine import InterviewStage, StateMachine
from app.schemas import PlanQuestion, PlanResponse, PlanSection


def test_policy_payload_includes_clarifications_and_coverage(monkeypatch):
    monkeypatch.setattr(settings, "ark_base_url", "https://ark.example.com")
    monkeypatch.setattr(settings, "ark_api_key", "test-key")
    monkeypatch.setattr(settings, "ark_model_id", "ep-test")

    machine = StateMachine(session_id="1", topic="测试主题", outline_questions=["Q1", "Q2", "Q3"])
    machine.data.answered_questions.extend(["Q1", "Q2"])
    machine.data.pending_clarifications.append("缺少 KPI 数字")
    machine.data.stage = InterviewStage.CLARIFY
    machine.data.add_turn("assistant", "Q1")
    machine.data.add_turn("user", "A1")

    captured: dict = {}

    async def fake_chat_stream(messages, **kwargs):
        captured["messages"] = messages
        yield json.dumps(
            {
                "action": "clarify",
                "question": "请补充缺失的 KPI 数字",
                "rationale": "clarification required",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    decision = asyncio.run(decide_policy(machine.data))
    assert decision.action == "clarify"
    payload = json.loads(captured["messages"][1]["content"])
    assert payload["pending_clarifications"] == ["缺少 KPI 数字"]
    assert pytest.approx(payload["coverage"], rel=0.0) == 0.667
    assert payload["stage"] == InterviewStage.CLARIFY.value


def test_agent_fallback_uses_rule_based_clarification(monkeypatch):
    orchestrator = AgentOrchestrator()
    outline = PlanResponse(
        topic="测试主题",
        sections=[
            PlanSection(stage="背景", questions=[PlanQuestion(question="请介绍背景")]),
        ],
    )
    machine = asyncio.run(orchestrator.ensure_session("42", "测试主题", outline))
    machine.data.stage = InterviewStage.CLARIFY
    machine.register_clarification("缺少预算")

    async def raise_policy(*args, **kwargs):
        raise PolicyError("boom")

    monkeypatch.setattr("backend.app.services.agent.decide_policy", raise_policy)
    decision = asyncio.run(orchestrator.bootstrap_decision("42"))
    assert decision.action == "clarify"
    assert "缺少预算" in decision.question
