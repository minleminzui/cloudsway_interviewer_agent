from __future__ import annotations

from typing import Iterable

from ..schemas import PlanQuestion, PlanResponse, PlanSection


DEFAULT_STAGES = [
    ("背景", ["请介绍一下当前的业务背景", "团队目前的规模与分工情况如何？"]),
    ("细节", ["这个项目的核心指标有哪些？", "在实施过程中遇到了什么挑战？"]),
    ("结论", ["下一步的关键计划是什么？", "还需要哪些外部支持？"]),
]


class OutlineBuilder:
    """Generate structured three-level outlines."""

    def build(self, topic: str, seeds: Iterable[tuple[str, list[str]]] | None = None) -> PlanResponse:
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
