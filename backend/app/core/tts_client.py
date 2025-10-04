from __future__ import annotations

import asyncio
import base64
import os
import json
import logging
from typing import Optional

import aiohttp

from .ws_tts_manager import manager as ws_manager

LOGGER = logging.getLogger(__name__)

_DEFAULT_VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_DEFAULT_VOLC_TTS_RES = "volc.service_type.10029"
_DEFAULT_VOLC_TTS_SPK = "zh_male_beijingxiaoye_emo_v2_mars_bigtts"
_DEFAULT_VOLC_TTS_SR = 24000
_DEFAULT_VOLC_TTS_FMT = "mp3"

VOLC_TTS_URL = _DEFAULT_VOLC_TTS_URL
VOLC_TTS_KEY: Optional[str] = None
VOLC_TTS_RES = _DEFAULT_VOLC_TTS_RES
VOLC_TTS_SPK = _DEFAULT_VOLC_TTS_SPK
VOLC_TTS_SR = _DEFAULT_VOLC_TTS_SR
VOLC_TTS_FMT = _DEFAULT_VOLC_TTS_FMT


def refresh_volc_config() -> None:
    """Reload VOLC TTS configuration values from environment variables."""

    global VOLC_TTS_URL
    global VOLC_TTS_KEY
    global VOLC_TTS_RES
    global VOLC_TTS_SPK
    global VOLC_TTS_SR
    global VOLC_TTS_FMT

    VOLC_TTS_URL = os.environ.get("VOLC_TTS_BASE_URL", _DEFAULT_VOLC_TTS_URL)
    VOLC_TTS_KEY = os.environ.get("VOLC_TTS_API_KEY")
    VOLC_TTS_RES = os.environ.get("VOLC_TTS_RESOURCE_ID", _DEFAULT_VOLC_TTS_RES)
    VOLC_TTS_SPK = os.environ.get("VOLC_TTS_SPEAKER", _DEFAULT_VOLC_TTS_SPK)
    VOLC_TTS_SR = int(os.environ.get("VOLC_TTS_SAMPLE_RATE", _DEFAULT_VOLC_TTS_SR))
    VOLC_TTS_FMT = os.environ.get("VOLC_TTS_FORMAT", _DEFAULT_VOLC_TTS_FMT)


refresh_volc_config()

WS_READY_TIMEOUT = float(os.environ.get("TTS_WS_READY_TIMEOUT", 5))


def _volc_config_ready() -> bool:
    return bool(VOLC_TTS_URL and VOLC_TTS_KEY and VOLC_TTS_RES)


async def synth_once(text: str) -> bytes:
    if not VOLC_TTS_URL or not VOLC_TTS_KEY or not VOLC_TTS_RES:
        LOGGER.error(
            "VOLC TTS configuration missing: url=%s key=%s resource=%s",
            bool(VOLC_TTS_URL),
            bool(VOLC_TTS_KEY),
            bool(VOLC_TTS_RES),
        )
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
    LOGGER.debug(
        "Dispatching TTS request",
        extra={
            "target": VOLC_TTS_URL,
            "speaker": VOLC_TTS_SPK,
            "sample_rate": VOLC_TTS_SR,
            "format": VOLC_TTS_FMT,
            "text_preview": text[:32],
            "text_length": len(text),
        },
    )
    async with aiohttp.ClientSession(trust_env=False) as session:
        async with session.post(VOLC_TTS_URL, json=payload, headers=headers) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = await resp.read()
            LOGGER.debug(
                "Received TTS response",
                extra={
                    "status": resp.status,
                    "content_type": content_type,
                    "body_length": len(body),
                },
            )
            if content_type.startswith("audio/"):
                return body
            text_body = body.decode("utf-8", errors="replace")
            payloads = _coerce_json_payloads(text_body)
            if not payloads:
                raise RuntimeError(
                    "TTS bad response"
                    f" ({resp.status} {content_type or 'unknown'}): {text_body}"
                )
            audio_chunks: list[bytes] = []
            for payload in payloads:
                audio_b64 = _extract_audio_field(payload)
                if audio_b64:
                    try:
                        audio_chunks.append(base64.b64decode(audio_b64))
                    except (ValueError, TypeError) as exc:
                        raise RuntimeError(
                            f"TTS invalid audio payload: {payload}"
                        ) from exc
            if not audio_chunks:
                raise RuntimeError(f"TTS bad response payload: {payloads}")
            return b"".join(audio_chunks)


def _coerce_json_payloads(text_body: str) -> list[dict]:
    """Return a list of JSON objects contained within ``text_body``."""
    decoder = json.JSONDecoder()
    idx = 0
    payloads: list[dict] = []
    while idx < len(text_body):
        idx = _skip_whitespace(text_body, idx)
        if idx >= len(text_body):
            break
        try:
            value, next_idx = decoder.raw_decode(text_body, idx)
        except json.JSONDecodeError:
            return []
        idx = next_idx
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _skip_whitespace(text: str, idx: int) -> int:
    while idx < len(text) and text[idx].isspace():
        idx += 1
    return idx


def _extract_audio_field(payload: dict) -> Optional[str]:
    """Locate the base64 audio field in a TTS payload."""
    data_field = payload.get("data")
    if isinstance(data_field, str):
        return data_field or None
    if isinstance(data_field, dict):
        audio = data_field.get("audio")
        if isinstance(audio, str) and audio:
            return audio
    result_field = payload.get("result")
    if isinstance(result_field, dict):
        audio = result_field.get("audio")
        if isinstance(audio, str) and audio:
            return audio
    audio_field = payload.get("audio")
    if isinstance(audio_field, str) and audio_field:
        return audio_field
    return None


async def stream_and_broadcast(session_id: str, text: str) -> None:
    current_task = asyncio.current_task()
    if current_task is None:
        raise RuntimeError("stream_and_broadcast must be awaited within a task context")
    token = ws_manager.start_stream(session_id, current_task)
    fallback_sent = False
    try:
        LOGGER.info(
            "Starting TTS stream",
            extra={
                "session_id": session_id,
                "text_length": len(text),
                "text_preview": text[:32],
            },
        )
        try:
            await asyncio.wait_for(
                ws_manager.wait_until_ready(session_id), WS_READY_TIMEOUT
            )
        except asyncio.TimeoutError:
            fallback_sent = True
            fallback_reason = "语音合成连接超时，已使用浏览器朗读。"
            diagnostics = await ws_manager.diagnostic_state(session_id)
            LOGGER.warning(
                "TTS websocket never became ready; switching to browser fallback",
                extra={
                    "session_id": session_id,
                    "timeout_seconds": WS_READY_TIMEOUT,
                    "text_length": len(text),
                    "ws_diagnostics": diagnostics,
                },
            )
            await ws_manager.send_tts_error(session_id, fallback_reason)
            await ws_manager.send_tts_fallback(session_id, text, fallback_reason)  # ✅ 修复
            return

        if not _volc_config_ready():
            fallback_sent = True
            fallback_reason = "语音合成功能未配置，已使用浏览器朗读。"
            LOGGER.warning(
                "VOLC TTS configuration incomplete; switching to browser fallback",
                extra={
                    "session_id": session_id,
                    "volc_url": bool(VOLC_TTS_URL),
                    "volc_key": bool(VOLC_TTS_KEY),
                    "volc_resource": bool(VOLC_TTS_RES),
                },
            )
            await ws_manager.send_tts_error(session_id, fallback_reason)
            await ws_manager.send_tts_fallback(session_id, text, fallback_reason)  # ✅ 修复
            return

        audio = await synth_once(text)
        chunk_size = 32 * 1024
        for start in range(0, len(audio), chunk_size):
            if token.is_cancelled() or ws_manager.is_cancelled(session_id):
                break
            chunk = audio[start:start + chunk_size]
            await ws_manager.send_audio_chunk(session_id, chunk)

    except asyncio.CancelledError:
        LOGGER.info(
            "TTS stream cancelled", extra={"session_id": session_id, "reason": "cancelled"}
        )
    except Exception as exc:
        LOGGER.exception(
            "TTS synthesis failed",
            extra={
                "session_id": session_id,
                "text_length": len(text),
                "fallback_sent": fallback_sent,
            },
        )
        reason = str(exc) or "语音合成失败，已使用浏览器朗读。"
        await ws_manager.send_tts_error(session_id, reason)
        if not fallback_sent:
            await ws_manager.send_tts_fallback(session_id, text, reason)  # ✅ 修复
    finally:
        try:
            await ws_manager.send_tts_end(session_id)
            LOGGER.info("TTS stream finished", extra={"session_id": session_id})
        finally:
            ws_manager.finish_stream(session_id, current_task)