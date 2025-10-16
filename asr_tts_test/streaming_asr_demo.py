import asyncio, base64, gzip, hmac, json, os, uuid, wave, ssl, socket
from enum import Enum
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlparse

import websockets

# -------- 你的控制台信息（直写） --------
appid   = "8726984949"
token   = "cABD3Fc92li99s7i5vslzIvw6ZxlUad2"
cluster = "volcengine_streaming"   # 建议用这个
audio_path   = "tts.wav"
audio_format = "wav"                       # "wav" | "mp3"

# -------- 关闭代理（关键！） --------
for k in ("HTTPS_PROXY","https_proxy","HTTP_PROXY","http_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
# 可选：只对 openspeech 绕过代理
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
    # 解析服务端帧（与官方一致）
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

def read_wav_info(data: bytes):
    with BytesIO(data) as _f:
        wave_fp = wave.open(_f, 'rb')
        nch, sw, fr, nframes = wave_fp.getparams()[:4]
        wave_bytes = wave_fp.readframes(nframes)
    return nch, sw, fr, nframes, len(wave_bytes)

class AudioType(Enum):
    LOCAL = 1

class AsrWsClient:
    def __init__(self, audio_path, cluster, **kwargs):
        self.audio_path = audio_path
        self.cluster = cluster
        self.success_code = 1000
        self.seg_duration = int(kwargs.get("seg_duration", 15000))
        self.nbest = int(kwargs.get("nbest", 1))
        self.appid = kwargs.get("appid", "")
        self.token = kwargs.get("token", "")
        self.ws_url = kwargs.get("ws_url", "wss://openspeech.bytedance.com/api/v2/asr")
        self.uid = kwargs.get("uid", "streaming_asr_demo")
        self.workflow = kwargs.get("workflow", "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate")
        self.show_language = kwargs.get("show_language", False)
        self.show_utterances = kwargs.get("show_utterances", False)
        self.result_type = kwargs.get("result_type", "full")
        self.format = kwargs.get("format", "wav")
        self.rate = kwargs.get("sample_rate", 16000)
        self.language = kwargs.get("language", "zh-CN")
        self.bits = kwargs.get("bits", 16)
        self.channel = kwargs.get("channel", 1)
        # ✅ 关键：按实际输入设置 codec
        self.codec = kwargs.get("codec", "mp3" if self.format == "mp3" else "raw")
        self.audio_type = kwargs.get("audio_type", AudioType.LOCAL)
        self.secret = kwargs.get("secret", "access_secret")
        self.auth_method = kwargs.get("auth_method", "token")
        self.mp3_seg_size = int(kwargs.get("mp3_seg_size", 10000))

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
                'format': self.format,
                'rate': self.rate,
                'language': self.language,
                'bits': self.bits,
                'channel': self.channel,
                'codec': self.codec,   # ✅ 修正
            }
        }

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        data_len, offset = len(data), 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        else:
            yield data[offset: data_len], True

    def token_auth(self):
        return {'Authorization': f'Bearer; {self.token}'}
        # 若这条线要求 Bearer：
        # return {'Authorization': f'Bearer {self.token}'}

    def signature_auth(self, data):
        # 如果你要走签名鉴权，这里保持官方写法即可
        header_dicts = {'Custom': 'auth_custom'}
        url_parse = urlparse(self.ws_url)
        input_str = f'GET {url_parse.path} HTTP/1.1\nCustom\n'
        input_data = bytearray(input_str, 'utf-8') + data
        mac = base64.urlsafe_b64encode(hmac.new(self.secret.encode('utf-8'), input_data, digestmod=sha256).digest())
        header_dicts['Authorization'] = f'HMAC256; access_token="{self.token}"; mac="{mac.decode()}"; h="Custom"'
        return header_dicts

    async def segment_data_processor(self, wav_or_mp3_data: bytes, segment_size: int):
        reqid = str(uuid.uuid4())
        request_params = self.construct_request(reqid)
        payload_bytes = gzip.compress(json.dumps(request_params).encode())

        full_client_request = bytearray(generate_full_default_header())
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        # 选择鉴权头
        if self.auth_method == "token":
            header = self.token_auth()
        else:
            header = self.signature_auth(full_client_request)

        # 强制使用 websockets 直连（不走代理）
        # 如需强制 IPv4，可用：host = socket.getaddrinfo("openspeech.bytedance.com", 443, socket.AF_INET)[0][4][0]
        uri = self.ws_url

        # 适当延长超时；max_size 给大些
        async with websockets.connect(
            uri,
            extra_headers=header,
            close_timeout=5,
            open_timeout=12,
            max_size=10_000_000,
        ) as ws:
            # 发送 Full Request
            await ws.send(full_client_request)
            res = await ws.recv()
            result = parse_response(res)
            # 调试打印
            print("<< first:", result)

            # 非 1000（success）直接返回
            code = (result.get('payload_msg') or {}).get('code', self.success_code)
            if code != self.success_code:
                return result

            # 逐段发送音频
            for seq, (chunk, last) in enumerate(self.slice_data(wav_or_mp3_data, segment_size), 1):
                payload_bytes = gzip.compress(chunk)
                hdr = generate_last_audio_default_header() if last else generate_audio_default_header()
                audio_only_request = bytearray(hdr)
                audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                audio_only_request.extend(payload_bytes)

                await ws.send(audio_only_request)
                res = await ws.recv()
                result = parse_response(res)
                print(f"<< seq={seq}:", result)
                if 'payload_msg' in result and result['payload_msg'].get('code') != self.success_code:
                    return result

        return result

    async def execute(self):
        data = open(self.audio_path, "rb").read()
        if self.format == "mp3":
            segment_size = self.mp3_seg_size  # 10KB 左右一段
            return await self.segment_data_processor(data, segment_size)
        if self.format != "wav":
            raise Exception("format should be wav or mp3")
        nch, sw, fr, nframes, wav_len = read_wav_info(data)
        size_per_sec = nch * sw * fr
        segment_size = int(size_per_sec * self.seg_duration / 1000)
        return await self.segment_data_processor(data, segment_size)

def execute_one(audio_item, cluster, **kwargs):
    asr = AsrWsClient(audio_path=audio_item['path'], cluster=cluster, **kwargs)
    return asyncio.run(asr.execute())

def test_one():
    result = execute_one(
        {"id": 1, "path": audio_path},
        cluster=cluster,
        appid=appid,
        token=token,
        format=audio_format,
        # codec 会根据 format 自动设置；也可以手动传 codec="mp3"
    )
    print("== final result ==")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    # 建议固定 websockets 版本，避免 API 差异：
    # pip install "websockets>=11,<12"
    test_one()
