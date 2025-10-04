import asyncio
import logging

import pytest

from app.core.ws_tts_manager import WsTtsManager


from starlette.websockets import WebSocketDisconnect


class ControlledWebSocket:
    def __init__(self, *, send_exc: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self._release = asyncio.Event()
        self.accepted = False
        self._send_exc = send_exc
        self.close_called = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        if self._send_exc is not None:
            raise self._send_exc
        self.sent.append(payload)
        await self._release.wait()

    def allow_ready(self) -> None:
        self._release.set()

    async def close(self) -> None:
        self.close_called = True


@pytest.mark.asyncio
async def test_waiters_resume_after_ready_message_is_sent() -> None:
    manager = WsTtsManager()
    websocket = ControlledWebSocket()

    waiter_triggered = asyncio.Event()

    async def waiter() -> None:
        await manager.wait_until_ready("session-1")
        waiter_triggered.set()

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert not waiter_triggered.is_set()

    register_task = asyncio.create_task(manager.register("session-1", websocket))
    await asyncio.sleep(0)
    assert websocket.sent == [{"type": "tts_ready", "mime": "audio/mpeg"}]
    assert not waiter_triggered.is_set()

    websocket.allow_ready()
    await register_task
    await waiter_task

    assert waiter_triggered.is_set()
    assert websocket.accepted


@pytest.mark.asyncio
async def test_waiter_blocks_until_successful_register_after_failure() -> None:
    manager = WsTtsManager()
    sid = "session-failure"

    waiter_triggered = asyncio.Event()

    async def waiter() -> None:
        await manager.wait_until_ready(sid)
        waiter_triggered.set()

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert not waiter_triggered.is_set()

    failing_websocket = ControlledWebSocket(send_exc=RuntimeError("controlled failure"))

    with pytest.raises(RuntimeError):
        await manager.register(sid, failing_websocket)

    await manager.unregister(sid, failing_websocket)

    assert not waiter_triggered.is_set()
    assert not waiter_task.done()
    assert failing_websocket.accepted
    assert failing_websocket.close_called

    websocket = ControlledWebSocket()
    register_task = asyncio.create_task(manager.register(sid, websocket))
    await asyncio.sleep(0)

    assert websocket.sent == [{"type": "tts_ready", "mime": "audio/mpeg"}]
    assert not waiter_triggered.is_set()

    websocket.allow_ready()
    await register_task
    await asyncio.wait_for(waiter_task, timeout=1)

    assert waiter_triggered.is_set()
    assert websocket.accepted


@pytest.mark.asyncio
async def test_register_and_unregister_log_peer_counts(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.core.ws_tts_manager")
    manager = WsTtsManager()
    websocket = ControlledWebSocket()

    register_task = asyncio.create_task(manager.register("session-logs", websocket))
    await asyncio.sleep(0)
    websocket.allow_ready()
    await register_task

    assert any(
        record.levelno == logging.INFO
        and "Registered TTS peer sid=session-logs peers=1 readiness_reset=True" in record.getMessage()
        for record in caplog.records
    )

    caplog.clear()
    await manager.unregister("session-logs", websocket)

    assert any(
        record.levelno == logging.INFO
        and "Unregistered TTS peer sid=session-logs peers=0 readiness_reset=True" in record.getMessage()
        for record in caplog.records
    )


class BrokenWebSocket:
    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        return None

    async def send_bytes(self, payload: bytes) -> None:  # pragma: no cover - behaviour verified via exception
        raise RuntimeError("boom")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_broadcast_logs_peer_drop(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="app.core.ws_tts_manager")
    manager = WsTtsManager()
    ws = BrokenWebSocket()
    sid = "session-drop"

    await manager.register(sid, ws)
    await manager._broadcast_bytes(sid, b"data")

    assert any(
        record.levelno == logging.ERROR
        and "Dropping TTS peer sid=session-drop due to bytes send error" in record.getMessage()
        for record in caplog.records
    )


class DummyQueryParams(dict):
    def get(self, key, default=None):  # type: ignore[override]
        return super().get(key, default)


class DummyWebSocket:
    def __init__(self) -> None:
        self.query_params = DummyQueryParams({"session": "dummy"})
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class DummyManager:
    def __init__(self) -> None:
        self.register_calls: list[tuple[str, object]] = []
        self.unregister_calls: list[tuple[str, object]] = []

    async def register(self, sid: str, websocket: object) -> None:
        self.register_calls.append((sid, websocket))
        raise WebSocketDisconnect()

    async def unregister(self, sid: str, websocket: object) -> None:
        self.unregister_calls.append((sid, websocket))


@pytest.mark.asyncio
async def test_websocket_tts_unregisters_on_registration_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import ws_tts

    dummy_manager = DummyManager()
    monkeypatch.setattr(ws_tts, "manager", dummy_manager)

    websocket = DummyWebSocket()

    await ws_tts.websocket_tts(websocket)  # Should swallow the disconnect and return.

    assert dummy_manager.register_calls == [("dummy", websocket)]
    assert dummy_manager.unregister_calls == [("dummy", websocket)]
    assert websocket.closed


@pytest.mark.asyncio
async def test_waiter_blocks_until_success_after_disconnect() -> None:
    manager = WsTtsManager()
    sid = "session-disconnect"

    waiter_triggered = asyncio.Event()

    async def waiter() -> None:
        await manager.wait_until_ready(sid)
        waiter_triggered.set()

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert not waiter_triggered.is_set()

    disconnecting_ws = ControlledWebSocket(send_exc=WebSocketDisconnect())

    with pytest.raises(WebSocketDisconnect):
        await manager.register(sid, disconnecting_ws)

    await manager.unregister(sid, disconnecting_ws)

    assert disconnecting_ws.close_called
    assert not waiter_triggered.is_set()
    assert not waiter_task.done()

    websocket = ControlledWebSocket()
    register_task = asyncio.create_task(manager.register(sid, websocket))
    await asyncio.sleep(0)

    websocket.allow_ready()
    await register_task
    await asyncio.wait_for(waiter_task, timeout=1)

    assert waiter_triggered.is_set()
    assert websocket.accepted
