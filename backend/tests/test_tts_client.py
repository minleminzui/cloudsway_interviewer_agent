from __future__ import annotations

import base64
from typing import Iterable, List

import pytest
import asyncio
from types import SimpleNamespace
from app.core import tts_client
from app.core.ws_tts_manager import WsTtsManager

class DummyResponse:
    def __init__(self, *, content_type: str, body: bytes, status: int = 200) -> None:
        self.headers = {"Content-Type": content_type}
        self._body = body
        self.status = status

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> "DummyResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class DummySession:
    def __init__(self, responses: Iterable[DummyResponse]) -> None:
        self._responses: List[DummyResponse] = list(responses)

    async def __aenter__(self) -> "DummySession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, *args, **kwargs) -> DummyResponse:
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _patch_tts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://example.test/tts")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "dummy")
    monkeypatch.setenv("VOLC_TTS_RESOURCE_ID", "resource")
    monkeypatch.setenv(
        "VOLC_TTS_SPEAKER", "zh_male_beijingxiaoye_emo_v2_mars_bigtts"
    )
    monkeypatch.setenv("VOLC_TTS_SAMPLE_RATE", "24000")
    monkeypatch.setenv("VOLC_TTS_FORMAT", "mp3")
    tts_client.refresh_volc_config()


@pytest.mark.asyncio
async def test_synth_once_returns_audio_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = DummyResponse(content_type="audio/mpeg", body=b"binary-audio")
    monkeypatch.setattr(tts_client.aiohttp, "ClientSession", lambda **_: DummySession([payload]))

    audio = await tts_client.synth_once("hello")

    assert audio == b"binary-audio"


@pytest.mark.asyncio
async def test_synth_once_accepts_text_plain_json(monkeypatch: pytest.MonkeyPatch) -> None:
    audio_bytes = base64.b64encode(b"audio-bytes").decode()
    payload = DummyResponse(
        content_type="text/plain; charset=utf-8",
        body=f"{{\"data\": {{\"audio\": \"{audio_bytes}\"}}}}".encode(),
        status=400,
    )
    monkeypatch.setattr(tts_client.aiohttp, "ClientSession", lambda **_: DummySession([payload]))

    audio = await tts_client.synth_once("hello")

    assert audio == b"audio-bytes"


@pytest.mark.asyncio
async def test_synth_once_raises_on_non_json_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = DummyResponse(
        content_type="text/plain", body=b"plain error", status=403
    )
    monkeypatch.setattr(tts_client.aiohttp, "ClientSession", lambda **_: DummySession([payload]))

    with pytest.raises(RuntimeError) as excinfo:
        await tts_client.synth_once("hello")

    assert "plain error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_stream_and_broadcast_falls_back_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_RESOURCE_ID", raising=False)
    tts_client.refresh_volc_config()

    recorded: dict[str, object] = {
        "error": "",
        "fallback": "",
        "fallback_message": None,
        "end": False,
        "finished": False,
    }

    class DummyManager:
        def start_stream(self, sid: str, task: asyncio.Task) -> SimpleNamespace:
            return SimpleNamespace(is_cancelled=lambda: False)

        async def wait_until_ready(self, sid: str) -> None:
            return None

        def is_cancelled(self, sid: str) -> bool:
            return False

        async def send_tts_error(self, sid: str, message: str) -> None:
            recorded["error"] = message

        async def send_tts_fallback(self, sid: str, text: str, message: str | None = None) -> None:
            recorded["fallback"] = text
            recorded["fallback_message"] = message

        async def send_tts_end(self, sid: str) -> None:
            recorded["end"] = True

        async def send_audio_chunk(self, sid: str, chunk: bytes) -> None:  # pragma: no cover - unused
            raise AssertionError("audio should not be streamed when config is missing")

        def finish_stream(self, sid: str, task: asyncio.Task) -> None:
            recorded["finished"] = True

    dummy_manager = DummyManager()
    monkeypatch.setattr(tts_client, "ws_manager", dummy_manager)
    synth_called = False

    async def fail_synth(text: str) -> bytes:  # pragma: no cover - should not be called
        nonlocal synth_called
        synth_called = True
        return b""

    monkeypatch.setattr(tts_client, "synth_once", fail_synth)

    await tts_client.stream_and_broadcast("s1", "测试语句")

    assert recorded["error"]
    assert recorded["fallback"] == "测试语句"
    assert recorded["fallback_message"] == "语音合成功能未配置，已使用浏览器朗读。"
    assert recorded["end"] is True
    assert recorded["finished"] is True
    assert synth_called is False



@pytest.mark.asyncio
async def test_stream_and_broadcast_times_out_waiting_for_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_client, "WS_READY_TIMEOUT", 0.01)

    recorded: dict[str, object] = {
        "error": "",
        "fallback": "",
        "fallback_message": None,
        "end": False,
        "finished": False,
        "ready_calls": 0,
    }

    class DummyManager:
        def start_stream(self, sid: str, task: asyncio.Task) -> SimpleNamespace:
            return SimpleNamespace(is_cancelled=lambda: False)

        async def wait_until_ready(self, sid: str) -> None:
            recorded["ready_calls"] = recorded.get("ready_calls", 0) + 1
            await asyncio.Event().wait()

        def is_cancelled(self, sid: str) -> bool:
            return False

        async def diagnostic_state(self, sid: str) -> dict:
            return {
                "peers": 0,
                "ready_event": False,
                "ready_event_is_set": False,
                "has_active_task": False,
                "cancelled": False,
            }

        async def send_tts_error(self, sid: str, message: str) -> None:
            recorded["error"] = message

        async def send_tts_fallback(self, sid: str, text: str, message: str | None = None) -> None:
            recorded["fallback"] = text
            recorded["fallback_message"] = message

        async def send_tts_end(self, sid: str) -> None:
            recorded["end"] = True

        async def send_audio_chunk(self, sid: str, chunk: bytes) -> None:  # pragma: no cover - unused
            raise AssertionError("audio should not be streamed when websocket never becomes ready")

        def finish_stream(self, sid: str, task: asyncio.Task) -> None:
            recorded["finished"] = True

    dummy_manager = DummyManager()
    monkeypatch.setattr(tts_client, "ws_manager", dummy_manager)

    synth_called = False

    async def fail_synth(text: str) -> bytes:  # pragma: no cover - should not be called
        nonlocal synth_called
        synth_called = True
        return b""

    monkeypatch.setattr(tts_client, "synth_once", fail_synth)

    await tts_client.stream_and_broadcast("s-timeout", "超时测试")

    assert recorded["ready_calls"] == 1
    assert recorded["error"] == "语音合成连接超时，已使用浏览器朗读。"
    assert recorded["fallback"] == "超时测试"
    assert recorded["fallback_message"] == "语音合成连接超时，已使用浏览器朗读。"
    assert recorded["end"] is True
    assert recorded["finished"] is True
    assert synth_called is False


class DummyWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent_json: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent_json.append(payload)


@pytest.mark.asyncio
async def test_manager_normalizes_control_payloads() -> None:
    manager = WsTtsManager()

    await manager._broadcast_json(  # type: ignore[attr-defined]
        "sid-norm",
        {
            "type": "tts_error",
            "message": "boom",
            "text": "should-drop",
        },
    )
    await manager._broadcast_json(  # type: ignore[attr-defined]
        "sid-norm",
        {
            "type": "tts_fallback",
            "text": "cached text",
            "message": "extra",
        },
    )
    await manager._broadcast_json(  # type: ignore[attr-defined]
        "sid-norm",
        {"type": "tts_end", "text": "extra"},
    )

    ws = DummyWebSocket()
    await manager.register("sid-norm", ws)

    assert ws.sent_json[0] == {"type": "tts_ready", "mime": "audio/mpeg"}
    assert ws.sent_json[1] == {"type": "tts_error", "message": "boom"}
    assert ws.sent_json[2] == {"type": "tts_fallback", "text": "cached text"}
    assert ws.sent_json[3] == {"type": "tts_end"}


@pytest.mark.asyncio
async def test_timeout_then_late_websocket_receives_cached_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WsTtsManager()
    monkeypatch.setattr(tts_client, "ws_manager", manager)
    monkeypatch.setattr(tts_client, "WS_READY_TIMEOUT", 0.01)

    synth_called = False

    async def synth_stub(_: str) -> bytes:  # pragma: no cover - not expected to run
        nonlocal synth_called
        synth_called = True
        return b""

    monkeypatch.setattr(tts_client, "synth_once", synth_stub)

    text = "晚到的客户端"
    await tts_client.stream_and_broadcast("sid-late", text)

    ws = DummyWebSocket()
    await manager.register("sid-late", ws)

    assert ws.accepted is True
    assert ws.sent_json[0] == {"type": "tts_ready", "mime": "audio/mpeg"}
    assert ws.sent_json[1] == {
        "type": "tts_error",
        "message": "语音合成连接超时，已使用浏览器朗读。",
    }
    assert ws.sent_json[2] == {"type": "tts_fallback", "text": text}
    assert ws.sent_json[3] == {"type": "tts_end"}
    assert "sid-late" not in manager._pending_json
    assert synth_called is False
