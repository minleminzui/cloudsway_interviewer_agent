from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from ..schemas import NoteSchema


FUZZY_MARKERS = {"可能", "大概", "不确定", "暂时"}
NUMBER_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>[%万亿万件人小时元人民币]*)")


@dataclass
class ExtractedNote:
    category: str
    content: str
    confidence: float = 0.9
    requires_clarification: bool = False


class InformationExtractor:
    """A lightweight rule-based extractor used for the MVP."""

    def extract(self, utterance: str) -> List[ExtractedNote]:
        notes: list[ExtractedNote] = []
        numbers = NUMBER_PATTERN.findall(utterance)
        for value, unit in numbers:
            notes.append(
                ExtractedNote(
                    category="数字",
                    content=f"{value}{unit}",
                    confidence=0.95,
                    requires_clarification=False,
                )
            )
        if any(marker in utterance for marker in FUZZY_MARKERS):
            notes.append(
                ExtractedNote(
                    category="澄清",
                    content="回答含糊，需要追问",
                    confidence=0.6,
                    requires_clarification=True,
                )
            )
        if not notes:
            notes.append(
                ExtractedNote(
                    category="观点",
                    content=utterance.strip(),
                    confidence=0.75,
                    requires_clarification=False,
                )
            )
        return notes


extractor = InformationExtractor()
