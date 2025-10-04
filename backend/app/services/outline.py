from __future__ import annotations

import json
import logging
from typing import Iterable, Any

from ..config import settings
from ..core import llm

from ..schemas import PlanQuestion, PlanResponse, PlanSection


LOGGER = logging.getLogger(__name__)


DEFAULT_STAGES = [
    ("背景", ["请介绍一下当前的业务背景", "团队目前的规模与分工情况如何？"]),
    ("细节", ["这个项目的核心指标有哪些？", "在实施过程中遇到了什么挑战？"]),
    ("结论", ["下一步的关键计划是什么？", "还需要哪些外部支持？"]),
]


class OutlineBuilder:
    """Generate structured three-level outlines."""

    async def build(
        self,
        topic: str,
        seeds: Iterable[tuple[str, list[str]]] | None = None,
    ) -> PlanResponse:
        blueprint: list[tuple[str, list[str]]] | None = None
        if settings.llm_credentials_ready:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是采访提纲助手，请基于主题生成三级递进的访谈提纲。"
                        "确保问题覆盖背景、细节、指标与行动项，回答 JSON 数组。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": topic,
                            "format": [
                                {"stage": "背景", "questions": []},
                                {"stage": "细节", "questions": []},
                                {"stage": "结论", "questions": []},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            buffer: list[str] = []
            try:
                async for chunk in llm.chat_stream(
                    messages,
                    model=settings.ark_outline_model_id or settings.ark_model_id,
                ):
                    buffer.append(chunk)
                raw = "".join(buffer).strip()
                if raw:
                    payload = _coerce_outline_payload(raw)
                    if payload:
                        blueprint = []
                        for section in payload:
                            stage = section.get("stage")
                            questions = section.get("questions") or []
                            if not stage or not isinstance(questions, list):
                                continue
                            normalized = [
                                str(question).strip()
                                for question in questions
                                if str(question).strip()
                            ]
                            if normalized:
                                blueprint.append((str(stage), normalized))
            except (llm.LLMNotConfiguredError, json.JSONDecodeError, TypeError, ValueError) as exc:
                LOGGER.warning("Ark outline generation failed, falling back to defaults: %s", exc)
                blueprint = None
        if blueprint is None:
            blueprint = list(seeds or DEFAULT_STAGES)
            
        sections = [
            PlanSection(
                stage=stage,
                questions=[PlanQuestion(question=q) for q in questions],
            )
            for stage, questions in blueprint
        ]
        return PlanResponse(topic=topic, sections=sections)


outline_builder = OutlineBuilder()

def _coerce_outline_payload(raw: str) -> list[dict[str, Any]] | None:
    """Attempt to extract a list of section payloads from ``raw`` text."""

    cleaned = raw.strip()
    if not cleaned:
        return None

    cleaned = _strip_code_fence(cleaned)

    def _normalize(value: Any) -> list[dict[str, Any]] | None:
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        if isinstance(value, dict):
            for key in ("outline", "data", "result"):
                candidate = value.get(key)
                if isinstance(candidate, list) and all(isinstance(item, dict) for item in candidate):
                    return candidate
        return None

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        normalized = _normalize(parsed)
        if normalized is not None:
            return normalized

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(cleaned):
        try:
            value, next_idx = decoder.raw_decode(cleaned, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        idx = max(next_idx, idx + 1)
        normalized = _normalize(value)
        if normalized is not None:
            return normalized
    return None


def _strip_code_fence(payload: str) -> str:
    if not payload.startswith("```"):
        return payload
    lines = payload.splitlines()
    if len(lines) < 2:
        return payload
    if lines[-1].strip().startswith("```"):
        content = lines[1:-1]
    else:
        content = lines[1:]
    return "\n".join(content).strip()