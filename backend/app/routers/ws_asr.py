# app/routers/ws_asr.py
from __future__ import annotations
import asyncio, contextlib, gzip, json, logging, os, uuid
from typing import Any
import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..utils.ws_manager import WebSocketManager

LOGGER = logging.getLogger(__name__)

APPID = os.getenv("VOLS_APPID", "")
TOKEN = os.getenv("VOLS_TOKEN", "")
CLUSTER = os.getenv("VOLS_CLUSTER", "volcengine_streaming")
WS_URL = os.getenv("VOLS_WS_URL", "wss://openspeech.bytedance.com/api/v2/asr")

router = APIRouter()

# 本地兜底 manager（运行时会被 app.state.ws_manager 替换）
manager = WebSocketManager()


def build_full_request(reqid: str, sample_rate: int, language: str) -> dict:
    """构造 volcengine ASR 的初始化请求包"""
    return {
        "app": {
            "appid": os.getenv("VOLS_APPID", "demo_appid"),
            "token": os.getenv("VOLS_TOKEN", "demo_token"),
            "cluster": os.getenv("VOLS_CLUSTER", "volcengine_streaming"),
        },
        "user": {
            "uid": "test_user",
        },
        "request": {
            "reqid": reqid,
            "engine_type": "asr",
            "sequence": 1,
            "speech_language": language,
            "sample_rate": sample_rate,
            "audio_format": "pcm",
            "needpartial": True,
        },
    }


def volc_headers_token() -> dict:
    """Volcengine ASR websocket headers"""
    return {
        "Authorization": f"Bearer {os.getenv('VOLS_TOKEN', 'demo_token')}",
        "Accept-Encoding": "gzip",
    }


def hdr_full() -> bytes:
    """Volcengine 自定义帧头前缀（魔术字节标识）"""
    # 按火山协议标准，这里可简化为固定头
    # 实际字节序列根据协议需要调整
    return b'\x00\x00\x00\x00'


def parse_response(raw: bytes) -> dict:
    """解析 volcengine 返回的数据帧（兼容 text / gzip）"""
    try:
        if raw[:2] == b'\x1f\x8b':  # gzip magic
            import gzip
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8")
        return json.loads(text)
    except Exception:
        return {"payload_msg": {}}


def _extract_utterances(payload: dict):
    """抽取 volcengine 返回中的句子列表"""
    for item in payload.get("result", []):
        for utt in item.get("utterances", []):
            yield utt


async def _send_pcm_chunk(ws, chunk: bytes):
    """发送音频块到 volcengine"""
    try:
        await ws.send_bytes(chunk)
    except Exception as e:
        LOGGER.warning(f"[ASR] send_pcm_chunk failed: {e}")


async def _send_last_frame(ws):
    """发送结束标志帧"""
    try:
        await ws.send_bytes(b"")
        await ws.close()
    except Exception:
        pass

# ===========================================================
# === 🔧 主流程：与火山ASR桥接 ===
# ===========================================================
async def _relay_to_volc(session_id: str, websocket: WebSocket, mgr: WebSocketManager) -> None:
    import aiohttp, gzip, uuid, json, os, asyncio
    from app.routers.ws_asr_framing import (
        generate_full_default_header,
        generate_audio_default_header,
        generate_last_audio_default_header,
        parse_response,
    )

    LOGGER.info(f"[ASR] === START relay sid={session_id}")

    ws_url = os.getenv("VOLS_WS_URL", "wss://openspeech.bytedance.com/api/v2/asr")
    token = os.getenv("VOLS_TOKEN", "")
    cluster = os.getenv("VOLS_CLUSTER", "volcengine_streaming")
    appid = os.getenv("VOLS_APPID", "")

    # 前端 start
    msg = await websocket.receive_json()
    rate = msg.get("sampleRate", 16000)
    lang = msg.get("language", "zh-CN")
    LOGGER.info(f"[ASR] 🧾 start params sid={session_id} rate={rate} lang={lang}")

    # 初始化包
    reqid = str(uuid.uuid4())
    request = {
        "app": {"appid": appid, "cluster": cluster, "token": token},
        "user": {"uid": "relay_asr"},
        "request": {
            "reqid": reqid,
            "nbest": 1,
            "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate",
            "show_utterances": True,
            "result_type": "full",
        },
        "audio": {
            "format": "pcm",
            "rate": rate,
            "language": lang,
            "bits": 16,
            "channel": 1,
            "codec": "raw",
        },
    }

    payload = gzip.compress(json.dumps(request).encode("utf-8"))
    frame = bytearray(generate_full_default_header())
    frame.extend(len(payload).to_bytes(4, "big"))
    frame.extend(payload)

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(
            ws_url,
            headers={"Authorization": f"Bearer; {token}"},
            max_msg_size=10_000_000,
        ) as ws_volc:
            LOGGER.info(f"[ASR] 🌐 connecting volcengine sid={session_id}")

            await ws_volc.send_bytes(frame)
            LOGGER.info(f"[ASR] 🔧 full frame sent ({len(payload)} bytes)")

            handshake = await ws_volc.receive()
            if handshake.type == aiohttp.WSMsgType.BINARY:
                parsed = parse_response(handshake.data)
                LOGGER.info(f"[ASR] ✅ handshake ok {parsed}")
                await mgr.send_json(session_id, {"type": "asr_handshake", "payload": parsed})
            else:
                LOGGER.warning(f"[ASR] ⚠️ unexpected handshake {handshake.type}")

            await mgr.notify_ready(session_id, "asr")

            # 🔁 volc 下行任务
            async def volc_recv():
                try:
                    async for msg in ws_volc:
                        if msg.type != aiohttp.WSMsgType.BINARY:
                            continue
                        parsed = parse_response(msg.data)
                        payload_msg = parsed.get("payload_msg")
                        if not payload_msg:
                            continue

                        result_list = payload_msg.get("result") or []
                        if not result_list:
                            continue

                        for res in result_list:
                            for utt in res.get("utterances", []):
                                text = utt.get("text") or utt.get("normalized_text") or ""
                                if not text:
                                    continue
                                definite = utt.get("definite") or utt.get("is_final")
                                if not definite:
                                    await mgr.send_json(session_id, {"type": "asr_partial", "text": text})
                                else:
                                    await mgr.send_json(session_id, {"type": "asr_final", "text": text})
                                    await mgr.send_json(session_id, {"type": "query", "text": text})
                except Exception:
                    LOGGER.exception("[ASR] volc_recv failed")


            recv_task = asyncio.create_task(volc_recv())

            # 🔁 前端音频上传
            try:
                while True:
                    chunk = await websocket.receive()
                    if chunk["type"] == "websocket.disconnect":
                        LOGGER.info(f"[ASR] 🔴 client disconnect sid={session_id}")
                        break

                    if chunk.get("bytes"):
                        pcm = chunk["bytes"]
                        LOGGER.info(f"[ASR] 🔹 recv PCM {len(pcm)} bytes sid={session_id}")
                        comp = gzip.compress(pcm)
                        pkt = bytearray(generate_audio_default_header())
                        pkt.extend(len(comp).to_bytes(4, "big"))
                        pkt.extend(comp)
                        await ws_volc.send_bytes(pkt)
                    elif chunk.get("text", "").strip() in {"stop", '{"type":"stop"}'}:
                        LOGGER.info(f"[ASR] 🟥 stop received sid={session_id}")
                        comp = gzip.compress(b"")
                        pkt = bytearray(generate_last_audio_default_header())
                        pkt.extend(len(comp).to_bytes(4, "big"))
                        pkt.extend(comp)
                        await ws_volc.send_bytes(pkt)
                        break
            finally:
                recv_task.cancel()
                LOGGER.info(f"[ASR] 🧹 cleaned sid={session_id}")

# ===========================================================
# === 🔌 WebSocket 路由入口 ===
# ===========================================================
@router.websocket("/ws/asr")
async def websocket_asr(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.query_params.get("session") or "default"
    mgr: WebSocketManager = getattr(websocket.app.state, "ws_manager", manager)
    LOGGER.info(f"[asr] 🎙️ connected sid={session_id}")

    try:
        await _relay_to_volc(session_id, websocket, mgr)
    except WebSocketDisconnect:
        LOGGER.info(f"[asr] 🔴 disconnected sid={session_id}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOGGER.exception(f"[asr] ❌ Exception sid={session_id}: {e}")
        await mgr.send_json(session_id, {"type": "asr_error", "message": str(e)})
    finally:
        await mgr.disconnect(session_id)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
        LOGGER.info(f"[asr] 🧹 cleaned sid={session_id}")
