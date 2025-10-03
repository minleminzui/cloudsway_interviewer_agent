from __future__ import annotations

import asyncio

from ..core.ws_tts_manager import manager as ws_manager

_CLUSTER_ID = b"\x1fC\xb6u"


def _split_webm_clusters(buf: bytes) -> list[bytes]:
    positions: list[int] = []
    start = 0
    while True:
        idx = buf.find(_CLUSTER_ID, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    if not positions:
        return [buf]
    chunks: list[bytes] = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(buf)
        chunks.append(buf[pos:end])
    return chunks


def _read_demo_asset(path: str) -> tuple[bytes, list[bytes]]:
    with open(path, "rb") as handle:
        data = handle.read()
    head_end = data.find(_CLUSTER_ID)
    header = data[:head_end] if head_end > 0 else b""
    clusters = _split_webm_clusters(data)
    return header, clusters


async def stream_demo_webm(session: str, path: str, pace_ms: int = 40) -> None:
    header, clusters = _read_demo_asset(path)
    current_task = asyncio.current_task()
    if current_task is None:
        raise RuntimeError("stream_demo_webm must run within a task context")
    token = ws_manager.start_stream(session, current_task)
    try:
        await ws_manager.wait_until_ready(session)
        if header:
            await ws_manager.send_audio_chunk(session, header)
        for chunk in clusters:
            if token.is_cancelled() or ws_manager.is_cancelled(session):
                break
            await ws_manager.send_audio_chunk(session, chunk)
            await asyncio.sleep(pace_ms / 1000)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await ws_manager.send_tts_end(session)
        finally:
            ws_manager.finish_stream(session, current_task)
