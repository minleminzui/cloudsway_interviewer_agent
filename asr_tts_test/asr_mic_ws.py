# asr_mic_ws.py
# -*- coding: utf-8 -*-
"""
Mic -> Volcengine OpenSpeech ASR (WS v2 framing) streaming demo.

依赖:
  pip install "websockets>=11,<12" sounddevice
首次运行如遇 macOS 权限，请到“系统设置 → 隐私与安全性 → 麦克风”为终端/IDE 授权。
"""

import asyncio, base64, gzip, hmac, json, os, uuid
from enum import Enum
from hashlib import sha256
from urllib.parse import urlparse

import websockets
import sounddevice as sd

# -------- 你的控制台信息（直写） --------
appid   = "8726984949"
token   = "cABD3Fc92li99s7i5vslzIvw6ZxlUad2"
cluster = "volcengine_streaming"   # 推荐

# -------- 关闭代理（关键！） --------
for k in ("HTTPS_PROXY","https_proxy","HTTP_PROXY","http_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "openspeech.bytedance.com"

# -------- V1 framing 常量（保持官方示例） --------
PROTOCOL_VERSION = 0b0001
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

NO_SEQUENCE = 0b0000
NEG_SEQUENCE = 0b0010

NO_SERIALIZATION = 0b0000
JSON = 0b0001

NO_COMPRESSION = 0b0000
GZIP = 0b0001

def generate_header(version=PROTOCOL_VERSION,
                    message_type=CLIENT_FULL_REQUEST,
                    message_type_specific_flags=NO_SEQUENCE,
                    serial_method=JSON,
                    compression_type=GZIP,
                    reserved_data=0x00,
                    extension_header=bytes()):
    header = bytearray()
    header_size = int(len(extension_header)/4) + 1
    header.append((version << 4) | header_size)
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved_data)
    header.extend(extension_header)
    return header

def generate_full_default_header():
    return generate_header()

def generate_audio_default_header():
    return generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST)

def generate_last_audio_default_header():
    return generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                           message_type_specific_flags=NEG_SEQUENCE)

def parse_response(res: bytes):
    # 解析服务端帧
    protocol_version = res[0] >> 4
    header_size = res[0] & 0x0f
    message_type = res[1] >> 4
    message_type_specific_flags = res[1] & 0x0f
    serialization_method = res[2] >> 4
    message_compression = res[2] & 0x0f
    payload = res[header_size * 4:]

    result, payload_msg, payload_size = {}, None, 0

    if message_type == SERVER_FULL_RESPONSE:
        payload_size = int.from_bytes(payload[:4], "big", signed=True)
        payload_msg = payload[4:]
    elif message_type == SERVER_ACK:
        seq = int.from_bytes(payload[:4], "big", signed=True)
        result['seq'] = seq
        if len(payload) >= 8:
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]
    elif message_type == SERVER_ERROR_RESPONSE:
        code = int.from_bytes(payload[:4], "big", signed=False)
        result['code'] = code
        payload_size = int.from_bytes(payload[4:8], "big", signed=False)
        payload_msg = payload[8:]

    if payload_msg is None:
        return result

    if message_compression == GZIP:
        payload_msg = gzip.decompress(payload_msg)
    if serialization_method == JSON:
        payload_msg = json.loads(payload_msg.decode("utf-8"))
    elif serialization_method != NO_SERIALIZATION:
        payload_msg = payload_msg.decode("utf-8")

    result['payload_msg'] = payload_msg
    result['payload_size'] = payload_size
    return result

class AsrWsClient:
    def __init__(self, cluster, **kwargs):
        self.cluster = cluster
        self.success_code = 1000
        self.nbest = int(kwargs.get("nbest", 1))
        self.appid = kwargs.get("appid", "")
        self.token = kwargs.get("token", "")
        self.ws_url = kwargs.get("ws_url", "wss://openspeech.bytedance.com/api/v2/asr")
        self.uid = kwargs.get("uid", "streaming_asr_demo")

        # workflow 内含 vad，可直接连麦传整流
        self.workflow = kwargs.get("workflow", "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate")
        self.show_language = kwargs.get("show_language", False)
        self.show_utterances = kwargs.get("show_utterances", True)
        self.result_type = kwargs.get("result_type", "full")

        # 采样设置 —— 麦克风走 raw PCM
        self.format = kwargs.get("format", "wav")   # 改成 "pcm" 更贴近实际
        self.rate = int(kwargs.get("sample_rate", 16000))
        self.bits = int(kwargs.get("bits", 16))
        self.channel = int(kwargs.get("channel", 1))
        self.language = kwargs.get("language", "zh-CN")
        self.codec = kwargs.get("codec", "raw")     # 关键
        self.auth_method = kwargs.get("auth_method", "token")
        self.secret = kwargs.get("secret", "access_secret")

        # 设备选择（可传入整数索引或名字；None 用默认输入设备）
        self.input_device = kwargs.get("input_device", None)

    def construct_request(self, reqid):
        return {
            'app': {
                'appid': self.appid,
                'cluster': self.cluster,
                'token': self.token,
            },
            'user': {
                'uid': self.uid
            },
            'request': {
                'reqid': reqid,
                'nbest': self.nbest,
                'workflow': self.workflow,
                'show_language': self.show_language,
                'show_utterances': self.show_utterances,
                'result_type': self.result_type,
                "sequence": 1
            },
            'audio': {
                'format': self.format,    # 'pcm'
                'rate': self.rate,        # 16000
                'language': self.language,
                'bits': self.bits,        # 16
                'channel': self.channel,  # 1
                'codec': self.codec,      # 'raw'（payload 是裸 PCM）
            }
        }

    def token_auth(self):
        # 某些线路需要标准 Bearer 头；如 401/403，请改回 f'Bearer; {self.token}' 的老写法
        return {'Authorization': f'Bearer; {self.token}'}

    def signature_auth(self, data_bytes):
        header_dicts = {'Custom': 'auth_custom'}
        url_parse = urlparse(self.ws_url)
        input_str = f'GET {url_parse.path} HTTP/1.1\nCustom\n'
        input_data = bytearray(input_str, 'utf-8') + data_bytes
        mac = base64.urlsafe_b64encode(hmac.new(self.secret.encode('utf-8'), input_data, digestmod=sha256).digest())
        header_dicts['Authorization'] = f'HMAC256; access_token="{self.token}"; mac="{mac.decode()}"; h="Custom"'
        return header_dicts

    def _open_ws(self, full_client_request_bytes: bytes):
        """返回 connect 对象（不 await！用于 async with）"""
        header = self.token_auth() if self.auth_method == "token" else self.signature_auth(full_client_request_bytes)
        return websockets.connect(
            self.ws_url,
            extra_headers=header,
            close_timeout=5,
            open_timeout=12,
            max_size=10_000_000,
        )

    async def mic_streaming(self, chunk_ms: int = 100, print_partial: bool = True):
        """开麦流式识别。按 chunk_ms（默认 100ms）从麦克风取帧并发送。按回车结束。"""
        # 打印/选择设备，避免采到“空设备”
        try:
            default_in, _ = sd.default.device
        except Exception:
            default_in = None
        devices = sd.query_devices()
        print(f"[mic] default input device index: {default_in}")
        if self.input_device is None:
            used_index = default_in if (default_in is not None and default_in >= 0) else None
            if used_index is None:
                # 找第一个有输入通道的设备
                for i, d in enumerate(devices):
                    if d.get("max_input_channels", 0) > 0:
                        used_index = i
                        break
            self.input_device = used_index

        name = (devices[self.input_device]['name'] if isinstance(self.input_device, int)
                else str(self.input_device))
        print(f"[mic] default input idx: {default_in}, using: {self.input_device} -> {name}")
        
        reqid = str(uuid.uuid4())
        request_params = self.construct_request(reqid)
        payload_bytes = gzip.compress(json.dumps(request_params).encode())

        full_client_request = bytearray(generate_full_default_header())
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        done_event = asyncio.Event()   # 只让 recv_task 接收；主协程等这个事件

        # 连接 WS（只此一个接收方：recv_task）
        async with self._open_ws(bytes(full_client_request)) as ws:
            # 1) 先发 Full Request
            await ws.send(full_client_request)
            res = await ws.recv()
            if isinstance(res, str):
                res = res.encode("utf-8")
            first = parse_response(res)
            print("<< first:", json.dumps(first, ensure_ascii=False))

            code = (first.get('payload_msg') or {}).get('code', self.success_code)
            if code != self.success_code:
                done_event.set()
                return first

            # 2) 音频生产者（麦克风）→ asyncio.Queue → 消费者（WS 发送）
            q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)

            frames_per_chunk = int(self.rate * chunk_ms / 1000)  # 16k * 0.1s = 1600
            bytes_per_frame = self.bits // 8 * self.channel       # 2 * 1 = 2
            bytes_per_chunk = frames_per_chunk * bytes_per_frame  # 3200 bytes

            def _callback(indata, frames, time, status):
                if status:
                    print(f"[mic] status: {status}")
                try:
                    q.put_nowait(bytes(indata))
                except asyncio.QueueFull:
                    pass  # 保持实时性，丢帧

            stream = sd.RawInputStream(
                device=self.input_device,
                samplerate=self.rate,
                blocksize=frames_per_chunk,
                dtype='int16',
                channels=self.channel,
                callback=_callback,
            )

            # 3) 后台接收任务（唯一 recv 方）：打印部分/最终结果，并在结束时 set 事件
            async def recv_task():
                try:
                    while True:
                        msg = await ws.recv()
                        if isinstance(msg, str):
                            msg = msg.encode("utf-8")
                        parsed = parse_response(msg)
                        pm = parsed.get("payload_msg")
                        if not pm:
                            continue

                        # 服务端错误（如 400）也结束
                        if isinstance(pm, dict) and pm.get("code") not in (None, 1000):
                            print("<< payload:", json.dumps(pm, ensure_ascii=False))
                            done_event.set()
                            return

                        if print_partial:
                            text = None
                            if isinstance(pm, dict):
                                utt = pm.get("utterances")
                                if isinstance(utt, list) and len(utt) > 0:
                                    u = utt[-1]
                                    text = u.get("text") or u.get("normalized_text") or u.get("transcript")
                                    is_final = u.get("is_final") or (u.get("type") in ("final", "sentence_end"))
                                    if text:
                                        print(("【FINAL】" if is_final else "【PART】"), text)
                                        # 收到明确 final 也可以结束
                                        if is_final:
                                            # 不强制立即结束，留给下一句；最终还是靠按回车
                                            pass
                                if not text and pm.get("result"):
                                    r = pm["result"]
                                    if isinstance(r, dict):
                                        text = r.get("text") or r.get("normalized_text")
                                        if text:
                                            print("【RESULT】", text)
                            if text is None:
                                # 常规 ACK（只有 code/sequence）就别刷屏了
                                if isinstance(pm, dict) and set(pm.keys()) <= {"addition","code","message","reqid","sequence"}:
                                    continue
                                try:
                                    print("<< payload:", json.dumps(pm, ensure_ascii=False))
                                except Exception:
                                    print("<< payload(raw):", pm)
                except websockets.ConnectionClosed:
                    done_event.set()
                    return

            recv_runner = asyncio.create_task(recv_task())

            # 4) 发送音频；回车结束
            async def wait_enter():
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, input, "\n[按回车键结束说话并等待最终结果] ")

            with stream:
                print(f"[mic] started: {self.rate} Hz, {self.bits} bit, {self.channel} ch, chunk={chunk_ms}ms")
                stop_future = asyncio.create_task(wait_enter())
                sending = True

                while sending:
                    done, _ = await asyncio.wait(
                        {asyncio.create_task(q.get()), stop_future},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if stop_future in done:
                        # 用户结束输入：把队列里的剩余帧发完后，发“最后一帧”
                        tail = bytearray()
                        while not q.empty():
                            try:
                                tail.extend(q.get_nowait())
                            except asyncio.QueueEmpty:
                                break
                        if tail:
                            payload_bytes = gzip.compress(bytes(tail))
                            pkt = bytearray(generate_audio_default_header())
                            pkt.extend((len(payload_bytes)).to_bytes(4, 'big'))
                            pkt.extend(payload_bytes)
                            await ws.send(pkt)

                        last_payload = gzip.compress(b'')
                        last_pkt = bytearray(generate_last_audio_default_header())
                        last_pkt.extend((len(last_payload)).to_bytes(4, 'big'))
                        last_pkt.extend(last_payload)
                        await ws.send(last_pkt)
                        sending = False
                        break

                    # 正常从队列取一帧并发送
                    task = list(done)[0]
                    chunk = task.result()
                    if not chunk:
                        continue
                    payload_bytes = gzip.compress(chunk)
                    pkt = bytearray(generate_audio_default_header())
                    pkt.extend((len(payload_bytes)).to_bytes(4, 'big'))
                    pkt.extend(payload_bytes)
                    await ws.send(pkt)

            # 5) 不再直接 ws.recv()，只等待 recv_task 处理完或超时
            try:
                await asyncio.wait_for(done_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

            recv_runner.cancel()
            return {"code": 0, "msg": "mic session finished"}

# ========== 入口 ==========

def run_mic():
    # 如需指定输入设备，传入 input_device=索引或名字；不指定会自动选一个可用输入设备
    client = AsrWsClient(
        cluster=cluster,
        appid=appid,
        token=token,
        language="zh-CN",
        sample_rate=16000,
        bits=16,
        channel=1,
        result_type="full",
        show_utterances=True,
        codec="raw",   # 开麦必须 raw
        format="pcm",
        # input_device=0,  # 可手动指定
    )
    asyncio.run(client.mic_streaming(chunk_ms=100, print_partial=True))

if __name__ == "__main__":
    run_mic()
