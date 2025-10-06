# app/core/tts_client.py
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Optional

import aiohttp

from .ws_tts_manager import manager as ws_manager

LOGGER = logging.getLogger(__name__)

# ==============================
# 🔹 默认火山配置
# ==============================
_DEFAULT_VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_DEFAULT_VOLC_TTS_RES = "volc.service_type.10029"
_DEFAULT_VOLC_TTS_SPK = "zh_male_beijingxiaoye_emo_v2_mars_bigtts"
_DEFAULT_VOLC_TTS_SR = 24000
_DEFAULT_VOLC_TTS_FMT = "ogg"

VOLC_TTS_URL = os.getenv("VOLC_TTS_BASE_URL", _DEFAULT_VOLC_TTS_URL)
VOLC_TTS_KEY = os.getenv("VOLC_TTS_API_KEY")
VOLC_TTS_RES = os.getenv("VOLC_TTS_RESOURCE_ID", _DEFAULT_VOLC_TTS_RES)
VOLC_TTS_SPK = os.getenv("VOLC_TTS_SPEAKER", _DEFAULT_VOLC_TTS_SPK)
VOLC_TTS_SR = int(os.getenv("VOLC_TTS_SAMPLE_RATE", _DEFAULT_VOLC_TTS_SR))
VOLC_TTS_FMT = os.getenv("VOLC_TTS_FORMAT", _DEFAULT_VOLC_TTS_FMT)

WS_READY_TIMEOUT = float(os.getenv("TTS_WS_READY_TIMEOUT", 15.0))


# ==============================
# 🔹 调用火山 TTS 接口
# ==============================
async def synth_once(text: str) -> bytes:
    """调用火山 TTS 一次并返回完整音频字节流"""
    if not VOLC_TTS_KEY:
        raise RuntimeError("VOLC_TTS_API_KEY 未配置")

    payload = {
        "req_params": {
            "text": text,
            "speaker": VOLC_TTS_SPK,
            "additions": "{\"disable_markdown_filter\":true,\"enable_language_detector\":true}",
            "audio_params": {"format": VOLC_TTS_FMT, "sample_rate": VOLC_TTS_SR},
        }
    }
    headers = {
        "x-api-key": VOLC_TTS_KEY,
        "X-Api-Resource-Id": VOLC_TTS_RES,
        "Content-Type": "application/json",
    }

    chunks: list[bytes] = []
    async with aiohttp.ClientSession() as session:
        async with session.post(VOLC_TTS_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"TTS HTTP {resp.status}: {body[:300]}")

            # 有些版本返回多行 JSON
            raw = await resp.text()
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                data_field = _extract_audio_field(obj)
                if data_field:
                    try:
                        chunks.append(base64.b64decode(data_field))
                    except Exception as e:
                        LOGGER.warning(f"[tts] Base64 decode failed: {e}")
            if not chunks:
                raise RuntimeError("TTS 返回内容为空")

    audio = b"".join(chunks)
    LOGGER.info(f"[tts] 🔊 got {len(audio)} bytes from {len(chunks)} segments")
    return audio


def _extract_audio_field(obj: dict) -> Optional[str]:
    for key in ("audio", "data", "result"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):
            inner = v.get("audio")
            if isinstance(inner, str) and inner.strip():
                return inner
    return None


# ==============================
# 🔹 主逻辑：TTS 生成并广播
# ==============================
async def stream_and_broadcast(session_id: str, text: str) -> None:
    """合成并推流音频到 WebSocket 客户端"""
    task = asyncio.current_task()
    token = ws_manager.start_stream(session_id, task)
    LOGGER.info(f"[tts] 🚀 start TTS stream sid={session_id}, len={len(text)}")

    try:
        # 等待前端 ready
        try:
            await asyncio.wait_for(ws_manager.wait_until_ready(session_id), timeout=WS_READY_TIMEOUT)
            LOGGER.info(f"[tts] ✅ websocket ready sid={session_id}")
        except asyncio.TimeoutError:
            LOGGER.warning(f"[tts] ⚠️ websocket not ready after {WS_READY_TIMEOUT}s, continue sid={session_id}")

        # 生成音频
        audio = await synth_once(text)
        if not audio:
            raise RuntimeError("empty audio output")

        # 发送“准备就绪”信号
        await ws_manager.send_tts_ready(session_id, mime=f"audio/{VOLC_TTS_FMT}")

        # 分块发送音频
        CHUNK = 32 * 1024
        for i in range(0, len(audio), CHUNK):
            if token.is_cancelled() or ws_manager.is_cancelled(session_id):
                LOGGER.info(f"[tts] 🔴 cancelled sid={session_id}")
                break
            await ws_manager.send_audio_chunk(session_id, audio[i:i + CHUNK])
            await asyncio.sleep(0.02)

        # 通知结束
        await ws_manager.send_tts_end(session_id)
        peers = len(ws_manager.active_peers.get(session_id, []))
        LOGGER.info(f"[tts] ✅ broadcast done sid={session_id}, peers={peers}")

    except Exception as e:
        msg = str(e)
        LOGGER.exception(f"[tts] ❌ stream failed sid={session_id}: {msg}")
        await ws_manager.send_tts_error(session_id, msg)
        await ws_manager.send_tts_fallback(session_id, text, msg)

    finally:
        ws_manager.finish_stream(session_id, task)
