curl -L -X POST 'https://openspeech.bytedance.com/api/v3/tts/unidirectional' \       
-H 'x-api-key: d77c97de-f0c3-4285-945b-8ec17fdfd76a' \
-H 'X-Api-Resource-Id: volc.service_type.10029' \
-H 'Connection: keep-alive' \
-H 'Content-Type: application/json' \
-d '{
    "req_params": {
        "text": "这里是豆包语音合成测试。我现在说两句话，确认你能听到声音。",
        "speaker": "zh_male_beijingxiaoye_emo_v2_mars_bigtts",
        "additions": "{\"disable_markdown_filter\":true,\"enable_language_detector\":true,\"enable_latex_tn\":true,\"disable_default_bit_rate\":true,\"max_length_to_filter_parenthesis\":0,\"cache_config\":{\"text_type\":1,\"use_cache\":true}}",
        "audio_params": {
            "format": "mp3",
            "sample_rate": 24000
        }
    }
}' > tts.raw.json

jq -rn 'inputs|select(.data|type=="string")|.data' tts.raw.json | base64 -D > tts.mp3