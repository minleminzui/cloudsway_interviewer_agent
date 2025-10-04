from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:  # pragma: no cover
    from .policy import PolicyDecision

class InterviewStage(str, Enum):
    OPENING = "Opening"
    EXPLORATION = "Exploration"
    DEEP_DIVE = "DeepDive"
    CLARIFY = "Clarify"
    CLOSING = "Closing"


@dataclass
class ConversationState:
    session_id: str
    topic: str
    outline_questions: List[str]
    answered_questions: List[str] = field(default_factory=list)
    stage: InterviewStage = InterviewStage.OPENING
    pending_clarifications: List[str] = field(default_factory=list)
    last_question: str | None = None
    turn_history: List[dict] = field(default_factory=list)

    def coverage(self) -> float:
        if not self.outline_questions:
            return 1.0
        return len(self.answered_questions) / len(self.outline_questions)

    def mark_answered(self, question: str) -> None:
        if question not in self.answered_questions:
            self.answered_questions.append(question)

    def mark_last_answered(self) -> None:
        if self.last_question:
            self.mark_answered(self.last_question)
            self.last_question = None

    def add_clarification(self, content: str) -> None:
        if content not in self.pending_clarifications:
            self.pending_clarifications.append(content)

    def resolve_clarification(self, content: str) -> None:
        if content in self.pending_clarifications:
            self.pending_clarifications.remove(content)
    
    def add_turn(self, role: str, content: str) -> None:
        text = content.strip()
        if not text:
            return
        payload = {"role": role, "content": text}
        self.turn_history.append(payload)
        if len(self.turn_history) > 10:
            del self.turn_history[0 : len(self.turn_history) - 10]

    def recent_turns(self, limit: int = 8) -> List[dict]:
        if limit <= 0:
            return []
        return self.turn_history[-limit:]


class StateMachine:
    def __init__(self, session_id: str, topic: str, outline_questions: List[str]):
        self.data = ConversationState(session_id=session_id, topic=topic, outline_questions=outline_questions)

    def transition_after_answer(self) -> None:
        self.data.mark_last_answered()
        coverage = self.data.coverage()
        if coverage > 0.75 and not self.data.pending_clarifications:
            self.data.stage = InterviewStage.CLOSING
        elif self.data.pending_clarifications:
            self.data.stage = InterviewStage.CLARIFY
        elif coverage > 0.4:
            self.data.stage = InterviewStage.DEEP_DIVE
        else:
            self.data.stage = InterviewStage.EXPLORATION

    def record_user_turn(self, text: str) -> None:
        self.data.add_turn("user", text)

    def apply_policy_decision(self, decision: "PolicyDecision") -> None:
        self.data.last_question = decision.question
        self.data.add_turn(
            "assistant",
            decision.question,
        )

    def rule_based_decision(self) -> "PolicyDecision":
        from .policy import PolicyDecision
        unanswered = [q for q in self.data.outline_questions if q not in self.data.answered_questions]
        rationale = "rule-based fallback"
        if self.data.pending_clarifications:
            target = self.data.pending_clarifications[0]
            question = f"关于『{target}』能再具体说明一下吗？"
            return PolicyDecision(action="clarify", question=question, rationale=rationale)
        if self.data.stage == InterviewStage.CLOSING:
            question = "感谢分享，我们来做个小结：还有哪些重点没有提到？"
            return PolicyDecision(action="close", question=question, rationale=rationale)
        if unanswered:
            question = unanswered[0]
            return PolicyDecision(action="ask", question=question, rationale=rationale)
        question = "能否补充一个具体数据或案例，帮助我们理解？"
        return PolicyDecision(action="ask", question=question, rationale=rationale)

    def register_clarification(self, content: str) -> None:
        self.data.add_clarification(content)


__all__ = ["InterviewStage", "ConversationState", "StateMachine"]
