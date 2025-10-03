from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class NoteSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    content: str
    confidence: float
    requires_clarification: bool
    created_at: datetime


class TurnSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    speaker: str
    transcript: str
    stage: str
    llm_action: str
    llm_rationale: Optional[str] = None
    created_at: datetime


class SessionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic: str
    interviewer: Optional[str]
    interviewee: Optional[str]
    started_at: datetime
    status: str


class PlanQuestion(BaseModel):
    question: str
    emphasis: List[str] = Field(default_factory=list)


class PlanSection(BaseModel):
    stage: str
    questions: List[PlanQuestion]


class PlanResponse(BaseModel):
    topic: str
    sections: List[PlanSection]


class SessionCreate(BaseModel):
    topic: str
    interviewer: Optional[str] = None
    interviewee: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session: SessionSchema
    outline: PlanResponse


class TranscriptAppendRequest(BaseModel):
    speaker: str
    text: str


class ExportRequest(BaseModel):
    session_id: int
    format: str = Field(pattern="^(docx|xlsx)$")
