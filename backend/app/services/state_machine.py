from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


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

    def next_question(self) -> str:
        unanswered = [q for q in self.data.outline_questions if q not in self.data.answered_questions]
        if self.data.stage == InterviewStage.CLARIFY and self.data.pending_clarifications:
            question = f"关于『{self.data.pending_clarifications[0]}』能再具体说明一下吗？"
            self.data.last_question = question
            return question
        if self.data.stage == InterviewStage.CLOSING:
            question = "感谢分享，我们来做个小结：还有哪些重点没有提到？"
            self.data.last_question = question
            return question
        if unanswered:
            question = unanswered[0]
            self.data.last_question = question
            return question
        question = "能否补充一个具体数据或案例，帮助我们理解？"
        self.data.last_question = question
        return question

    def register_clarification(self, content: str) -> None:
        self.data.add_clarification(content)


__all__ = ["InterviewStage", "ConversationState", "StateMachine"]
