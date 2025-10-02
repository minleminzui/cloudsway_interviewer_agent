from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict

from ..models import Note, Session, Turn
from ..schemas import PlanResponse
from ..database import SessionLocal
from .extraction import extractor
from .outline import outline_builder
from .state_machine import InterviewStage, StateMachine


@dataclass
class AgentDecision:
    action: str
    question: str
    stage: InterviewStage
    notes: list[dict]


class AgentOrchestrator:
    """Coordinates interview turns and persistence."""

    def __init__(self) -> None:
        self._machines: Dict[str, StateMachine] = {}
        self._lock = asyncio.Lock()

    async def ensure_session(self, session_id: str, topic: str, outline: PlanResponse | None = None) -> StateMachine:
        async with self._lock:
            if session_id in self._machines:
                return self._machines[session_id]
            outline_obj = outline or outline_builder.build(topic)
            questions = [q.question for section in outline_obj.sections for q in section.questions]
            machine = StateMachine(session_id=session_id, topic=topic, outline_questions=questions)
            self._machines[session_id] = machine
            return machine

    async def handle_user_turn(self, session_id: str, text: str, speaker: str = "user") -> AgentDecision:
        machine = self._machines[session_id]
        previous_stage = machine.data.stage
        if previous_stage == InterviewStage.CLARIFY and machine.data.pending_clarifications:
            machine.data.resolve_clarification(machine.data.pending_clarifications[0])
        machine.transition_after_answer()
        question = machine.next_question()
        notes = extractor.extract(text)
        for note in notes:
            if note.requires_clarification:
                machine.register_clarification(note.content)
        decision = AgentDecision(
            action="ask",
            question=question,
            stage=machine.data.stage,
            notes=[note.__dict__ for note in notes],
        )
        await self._persist_turn(session_id=session_id, speaker=speaker, text=text, decision=decision)
        return decision

    async def _persist_turn(self, session_id: str, speaker: str, text: str, decision: AgentDecision) -> None:
        async with SessionLocal() as db:  # open independent session outside FastAPI DI
            session_obj = await db.get(Session, int(session_id))
            if not session_obj:
                return
            turn = Turn(
                session_id=session_obj.id,
                speaker=speaker,
                transcript=text,
                stage=decision.stage.value,
                llm_action=decision.action,
            )
            db.add(turn)
            for payload in decision.notes:
                note = Note(
                    session_id=session_obj.id,
                    category=payload["category"],
                    content=payload["content"],
                    confidence=payload["confidence"],
                    requires_clarification=payload["requires_clarification"],
                )
                db.add(note)
            await db.commit()


agent_orchestrator = AgentOrchestrator()
