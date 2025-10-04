from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict

from ..models import Note, Session, Turn
from ..schemas import PlanResponse
from ..database import SessionLocal
from .extraction import extractor
from .outline import outline_builder
from .policy import PolicyDecision, PolicyError, decide_policy
from .state_machine import InterviewStage, StateMachine


@dataclass
class AgentDecision:
    action: str
    question: str
    stage: InterviewStage
    rationale: str
    notes: list[dict] = field(default_factory=list)
    new_notes: list[dict] = field(default_factory=list)



class AgentOrchestrator:
    """Coordinates interview turns and persistence."""

    def __init__(self) -> None:
        self._machines: Dict[str, StateMachine] = {}
        self._note_cache: Dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()

    async def ensure_session(self, session_id: str, topic: str, outline: PlanResponse | None = None) -> StateMachine:
        async with self._lock:
            if session_id in self._machines:
                return self._machines[session_id]
            outline_obj = outline or await outline_builder.build(topic)
            questions = [q.question for section in outline_obj.sections for q in section.questions]
            machine = StateMachine(session_id=session_id, topic=topic, outline_questions=questions)
            self._machines[session_id] = machine
            self._note_cache[session_id] = []
            return machine

    async def bootstrap_decision(self, session_id: str) -> AgentDecision:
        machine = self._machines[session_id]
        policy_decision = await self._decide_with_fallback(machine)
        self._sync_stage_with_action(machine, policy_decision.action)
        machine.apply_policy_decision(policy_decision)
        return AgentDecision(
            action=policy_decision.action,
            question=policy_decision.question,
            stage=machine.data.stage,
            rationale=policy_decision.rationale,
        )

    async def handle_user_turn(self, session_id: str, text: str, speaker: str = "user") -> AgentDecision:
        machine = self._machines[session_id]
        previous_stage = machine.data.stage
        if previous_stage == InterviewStage.CLARIFY and machine.data.pending_clarifications:
            machine.data.resolve_clarification(machine.data.pending_clarifications[0])
        machine.transition_after_answer()

        extracted_notes = extractor.extract(text)
        for note in extracted_notes:
            if note.requires_clarification:
                machine.register_clarification(note.content)
        policy_decision = await self._decide_with_fallback(machine)
        self._sync_stage_with_action(machine, policy_decision.action)
        machine.apply_policy_decision(policy_decision)
        note_payloads = [
            {
                "category": note.category,
                "content": note.content,
                "confidence": note.confidence,
                "requires_clarification": note.requires_clarification,
            }
            for note in extracted_notes
        ]
        aggregate = self._note_cache.setdefault(session_id, [])
        by_content = {item["content"]: item for item in aggregate}
        for payload in note_payloads:
            existing = by_content.get(payload["content"])
            if existing:
                existing["confidence"] = max(existing["confidence"], payload["confidence"])
                existing["requires_clarification"] = existing["requires_clarification"] or payload["requires_clarification"]
            else:
                aggregate.append(payload.copy())
                by_content[payload["content"]] = aggregate[-1]
        decision = AgentDecision(
            action=policy_decision.action,
            question=policy_decision.question,
            stage=machine.data.stage,
            notes=[{**item} for item in aggregate],
            new_notes=note_payloads,
            rationale=policy_decision.rationale,
        )
        await self._persist_turn(session_id=session_id, speaker=speaker, text=text, decision=decision)
        return decision

    async def _decide_with_fallback(self, machine: StateMachine) -> PolicyDecision:
        try:
            return await decide_policy(machine.data)
        except PolicyError:
            return machine.rule_based_decision()

    def _sync_stage_with_action(self, machine: StateMachine, action: str) -> None:
        if action == "clarify":
            machine.data.stage = InterviewStage.CLARIFY
        elif action == "close":
            machine.data.stage = InterviewStage.CLOSING
            
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
                llm_rationale=decision.rationale,
            )
            db.add(turn)
            for payload in decision.new_notes:
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
