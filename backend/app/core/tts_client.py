from __future__ import annotations

import asyncio
import base64
import os
from typing import Optional

import aiohttp

from .ws_tts_manager import manager as ws_manager

VOLC_TTS_URL = os.environ.get("VOLC_TTS_BASE_URL")
VOLC_TTS_KEY = os.environ.get("VOLC_TTS_API_KEY")
VOLC_TTS_RES = os.environ.get("VOLC_TTS_RESOURCE_ID")
VOLC_TTS_SPK = os.environ.get("VOLC_TTS_SPEAKER", "zh_male_beijingxiaoye_emo_v2_mars_bigtts")
VOLC_TTS_SR = int(os.environ.get("VOLC_TTS_SAMPLE_RATE", 24000))
VOLC_TTS_FMT = os.environ.get("VOLC_TTS_FORMAT", "mp3")


async def synth_once(text: str) -> bytes:
    if not VOLC_TTS_URL or not VOLC_TTS_KEY or not VOLC_TTS_RES:
        raise RuntimeError("VOLC TTS configuration is incomplete. Check environment variables.")
    payload = {
        "req_params": {
            "text": text,
            "speaker": VOLC_TTS_SPK,
            "additions": "{\"disable_markdown_filter\":true,\"enable_language_detector\":true,\"enable_latex_tn\":true,\"disable_default_bit_rate\":true,\"max_length_to_filter_parenthesis\":0,\"cache_config\":{\"text_type\":1,\"use_cache\":true}}",
            "audio_params": {"format": VOLC_TTS_FMT, "sample_rate": VOLC_TTS_SR},
        }
    }
    headers = {
        "x-api-key": VOLC_TTS_KEY,
        "X-Api-Resource-Id": VOLC_TTS_RES,
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(VOLC_TTS_URL, json=payload, headers=headers) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if content_type.startswith("audio/"):
                return await resp.read()
            data = await resp.json()
            audio_b64: Optional[str] = (
                data.get("data", {}).get("audio")
                or data.get("result", {}).get("audio")
            )
            if not audio_b64:
                raise RuntimeError(f"TTS bad response: {data}")
            return base64.b64decode(audio_b64)


async def stream_and_broadcast(session_id: str, text: str) -> None:
    current_task = asyncio.current_task()
    if current_task is None:
        raise RuntimeError("stream_and_broadcast must be awaited within a task context")
    token = ws_manager.start_stream(session_id, current_task)
    try:
        await ws_manager.wait_until_ready(session_id)
        audio = await synth_once(text)
        chunk_size = 32 * 1024
        for start in range(0, len(audio), chunk_size):
            if token.is_cancelled() or ws_manager.is_cancelled(session_id):
                break
            chunk = audio[start:start + chunk_size]
            await ws_manager.send_audio_chunk(session_id, chunk)
    except asyncio.CancelledError:
        # Cancellation is expected when barge-in happens; swallow to avoid noisy logs.
        pass
    finally:
        try:
            await ws_manager.send_tts_end(session_id)
        finally:
            ws_manager.finish_stream(session_id, current_task)
