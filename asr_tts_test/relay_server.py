# asr_tts_test/relay_server.py
# -*- coding: utf-8 -*-
"""
WebSocket Relay: Browser <-> Volcengine OpenSpeech (ASR WS v2)

浏览器：
  1) 先发 {"type":"start","sampleRate":48000,"language":"zh-CN"}
  2) 持续发二进制 Int16 PCM（单声道）
  3) 结束时发 {"type":"stop"} 或 "stop"

本中转只做两件事：
  * 把浏览器原始 PCM 转发给火山
  * 把火山结果抽取为 {type:"partial"|"final", text:"..."} 再发回浏览器
并且做了关键改动：**去重增量** —— 仅把“新确认”的句子作为 final 下发；partial 只有变化时才下发。
"""

import asyncio
import gzip
import json
import os
import uuid
import traceback

import websockets

# ===== 基本配置（可用环境变量覆盖） =====
APPID   = os.getenv("VOLS_APPID", "8726984949")
TOKEN   = os.getenv("VOLS_TOKEN", "cABD3Fc92li99s7i5vslzIvw6ZxlUad2")
CLUSTER = os.getenv("VOLS_CLUSTER", "volcengine_streaming")
WS_URL  = os.getenv("VOLS_WS_URL", "wss://openspeech.bytedance.com/api/v2/asr")

# 强制关闭代理，避免被系统代理劫持
for k in ("HTTPS_PROXY","https_proxy","HTTP_PROXY","http_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "openspeech.bytedance.com"

# ===== 火山 WS v2 framing 常量 =====
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


def _hdr(msg_type, flags=NO_SEQUENCE, serial=JSON_SERIAL, comp=GZIP_COMP, ext=b""):
    """生成 4*N 字节的头"""
    header = bytearray()
    header_size = int(len(ext) / 4) + 1
    header.append((PROTOCOL_VERSION << 4) | header_size)
    header.append((msg_type << 4) | flags)
    header.append((serial << 4) | comp)
    header.append(0x00)
    header.extend(ext)
    return header


def hdr_full():
    return _hdr(CLIENT_FULL_REQUEST)


def hdr_audio():
    return _hdr(CLIENT_AUDIO_ONLY_REQUEST)


def hdr_last():
    return _hdr(CLIENT_AUDIO_ONLY_REQUEST, flags=NEG_SEQUENCE)


def parse_response(res: bytes):
    """解析服务端帧 -> dict"""
    try:
        header_size = res[0] & 0x0F
        msg_type = res[1] >> 4
        serial = res[2] >> 4
        comp = res[2] & 0x0F
        payload = res[header_size * 4:]

        out = {}
        payload_msg = None
        size = 0

        if msg_type == SERVER_FULL_RESPONSE:
            size = int.from_bytes(payload[:4], "big", signed=True)
            payload_msg = payload[4:]
        elif msg_type == SERVER_ACK:
            out["seq"] = int.from_bytes(payload[:4], "big", signed=True)
            if len(payload) >= 8:
                size = int.from_bytes(payload[4:8], "big", signed=False)
                payload_msg = payload[8:]
        elif msg_type == SERVER_ERROR_RESPONSE:
            out["code"] = int.from_bytes(payload[:4], "big", signed=False)
            size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]

        if payload_msg is None:
            return out

        if comp == GZIP_COMP:
            payload_msg = gzip.decompress(payload_msg)

        if serial == JSON_SERIAL:
            payload_msg = json.loads(payload_msg.decode("utf-8"))
        else:
            payload_msg = payload_msg.decode("utf-8")

        out["payload_msg"] = payload_msg
        out["payload_size"] = size
        return out
    except Exception:
        print("[relay] parse_response error:", traceback.format_exc())
        return {}


def volc_headers_token():
    """部分线路需要 'Bearer; ' 的老式写法"""
    return {"Authorization": f"Bearer; {TOKEN}"}


def build_full_request(reqid: str, in_rate: int, language: str):
    # 关键点：format=pcm, codec=raw, rate=浏览器真实采样率（常见 48000）
    return {
        "app":   {"appid": APPID, "cluster": CLUSTER, "token": TOKEN},
        "user":  {"uid": "browser_mic"},
        "request": {
            "reqid": reqid,
            "nbest": 1,
            "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate",
            "show_language": False,
            "show_utterances": True,
            "result_type": "full",
            "sequence": 1
        },
        "audio": {
            "format": "pcm",
            "codec":  "raw",
            "rate":    in_rate,
            "bits":    16,
            "channel": 1,
            "language": language
        }
    }


async def handle_browser(ws_client):
    path = getattr(ws_client, "path", "/")
    if path not in ("/asr", "/"):
        await ws_client.close(code=1008, reason="invalid path")
        return

    print("[relay] client connected", path)

    # 默认参数（若浏览器第一条就是音频，按 48000/zh-CN）
    in_rate = 48000
    language = "zh-CN"

    # 收第一条（start 或者第一帧音频）
    try:
        first_msg = await asyncio.wait_for(ws_client.recv(), timeout=10.0)
    except asyncio.TimeoutError:
        print("[relay] client no first msg within 10s; closing")
        return
    except websockets.ConnectionClosed:
        print("[relay] client closed before start")
        return

    if isinstance(first_msg, (bytes, bytearray)):
        pass  # 直接音频：用默认 in_rate/language
    else:
        try:
            obj = json.loads(first_msg)
            if obj.get("type") == "start":
                in_rate = int(obj.get("sampleRate", in_rate))
                language = obj.get("language", language)
            else:
                await ws_client.send(json.dumps(
                    {"type": "error", "message": "first msg must be {type:'start'} or binary"},
                    ensure_ascii=False
                ))
                return
        except Exception:
            await ws_client.send(json.dumps(
                {"type": "error", "message": "invalid first message"},
                ensure_ascii=False
            ))
            return

    # === 连接火山并握手 ===
    reqid = str(uuid.uuid4())
    full_req = gzip.compress(json.dumps(build_full_request(reqid, in_rate, language)).encode("utf-8"))
    first_frame = bytearray(hdr_full())
    first_frame.extend(len(full_req).to_bytes(4, "big"))
    first_frame.extend(full_req)

    try:
        async with websockets.connect(
            WS_URL,
            extra_headers=volc_headers_token(),
            close_timeout=5,
            open_timeout=12,
            max_size=10_000_000,
        ) as ws_volc:

            # 发送 full request
            await ws_volc.send(first_frame)
            r0 = await ws_volc.recv()
            if isinstance(r0, str):
                r0 = r0.encode("utf-8")
            parsed0 = parse_response(r0)
            await ws_client.send(json.dumps(
                {"type": "handshake", "payload": parsed0.get("payload_msg")},
                ensure_ascii=False
            ))

            if (parsed0.get("payload_msg") or {}).get("code", 1000) != 1000:
                # 握手失败直接返回
                return

            # ---------- 增量/去重 状态 ----------
            last_committed_end = -1  # 已下发的最后一个 final 句子的 end_time（ms）
            last_partial_text = ""   # 最近一次下发的 partial 文本

            # --- 从火山收消息并转发给浏览器（唯一接收方） ---
            async def volc_recv():
                nonlocal last_committed_end, last_partial_text
                try:
                    while True:
                        m = await ws_volc.recv()
                        if isinstance(m, str):
                            m = m.encode("utf-8")
                        parsed = parse_response(m)
                        pm = parsed.get("payload_msg")
                        if not pm:
                            continue

                        # 只关心包含识别结果的负载，ACK/心跳忽略
                        if isinstance(pm, dict) and set(pm.keys()) <= {"addition", "code", "message", "reqid", "sequence"}:
                            continue

                        # 统一取 utterances 列表
                        def get_utterances(obj):
                            if not isinstance(obj, dict):
                                return []
                            if "utterances" in obj and isinstance(obj["utterances"], list):
                                return obj["utterances"]
                            r = obj.get("result")
                            if isinstance(r, dict):
                                return r.get("utterances") or []
                            if isinstance(r, list) and r:
                                return (r[-1].get("utterances") or []) if isinstance(r[-1], dict) else []
                            return []

                        utt = get_utterances(pm)
                        if not utt:
                            # 有些线路把“当前整段文本”放在 result[-1].text；但那通常是“累计全文”，这里不下发以免重复。
                            continue

                        # 1) 先找所有“新确认”的句子：definite/is_final/type 标识，且 end_time 更大
                        new_finals = []
                        for u in utt:
                            if not isinstance(u, dict):
                                continue
                            t = u.get("text") or u.get("normalized_text") or u.get("transcript") or ""
                            if not t:
                                continue
                            is_final = bool(
                                (u.get("definite") is True)
                                or u.get("is_final")
                                or (u.get("type") in ("final", "sentence_end"))
                            )
                            end_t = int(u.get("end_time") or 0)
                            if is_final and end_t > last_committed_end:
                                new_finals.append((end_t, t))

                        # 按时间顺序把“新确认”的句子逐个下发，并推进 last_committed_end
                        if new_finals:
                            new_finals.sort(key=lambda x: x[0])
                            for end_t, t in new_finals:
                                try:
                                    await ws_client.send(json.dumps({"type": "final", "text": t}, ensure_ascii=False))
                                except websockets.ConnectionClosed:
                                    return
                                last_committed_end = max(last_committed_end, end_t)
                            # final 一旦下发，partial 一般也该清掉
                            last_partial_text = ""

                        # 2) 再处理“最新一条且未定稿”的 partial（变化才下发）
                        last_u = utt[-1] if utt else {}
                        pt = (last_u.get("text") or last_u.get("normalized_text") or last_u.get("transcript") or "").strip()
                        is_last_final = bool(
                            (last_u.get("definite") is True)
                            or last_u.get("is_final")
                            or (last_u.get("type") in ("final", "sentence_end"))
                        )
                        if pt and (not is_last_final) and pt != last_partial_text:
                            try:
                                await ws_client.send(json.dumps({"type": "partial", "text": pt}, ensure_ascii=False))
                            except websockets.ConnectionClosed:
                                return
                            last_partial_text = pt

                except websockets.ConnectionClosed:
                    return
                except Exception:
                    print("[relay] volc_recv error:", traceback.format_exc())
                    return

            recv_task = asyncio.create_task(volc_recv())

            # --- 如果第一条就是音频，先发出去 ---
            async def send_pcm_chunk(chunk: bytes):
                if not chunk:
                    return
                gz = gzip.compress(chunk)
                frame = bytearray(hdr_audio())
                frame.extend(len(gz).to_bytes(4, "big"))
                frame.extend(gz)
                await ws_volc.send(frame)
                # 不再逐帧打印，避免刷屏
                # print(f"[relay] send pcm {len(chunk)} bytes @rate {in_rate}")

            if isinstance(first_msg, (bytes, bytearray)):
                await send_pcm_chunk(first_msg)

            # --- 主循环：浏览器 -> 火山 ---
            while True:
                try:
                    msg = await ws_client.recv()
                except websockets.ConnectionClosedOK:
                    break
                except websockets.ConnectionClosed:
                    break

                if isinstance(msg, (bytes, bytearray)):
                    await send_pcm_chunk(msg)
                else:
                    # 控制消息
                    try:
                        obj = json.loads(msg)
                        if obj.get("type") == "stop":
                            gz = gzip.compress(b"")
                            lastf = bytearray(hdr_last())
                            lastf.extend(len(gz).to_bytes(4, "big"))
                            lastf.extend(gz)
                            await ws_volc.send(lastf)
                            try:
                                await ws_client.send(json.dumps({"type": "stopped"}))
                            except websockets.ConnectionClosed:
                                pass
                            break
                    except Exception:
                        # 兼容纯文本 "stop"
                        if msg == "stop":
                            gz = gzip.compress(b"")
                            lastf = bytearray(hdr_last())
                            lastf.extend(len(gz).to_bytes(4, "big"))
                            lastf.extend(gz)
                            await ws_volc.send(lastf)
                            try:
                                await ws_client.send(json.dumps({"type": "stopped"}))
                            except websockets.ConnectionClosed:
                                pass
                            break

            # 给 volc_recv 留一点时间把尾包读完
            try:
                await asyncio.sleep(0.6)
            except Exception:
                pass
            recv_task.cancel()

    finally:
        print("[relay] client disconnected")


async def main():
    server = await websockets.serve(handle_browser, "127.0.0.1", 8765)
    print("Relay server listening on ws://127.0.0.1:8765/asr")
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
