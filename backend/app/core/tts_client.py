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

from typing import Tuple

LOGGER = logging.getLogger(__name__)

def _sniff_audio_mime(buf: bytes) -> str:
    """
    粗略嗅探容器类型，返回浏览器可用的 MIME。
    - WAV: 以 RIFF 开头
    - MP3: 以 ID3 开头，或 0xFFEx 的帧头
    - OGG/Opus: OggS
    其余默认当 MP3 处理
    """
    head = buf[:16]
    try:
        if head.startswith(b"RIFF"):
            return "audio/wav"
        # ID3 标记或帧头 0xFFEx
        if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
            return "audio/mpeg"
        if head[:4] == b"OggS":
            return "audio/ogg; codecs=opus"
    except Exception:
        pass
    return "audio/mpeg"

# ==============================
# 🔹 默认火山配置
# ==============================
_DEFAULT_VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_DEFAULT_VOLC_TTS_RES = "volc.service_type.10029"
_DEFAULT_VOLC_TTS_SPK = "zh_male_beijingxiaoye_emo_v2_mars_bigtts"
_DEFAULT_VOLC_TTS_SR = 24000
_DEFAULT_VOLC_TTS_FMT = "mp3"  # ✅ 前后端统一为 mp3

VOLC_TTS_URL = os.getenv("VOLC_TTS_BASE_URL", _DEFAULT_VOLC_TTS_URL)
VOLC_TTS_KEY = os.getenv("VOLC_TTS_API_KEY")
VOLC_TTS_RES = os.getenv("VOLC_TTS_RESOURCE_ID", _DEFAULT_VOLC_TTS_RES)
VOLC_TTS_SPK = os.getenv("VOLC_TTS_SPEAKER", _DEFAULT_VOLC_TTS_SPK)
VOLC_TTS_SR = int(os.getenv("VOLC_TTS_SAMPLE_RATE", _DEFAULT_VOLC_TTS_SR))
VOLC_TTS_FMT = os.getenv("VOLC_TTS_FORMAT", _DEFAULT_VOLC_TTS_FMT)

WS_READY_TIMEOUT = float(os.getenv("TTS_WS_READY_TIMEOUT", 15.0))
CHUNK_SIZE = int(os.getenv("TTS_CHUNK_SIZE", 32 * 1024))

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
    """提取音频字段（火山接口可能嵌套）"""
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
    """合成并推流音频到 WebSocket 客户端（严格二进制帧 + 正确 MIME + 总发 tts_end）"""
    task = asyncio.current_task()
    token = ws_manager.start_stream(session_id, task)
    LOGGER.info(f"[tts] 🚀 start TTS stream sid={session_id}, len={len(text)}")

    audio: bytes | None = None
    sent_end = False

    try:
        # 等前端 ready（超时也继续，避免卡死）
        try:
            await asyncio.wait_for(ws_manager.wait_until_ready(session_id), timeout=WS_READY_TIMEOUT)
            LOGGER.info(f"[tts] ✅ websocket ready sid={session_id}")
        except asyncio.TimeoutError:
            LOGGER.warning(f"[tts] ⚠️ websocket not ready after {WS_READY_TIMEOUT}s, continue sid={session_id}")

        # 生成音频（1 次重试）
        for attempt in range(2):
            try:
                audio = await synth_once(text)
                if audio:
                    break
            except Exception as e:
                LOGGER.warning(f"[tts] synth attempt {attempt+1} failed: {e}")
                await asyncio.sleep(0.5)
        if not audio:
            raise RuntimeError("TTS 合成失败：返回音频为空")

        # ⭕️ 嗅探容器类型，给前端一个“真实可解码”的 MIME
        mime = _sniff_audio_mime(audio)
        await ws_manager.send_tts_ready(session_id, mime=mime)
        LOGGER.info(f"[tts] ▶️ ready sent with mime={mime}, bytes={len(audio)}")

        # ⭕️ 用“二进制帧”分块发送
        #    （确保 WebSocketManager 实现里用的是 ws.send_bytes(chunk)，而不是 send_text/base64）
        total = len(audio)
        chunk_size = CHUNK_SIZE
        for i in range(0, total, chunk_size):
            if token.is_cancelled() or ws_manager.is_cancelled(session_id):
                LOGGER.info(f"[tts] 🔴 cancelled sid={session_id}")
                break
            await ws_manager.send_audio_chunk(session_id, audio[i:i + chunk_size])
            await asyncio.sleep(0.010)  # 平滑一点

        # ✅ 正常完成，发 tts_end
        await ws_manager.send_tts_end(session_id)
        sent_end = True
        peers = len(ws_manager.active_peers.get(session_id, []))
        LOGGER.info(f"[tts] ✅ broadcast done sid={session_id}, peers={peers}")

    except Exception as e:
        msg = str(e)
        LOGGER.exception(f"[tts] ❌ stream failed sid={session_id}: {msg}")
        # 出错也通知前端（fallback 文本 + 模式切换）
        try:
            await ws_manager.send_tts_error(session_id, msg)
            await ws_manager.send_tts_fallback(session_id, text, msg)
        finally:
            # ⭕️ 确保前端能 finalize
            if not sent_end:
                with contextlib.suppress(Exception):
                    await ws_manager.send_tts_end(session_id)

    finally:
        ws_manager.finish_stream(session_id, task)
