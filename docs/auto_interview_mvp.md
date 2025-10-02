# 自动采访机器人 MVP 实施方案

## 1. 目标概述

面向“采访机器人训练系统控制台”打造一个自动采访模式 MVP，实现“语音提问 → 语音回答 → 文本记录 → 实时转写”的闭环，并满足行业采访场景对专业提纲、动态追问、话题引导、信息结构化记录等需求。方案兼顾前端采集播报、后端编排调度、算法策略与数据管理，便于后续扩展到半自动/手动模式。

## 2. 关键技术栈与模型

| 能力 | 技术/服务 | 说明 |
| --- | --- | --- |
| 前端 | React 18 + TypeScript, Zustand, WebRTC, MediaRecorder, AudioWorklet, @ricky0123/vad-web | 支持流式采集、VAD、barge-in、实时字幕与控制面板 |
| 后端 | FastAPI + uvicorn + asyncio, aiohttp, tenacity, SQLAlchemy(Async), asyncpg, aioboto3, orjson | 实现 WS 通道、状态机、第三方 API 转发、数据持久化 |
| LLM | 方舟 Ark `ep-*` 接入点（≥30B 参数，如 Qwen2.5-32B-Instruct/DeepSeek-V3） | 通过 OpenAI 兼容接口完成提纲生成、策略决策、信息抽取 |
| ASR | 自有流式 ASR：`4o-mini-transcribe` 或 FunASR Paraformer/Whisper-v3-turbo | 需提供 2s 内延迟，返回 partial/final 结果 |
| TTS | 豆包 OpenSpeech TTS（流式或单向接口） | 支持≥3种音色、24000Hz 采样，后端切片推送实现 barge-in |
| 向量/RAG | `bge-m3` 或 `text-embedding-3-large` | 可选：行业资料检索、提纲覆盖率计算 |
| 数据库 | PostgreSQL（元数据、提纲、转写、纪要） | 结构化记录与检索 |
| 对象存储 | MinIO/S3 | 存储原始音频、导出文件 |

## 3. 系统整体架构

```
前端(React UI)
  ├─ WebRTC/VAD → /ws/asr → 后端 ASR 代理 → 第三方 ASR
  ├─ TTS 播放器 ← /ws/tts ← 后端 TTS 代理 ← 豆包 OpenSpeech
  └─ 控制/状态 ←→ /ws/agent ←→ 采访编排器(State Machine + Policy)
                                     ├─ LLM (Ark Gateway)
                                     ├─ 信息抽取器(JSON-Schema + 规则)
                                     └─ 可选 RAG (PGVector/Elastic)
                 数据持久化：Postgres + MinIO/S3 + 导出(Word/Excel)
```

核心分层：

1. **前端层**：负责低时延采集、实时字幕、提纲/澄清列表可视化、模式切换与人工介入。
2. **会话层**（后端 WS）：维护 ASR、Agent、TTS 三通道与事件总线，实现 barge-in、回声抑制、播报控制。
3. **策略层**：基于状态机与 LLM 决策（提问、追问、话题回归、结束），同步更新提纲覆盖与澄清项。
4. **知识层**：预置行业知识库/RAG，支撑专业术语识别、背景补充。
5. **数据层**：结构化存储对话、提纲、关键信息，支持检索与导出。

## 4. 数据流与协议

### 4.1 WebSocket 通道

* `/ws/asr`：浏览器以 `audio/webm;codecs=opus` 40ms 分片上行；后端转发至 ASR；下行 partial/final 字幕事件 `{type, text, ts, seq}`。
* `/ws/agent`：
  * 上行：`user_turn`（final 文本）、`barge_in`、`control`（pause/resume/stop）、`manual_question`。
  * 下行：`policy`（ask/followup/regress/close）、`bot_reply_delta`、`note_update`、`coverage_update`、`status`。
* `/ws/tts`：后端将豆包 TTS 音频切片推送 `audio_chunk` 二进制；结束包 `tts_end`；支持 `cancel` 指令应对 barge-in。

### 4.2 HTTP API

* `POST /v1/plan`：输入主题、被访者、可选背景资料；输出三级提纲。
* `POST /v1/export/{docx|excel}`：生成采访纪要、Q&A、行动项。
* `GET /v1/sessions`、`GET /v1/sessions/{id}`：检索历史采访、拉取结构化记录。
* `POST /v1/sessions/{id}/notes`：落人工补充信息。

### 4.3 事件总线

`apps/backend/core/bus.py`：基于 `asyncio.Queue`（单实例）或 Redis Streams（分布式）实现会话内广播，供 ASR/TTS/Agent/前端共享状态。

## 5. 前端实现要点

1. **音频采集**：`navigator.mediaDevices.getUserMedia` + `MediaRecorder` 40ms 分片；启用 `echoCancellation`、`noiseSuppression`、`autoGainControl`；并行 `@ricky0123/vad-web` 做 VAD。
2. **barge-in**：检测语音概率持续 > 阈值 200–300ms 时：
   * 发送 `{type:"barge_in"}` 给 `/ws/agent`；
   * 暂停 TTS 播放器、标记 `bargeIn` 状态；
   * 等待 ASR final 后恢复。
3. **字幕渲染**：partial 灰色、final 黑色；final 触发转写面板滚动、写入结构化数据。
4. **提纲视图**：左侧展示三级提纲，节点显示覆盖率、状态色（未问/已问/需澄清）。
5. **待澄清列表**：来自后端 `note_update` 中低置信度或缺失槽位，支持人工点击“标记完成”。
6. **模式控制**：自动/半自动/手动；半自动允许人工挑选下一问；手动模式 UI 直接发送 `manual_question`。
7. **TTS 播放器**：`MediaSource` 或 `AudioWorklet` 实现流式播放，支持取消/暂停；跟踪 TTS 文本窗口用于 echo mask。
8. **错误与重连**：`reconnecting-websocket`；显式状态提示（ASR/TTS/LLM 正常、降级、重试）。

## 6. 后端服务设计

### 6.1 目录结构

```
apps/backend/
  app.py
  core/
    config.py
    bus.py
    models.py
    storage.py
    llm.py
    asr_client.py
    tts_client.py
  services/
    agent_orchestrator.py
    outline.py
    extract_notes.py
    exporters/
      excel.py
      docx.py
  routes/
    ws_asr.py
    ws_agent.py
    ws_tts.py
    http_api.py
```

### 6.2 功能模块

* **`asr_client.py`**：管理与流式 ASR 的半双工连接；封装写入/读取协程；支持重试、超时、回声文本遮挡。
* **`tts_client.py`**：调用豆包 OpenSpeech，收取整段音频后切片推送；维护 TTS 文本缓存，支持取消。
* **`llm.py`**：基于方舟 Ark OpenAI 兼容接口，提供 `chat_stream`、`completion_json` 等方法；支持 temperature/top_p 配置。
* **`agent_orchestrator.py`**：
  * 会话状态机（Opening → Exploration → DeepDive → Clarify → Closing）；
  * 调用 `policy_decide`（LLM）产生行动；
  * 触发 `tts_client.stream_and_broadcast` 播报问题；
  * 同步信息抽取、提纲覆盖率更新。
* **`extract_notes.py`**：LLM 生成 JSON（按 Schema），使用 `pydantic` 校验；数值/日期后处理；更新待澄清项。
* **`outline.py`**：提纲生成、覆盖率计算；使用句向量余弦相似度≥0.6 视为覆盖。
* **`storage.py`**：Postgres + SQLAlchemy（异步）；MinIO 通过 `aioboto3` 上传音频；提供检索接口。
* **`exporters`**：Excel 使用 `XlsxWriter`；Word 使用 `python-docx` 模板。

### 6.3 可靠性

* `tenacity` 指数退避重试；LLM 超时 fallback（简短问题模板）。
* 会话心跳（30s）+ 超时自动结束。
* 关键事件（barge-in、API 错误）写入审计日志。

## 7. 算法与策略

### 7.1 提纲生成

Prompt 示例：
```
请基于以下采访主题与背景资料，生成三级递进采访提纲，格式 JSON：
[
  {"stage":"背景", "questions":[...]},
  {"stage":"细节", "questions":[...]},
  {"stage":"结论", "questions":[...]}
]
每个问题不超过 18 字，覆盖关键维度：背景、细节、指标、风险、行动。
```
输出后做去重、长度截断、敏感词检测。

### 7.2 状态机策略

* **Opening**：寒暄、确认议程、提出首问。
* **Exploration**：遍历提纲一级问题，记录覆盖情况。
* **DeepDive**：针对含关键信息的回答追问“原因/方法/指标/计划”。
* **Clarify**：清理 `pending_slots`（缺数字/日期/责任人）。
* **Closing**：总结要点、确认行动项、约定后续。

### 7.3 动态追问与话题回归

* 模糊词表：可能、差不多、之后、暂时、再说、不一定等；出现则触发 `followup`。
* 主题偏移检测：最近 3 轮问答与提纲主题的句向量相似度 < 0.65，则生成引导性问题；LLM Prompt 限制“回到主题 X”。
* 结束条件：覆盖率 ≥80% 或连续 2 轮无新增事实。

### 7.4 信息抽取

Schema：
```
{
  "people":[{"name":"string","role":"string?"}],
  "time":"string?",
  "facts":[{"claim":"string","evidence":"string?","confidence":0.0}],
  "numbers":[{"name":"string","value":0,"unit":"string"}],
  "actions":[{"who":"string","todo":"string","due":"string?"}],
  "open_questions":["string"]
}
```

低置信度(`confidence <0.6`) 自动加入待澄清；金额/百分比/中文数字转换通过规则处理。

### 7.5 回声文本屏蔽

维护最近 10–15 秒 TTS 文本窗口；ASR final 到来时计算与窗口句相似度（`rapidfuzz.partial_ratio` ≥90%）则视为回声，不进入策略器。

## 8. 数据库与存储设计

### 8.1 PostgreSQL 表

* `sessions(id, subject, interviewer, interviewee, status, created_at, updated_at)`
* `turns(id, session_id, speaker, text, start_ms, end_ms, action, confidence)`
* `notes(id, session_id, payload_jsonb, version, created_at)`
* `outline(id, session_id, structure_jsonb, coverage_jsonb)`
* `pending_slots(id, session_id, slot_type, description, status)`
* `exports(id, session_id, type, url, created_at)`

### 8.2 对象存储

* 音频录制（全程 + 回答切片）
* 导出文件（Word/Excel）
* 可选：截图、情绪分析帧等

## 9. 部署与配置

* Docker Compose：`frontend`、`backend`、`pg`、`redis`（可选）、`minio`、`nginx`、`llm-gateway`（方舟代理）、`asr-proxy`、`tts-proxy`。
* `.env` 关键变量：
  * `ASR_BASE_URL`、`ASR_API_KEY`
  * `VOLC_TTS_BASE_URL`、`VOLC_TTS_API_KEY`、`VOLC_TTS_RESOURCE_ID`
  * `ARK_BASE_URL`、`ARK_API_KEY`、`ARK_MODEL_ID`
  * `PG_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`
* 日志：`structlog` + ELK/ClickHouse 可选；音频加密存储（MinIO Server-Side Encryption）；HTTPS 终端加密。

## 10. 实施里程碑

1. **第 1 周：基础骨架**
   * 前端：WS 客户端、音频采集、字幕面板雏形。
   * 后端：FastAPI WS、ASR/TTS 代理打通（空回调）。
2. **第 2 周：策略与提纲**
   * 对接方舟 LLM，完成提纲生成 API、策略器基础问答循环。
   * 初版状态机（Opening/Exploration/Closing）。
3. **第 3 周：追问与纪要**
   * 动态追问、话题回归、信息抽取、待澄清列表。
   * PostgreSQL/MinIO 存储，转写与纪要导出。
4. **第 4 周：优化与验收**
   * barge-in、回声掩码、TTS 中断控制。
   * 指标自测（ASR 延迟、提纲覆盖率、追问成功率）。
   * 安全与部署文档。

## 11. 验收指标映射

| 需求 | 对应方案 |
| --- | --- |
| 多模态闭环 | WebRTC + ASR/TTS WS + Agent 状态机 |
| 专业采访逻辑 | 三级提纲、状态机 + LLM 策略、追问/回归规则 |
| 领域适配 | 指定知识库/RAG，术语词表，行业模板 |
| 实时记录 | 信息抽取器 + Postgres Notes + 待澄清列表 |
| 数据导出 | Excel/Word 导出模块 |
| 硬件接口 | 前端支持 HDMI 输出、TTS/麦克风参数；后端无硬件锁定 |
| 安全存储 | 数据库加密、MinIO 存储、API Key 管理 |
| API 扩展 | RESTful + WebSocket，留有 webhook/SDK 入口 |

---

该方案确保 MVP 在 4 周内可交付，并为后续功能（情感分析、视觉融合、半自动控制台等）预留扩展空间。
