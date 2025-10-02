from __future__ import annotations

from typing import Dict

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id] = websocket

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)

    async def send_json(self, session_id: str, data: dict) -> None:
        websocket = self._connections.get(session_id)
        if websocket:
            await websocket.send_json(data)

    async def send_bytes(self, session_id: str, data: bytes) -> None:
        websocket = self._connections.get(session_id)
        if websocket:
            await websocket.send_bytes(data)
