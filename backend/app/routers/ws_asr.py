from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import logging
import os
import uuid
from typing import Any, Dict, Iterable

import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..utils.ws_manager import WebSocketManager


LOGGER = logging.getLogger(__name__)

APPID = os.getenv("VOLS_APPID", "")
TOKEN = os.getenv("VOLS_TOKEN", "")
CLUSTER = os.getenv("VOLS_CLUSTER", "volcengine_streaming")
WS_URL = os.getenv("VOLS_WS_URL", "wss://openspeech.bytedance.com/api/v2/asr")

PROTOCOL_VERSION = 0b0001
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

NO_SEQUENCE = 0b0000
NEG_SEQUENCE = 0b0010

JSON_SERIAL = 0b0001
GZIP_COMP = 0b0001


router = APIRouter()
manager = WebSocketManager()


def _hdr(msg_type: int, *, flags: int = NO_SEQUENCE, serial: int = JSON_SERIAL, comp: int = GZIP_COMP, ext: bytes = b"") -> bytearray:
    header = bytearray()
    header_size = int(len(ext) / 4) + 1
    header.append((PROTOCOL_VERSION << 4) | header_size)
    header.append((msg_type << 4) | flags)
    header.append((serial << 4) | comp)
    header.append(0x00)
    header.extend(ext)
    return header


def hdr_full() -> bytearray:
    return _hdr(CLIENT_FULL_REQUEST)


def hdr_audio() -> bytearray:
    return _hdr(CLIENT_AUDIO_ONLY_REQUEST)


def hdr_last() -> bytearray:
    return _hdr(CLIENT_AUDIO_ONLY_REQUEST, flags=NEG_SEQUENCE)


def parse_response(payload: bytes) -> Dict[str, Any]:
    try:
        header_size = payload[0] & 0x0F
        msg_type = payload[1] >> 4
        serial = payload[2] >> 4
        comp = payload[2] & 0x0F
        body = payload[header_size * 4 :]

        response: Dict[str, Any] = {}
        payload_msg: Any = None
        size = 0

        if msg_type == SERVER_FULL_RESPONSE:
            size = int.from_bytes(body[:4], "big", signed=True)
            payload_msg = body[4:]
        elif msg_type == SERVER_ACK:
            response["seq"] = int.from_bytes(body[:4], "big", signed=True)
            if len(body) >= 8:
                size = int.from_bytes(body[4:8], "big", signed=False)
                payload_msg = body[8:]
        elif msg_type == SERVER_ERROR_RESPONSE:
            response["code"] = int.from_bytes(body[:4], "big", signed=False)
            size = int.from_bytes(body[4:8], "big", signed=False)
            payload_msg = body[8:]

        if payload_msg is None:
            return response

        if comp == GZIP_COMP:
            payload_msg = gzip.decompress(payload_msg)

        if serial == JSON_SERIAL:
            payload_msg = json.loads(payload_msg.decode("utf-8"))
        else:
            payload_msg = payload_msg.decode("utf-8")

        response["payload_msg"] = payload_msg
        response["payload_size"] = size
        return response
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to parse ASR response")
        return {}


def volc_headers_token() -> Dict[str, str]:
    return {"Authorization": f"Bearer; {TOKEN}"}


def build_full_request(reqid: str, in_rate: int, language: str) -> Dict[str, Any]:
    return {
        "app": {"appid": APPID, "cluster": CLUSTER, "token": TOKEN},
        "user": {"uid": "browser_mic"},
        "request": {
            "reqid": reqid,
            "nbest": 1,
            "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate",
            "show_language": False,
            "show_utterances": True,
            "result_type": "full",
            "sequence": 1,
        },
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": in_rate,
            "bits": 16,
            "channel": 1,
            "language": language,
        },
    }


async def _send_pcm_chunk(ws_volc: aiohttp.ClientWebSocketResponse, chunk: bytes) -> None:
    if not chunk:
        return
    gz = gzip.compress(chunk)
    frame = bytearray(hdr_audio())
    frame.extend(len(gz).to_bytes(4, "big"))
    frame.extend(gz)
    await ws_volc.send_bytes(frame)


async def _send_last_frame(ws_volc: aiohttp.ClientWebSocketResponse) -> None:
    gz = gzip.compress(b"")
    frame = bytearray(hdr_last())
    frame.extend(len(gz).to_bytes(4, "big"))
    frame.extend(gz)
    await ws_volc.send_bytes(frame)


def _extract_utterances(payload_msg: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(payload_msg, dict):
        return []
    if isinstance(payload_msg.get("utterances"), list):
        return payload_msg["utterances"]
    result = payload_msg.get("result")
    if isinstance(result, dict) and isinstance(result.get("utterances"), list):
        return result["utterances"]
    if isinstance(result, list) and result:
        last = result[-1]
        if isinstance(last, dict) and isinstance(last.get("utterances"), list):
            return last["utterances"]
    return []

@router.websocket("/ws/asr")
async def websocket_asr(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session") or "default"
    await manager.connect(session_id, websocket)

    if not (APPID and TOKEN):
        await manager.send_json(
            session_id,
            {"type": "asr_error", "message": "ASR credentials are not configured."},
        )
        manager.disconnect(session_id)
        return

    try:
        await _relay_to_volc(session_id, websocket)
    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except asyncio.CancelledError:  # pragma: no cover - propagate cancellation
        manager.disconnect(session_id)
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("ASR relay failed")
        try:
            await manager.send_json(session_id, {"type": "asr_error", "message": str(exc)})
        except Exception:
            pass
        manager.disconnect(session_id)


async def _relay_to_volc(session_id: str, websocket: WebSocket) -> None:
    in_rate = 48000
    language = "zh-CN"
    first_chunk: bytes | None = None

    try:
        first_message = await asyncio.wait_for(websocket.receive(), timeout=10.0)
    except asyncio.TimeoutError:
        await manager.send_json(session_id, {"type": "asr_error", "message": "No audio received within 10 seconds."})
        return

    if first_message.get("type") == "websocket.disconnect":
        return

    text_data = first_message.get("text")
    if text_data is not None:
        text_data = text_data.strip()
        if text_data:
            try:
                payload = json.loads(text_data)
            except json.JSONDecodeError:
                await manager.send_json(
                    session_id,
                    {"type": "asr_error", "message": "First text frame must be a JSON start message."},
                )
                return
            if payload.get("type") == "start":
                in_rate = int(payload.get("sampleRate", in_rate))
                language = payload.get("language", language)
            else:
                await manager.send_json(
                    session_id,
                    {"type": "asr_error", "message": "First message must be {type:'start'} or binary audio."},
                )
                return
    else:
        first_chunk = first_message.get("bytes")

    reqid = str(uuid.uuid4())
    full_req = gzip.compress(json.dumps(build_full_request(reqid, in_rate, language)).encode("utf-8"))
    first_frame = bytearray(hdr_full())
    first_frame.extend(len(full_req).to_bytes(4, "big"))
    first_frame.extend(full_req)

    timeout = aiohttp.ClientTimeout(total=None, connect=12, sock_read=None)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        async with session.ws_connect(
            WS_URL,
            headers=volc_headers_token(),
            receive_timeout=15,
            max_msg_size=10_000_000,
        ) as ws_volc:
            await ws_volc.send_bytes(first_frame)
            handshake = await ws_volc.receive()
            if handshake.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            ):
                await manager.send_json(session_id, {"type": "asr_error", "message": "ASR upstream closed during handshake."})
                return
            if handshake.type == aiohttp.WSMsgType.ERROR:
                await manager.send_json(session_id, {"type": "asr_error", "message": "ASR upstream error during handshake."})
                return
            raw = handshake.data.encode("utf-8") if handshake.type == aiohttp.WSMsgType.TEXT else handshake.data
            parsed0 = parse_response(raw)
            try:
                await manager.send_json(session_id, {"type": "asr_handshake", "payload": parsed0.get("payload_msg")})
            except Exception:
                pass

            payload_msg_raw = parsed0.get("payload_msg")
            payload_dict = payload_msg_raw if isinstance(payload_msg_raw, dict) else {}
            if payload_dict.get("code") not in (None, 1000):
                await manager.send_json(
                    session_id,
                    {"type": "asr_error", "message": f"Handshake failed: {payload_msg_raw}"},
                )
                return

            last_committed_end = -1
            last_partial = ""

            async def volc_recv() -> None:
                nonlocal last_committed_end, last_partial
                try:
                    while True:
                        message = await ws_volc.receive()
                        if message.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                        raw_payload = message.data.encode("utf-8") if message.type == aiohttp.WSMsgType.TEXT else message.data
                        parsed = parse_response(raw_payload)
                        payload = parsed.get("payload_msg")
                        if not payload or (
                            isinstance(payload, dict)
                            and set(payload.keys()).issubset({"addition", "code", "message", "reqid", "sequence"})
                        ):
                            continue

                        utterances = list(_extract_utterances(payload))
                        if not utterances:
                            continue

                        new_finals = []
                        for utt in utterances:
                            if not isinstance(utt, dict):
                                continue
                            text = (
                                utt.get("text")
                                or utt.get("normalized_text")
                                or utt.get("transcript")
                                or ""
                            ).strip()
                            if not text:
                                continue
                            is_final = bool(
                                utt.get("definite") is True
                                or utt.get("is_final")
                                or utt.get("type") in {"final", "sentence_end"}
                            )
                            end_time = int(utt.get("end_time") or 0)
                            if is_final and end_time > last_committed_end:
                                new_finals.append((end_time, text))

                        if new_finals:
                            new_finals.sort(key=lambda item: item[0])
                            for end_time, text in new_finals:
                                try:
                                    await manager.send_json(session_id, {"type": "asr_final", "text": text})
                                except Exception:
                                    return
                                last_committed_end = max(last_committed_end, end_time)
                            last_partial = ""

                        last_utt = utterances[-1]
                        partial_text = (
                            last_utt.get("text")
                            or last_utt.get("normalized_text")
                            or last_utt.get("transcript")
                            or ""
                        ).strip()
                        is_last_final = bool(
                            last_utt.get("definite") is True
                            or last_utt.get("is_final")
                            or last_utt.get("type") in {"final", "sentence_end"}
                        )
                        if partial_text and not is_last_final and partial_text != last_partial:
                            try:
                                await manager.send_json(session_id, {"type": "asr_partial", "text": partial_text})
                            except Exception:
                                return
                            last_partial = partial_text
                except asyncio.CancelledError:
                    raise
                except Exception:  # pragma: no cover - defensive logging
                    LOGGER.exception("Error receiving from ASR upstream")

            recv_task = asyncio.create_task(volc_recv())

            if first_chunk:
                await _send_pcm_chunk(ws_volc, first_chunk)

            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        await _send_last_frame(ws_volc)
                        break
                    if message.get("bytes") is not None:
                        await _send_pcm_chunk(ws_volc, message["bytes"])
                        continue
                    text_frame = message.get("text")
                    if text_frame is None:
                        continue
                    text_frame = text_frame.strip()
                    if not text_frame:
                        continue
                    if text_frame == "stop":
                        await _send_last_frame(ws_volc)
                        await manager.send_json(session_id, {"type": "asr_stopped"})
                        break
                    try:
                        control = json.loads(text_frame)
                    except json.JSONDecodeError:
                        continue
                    if control.get("type") == "stop":
                        await _send_last_frame(ws_volc)
                        await manager.send_json(session_id, {"type": "asr_stopped"})
                        break
            finally:
                try:
                    await asyncio.sleep(0.6)
                except Exception:
                    pass
                recv_task.cancel()
                with contextlib.suppress(Exception):
                    await recv_task


__all__ = ["websocket_asr"]
