import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PATH = ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.config import settings
from app.core import llm
from app.services.outline import OutlineBuilder, DEFAULT_STAGES


def test_outline_builder_uses_llm_when_configured(monkeypatch):
    builder = OutlineBuilder()
    monkeypatch.setattr(settings, "ark_base_url", "https://ark.example.com")
    monkeypatch.setattr(settings, "ark_api_key", "test-key")
    monkeypatch.setattr(settings, "ark_model_id", "ep-test")

    async def fake_chat_stream(messages, **kwargs):
        payload = [
            {"stage": "背景", "questions": ["Q1", "Q2"]},
            {"stage": "细节", "questions": ["Q3"]},
        ]
        yield json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    outline = asyncio.run(builder.build("测试主题"))
    assert [section.stage for section in outline.sections] == ["背景", "细节"]
    assert outline.sections[0].questions[0].question == "Q1"


def test_outline_builder_falls_back_on_error(monkeypatch):
    builder = OutlineBuilder()
    monkeypatch.setattr(settings, "ark_base_url", "https://ark.example.com")
    monkeypatch.setattr(settings, "ark_api_key", "test-key")
    monkeypatch.setattr(settings, "ark_model_id", "ep-test")

    async def broken_chat_stream(messages, **kwargs):
        yield "{"  # malformed json

    monkeypatch.setattr(llm, "chat_stream", broken_chat_stream)
    outline = asyncio.run(builder.build("测试主题"))
    assert [(stage, len(questions)) for stage, questions in DEFAULT_STAGES] == [
        (section.stage, len(section.questions)) for section in outline.sections
    ]

def test_outline_builder_parses_code_fence_payload(monkeypatch):
    builder = OutlineBuilder()
    monkeypatch.setattr(settings, "ark_base_url", "https://ark.example.com")
    monkeypatch.setattr(settings, "ark_api_key", "test-key")
    monkeypatch.setattr(settings, "ark_model_id", "ep-test")

    async def fake_chat_stream(messages, **kwargs):
        payload = """```json
        [
            {"stage": "背景", "questions": ["Q1"]},
            {"stage": "细节", "questions": ["Q2"]}
        ]
        ```"""
        yield payload

    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    outline = asyncio.run(builder.build("测试主题"))

    assert [section.stage for section in outline.sections] == ["背景", "细节"]


def test_outline_builder_supports_nested_outline_key(monkeypatch):
    builder = OutlineBuilder()
    monkeypatch.setattr(settings, "ark_base_url", "https://ark.example.com")
    monkeypatch.setattr(settings, "ark_api_key", "test-key")
    monkeypatch.setattr(settings, "ark_model_id", "ep-test")

    async def fake_chat_stream(messages, **kwargs):
        yield json.dumps(
            {
                "outline": [
                    {"stage": "背景", "questions": ["Q1"]},
                    {"stage": "结论", "questions": ["Q3"]},
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    outline = asyncio.run(builder.build("测试主题"))

    assert [section.stage for section in outline.sections] == ["背景", "结论"]
