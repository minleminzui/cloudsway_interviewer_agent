# Interviewer Agent MVP

## 功能概览

- **会话管理与提纲生成**：后端提供 `/v1/sessions` 创建接口，自动生成三级采访提纲并初始化状态机。
- **实时事件通道**：`/ws/asr`、`/ws/agent`、`/ws/tts` 三路 WebSocket，TTS 通道已接入火山引擎 OpenSpeech v3 单向接口，并新增 `tts_ready` 握手及打断取消机制。
- **采访策略状态机**：`Opening → Exploration → DeepDive → Clarify → Closing` 的分阶段策略，包含模糊回答检测、待澄清清单管理以及下一问决策。
- **信息抽取与纪要导出**：规则提取数字/观点/待澄清要点，可导出 DOCX 与 XLSX 纪要。
- **前端控制台**：展示提纲覆盖率、实时字幕、待澄清列表、下一问提示，并可通过文本框模拟受访者回答。

## 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── config.py            # Pydantic Settings 配置
│   │   ├── database.py          # Async SQLAlchemy 引擎与初始化
│   │   ├── main.py              # FastAPI 入口，注册 REST/WS 路由
│   │   ├── models.py            # ORM：sessions、turns、notes
│   │   ├── core/                # ws_tts_manager、tts_client、llm 客户端
│   │   ├── routers/             # http_api、ws_asr、ws_agent、ws_tts、demo_tts
│   │   └── services/            # outline、state_machine、agent、fake_tts 等逻辑
│   └── requirements.txt         # 后端依赖
├── frontend/
│   ├── src/
│   │   ├── components/          # React UI 组件
│   │   ├── store/               # Zustand 会话状态
│   │   ├── api/                 # WebSocket 客户端封装
│   │   ├── audio/               # MediaSource 播放器
│   │   ├── hooks/               # 会话初始化、连接管理
│   │   ├── pages/               # 控制台与 TTS demo 页面
│   │   └── App.tsx              # 路由入口
│   ├── package.json             # 前端依赖与脚本
│   └── vite.config.ts           # Vite 配置
├── docs/auto_interview_mvp.md   # 原始产品实施细化方案
├── .env.example                 # 后端环境变量示例
└── README.md
```

## 快速开始

### 准备环境

- Python 3.11+
- Node.js 20+
- 推荐在项目根目录复制 `.env.example` 为 `.env` 并按需修改。

若需启用 Ark LLM 生成提纲与策略，可在 `.env` 写入变量，或在启动终端先执行一次：

```bash
export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export ARK_API_KEY="<你的 Ark API Key>"
export ARK_MODEL_ID="<默认聊天模型 ID>"
# 可选：分别为提纲与策略指定模型
export ARK_OUTLINE_MODEL_ID="<提纲模型 ID>"
export ARK_POLICY_MODEL_ID="<策略模型 ID>"
```

语音服务也需要在当前终端导出凭据：

```bash
export VOLC_TTS_BASE_URL="https://openspeech.bytedance.com/api/v3/tts/unidirectional"
export VOLC_TTS_API_KEY="<你的 TTS API Key>"
export VOLC_TTS_RESOURCE_ID="volc.service_type.10029"
export VOLC_TTS_SPEAKER="zh_male_beijingxiaoye_emo_v2_mars_bigtts"
export VOLC_TTS_SAMPLE_RATE="24000"
export VOLC_TTS_FORMAT="mp3"

export VOLS_APPID="<你的火山 ASR AppId>"
export VOLS_TOKEN="<你的火山 ASR Token>"
export VOLS_CLUSTER="volcengine_streaming"
export VOLS_WS_URL="wss://openspeech.bytedance.com/api/v2/asr"
```

将这些命令写入 `.env` 文件也可以，FastAPI 会在启动时自动加载。

### 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 首次运行请确保已经在该终端执行过上面的 export 命令
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可访问：

- REST: `http://localhost:8000/v1/sessions`
- WebSocket: `ws://localhost:8000/ws/{agent|asr|tts}`
- Demo API: `POST http://localhost:8000/v1/tts/demo/start?session=...`

### 启动前端

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

浏览器访问 `http://localhost:5173`，系统将自动创建采访会话、拉取提纲并开始播报第一轮问题。可在底部输入框填写回答，观察右侧字幕与下一问动态更新。

## 后端接口速览

| 类型 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/sessions` | 创建采访会话，返回 session 基础信息与三级提纲 |
| GET  | `/v1/sessions` | 列出已有会话 |
| POST | `/v1/plan` | 基于主题生成三级采访提纲 |
| POST | `/v1/export` | 根据 `session_id` 导出 DOCX / XLSX 纪要 |
| WS   | `/ws/asr` | 接收浏览器发送的音频/文本，返回转写事件（MVP 内置模拟） |
| WS   | `/ws/agent` | 采访策略通道，接收受访者文本并下发下一轮提问、笔记 |
| WS   | `/ws/tts` | 握手返回 `tts_ready`，随后推送 OpenSpeech 音频分片；支持取消 |
| POST | `/v1/tts/demo/start` | 触发 demo WebM 播放，验证流式播放/打断 |
| POST | `/v1/tts/demo/stop` | 停止当前 demo 播放 |

> 真实接入外部 ASR / TTS / LLM 时，只需在 `services` 模块替换对应客户端实现，维持接口契约即可。

## 关键模块说明

- `services/state_machine.py`：维护覆盖率、待澄清列表与阶段切换逻辑，保证采访流程不会偏离主题。
- `services/agent.py`：协调状态机、信息抽取与数据库持久化，并累计历史澄清提示避免被后续回答覆盖。
- `services/extraction.py`：规则化提取数字、模糊回答等关键信息，并写入 `notes` 表。
- `core/ws_tts_manager.py` 与 `core/tts_client.py`：负责多端连接管理、`tts_ready` 握手、取消逻辑及火山 OpenSpeech HTTP 调用。
- `routers/ws_*`：提供最小可运行的 WS 协议实现，方便后续对接真实供应商 API。
- 前端 `hooks/useInterviewClients.ts`：集中管理三路 WebSocket 连接并提供 `sendUserUtterance` API；`audio/TtsPlayer.ts` 基于 MediaSource 播放流式音频。

## 下一步集成建议

1. **替换语音模块**：在 `ws_asr` / `ws_tts` 中接入真实流式 ASR、TTS 服务，沿用现有推送协议即可。
2. **连接大模型策略器**：在 `services/agent.py` 内调用外部 LLM，根据会话上下文生成更丰富的追问。
3. **增强抽取准确率**：扩展 `services/extraction.py`，引入 JSON Schema + LLM 校验，或使用正则/词典组合提升精度。
4. **观测与回放**：补充 Prometheus 指标、S3/MinIO 音频上传与回放页面，支撑正式部署。

### 豆包 TTS / 方舟 LLM 配置

在根目录 `.env` 中补充以下变量（请勿提交真实密钥）：

```
VOLC_TTS_BASE_URL=https://openspeech.bytedance.com/api/v3/tts/unidirectional
VOLC_TTS_API_KEY=__PUT_YOUR_KEY__
VOLC_TTS_RESOURCE_ID=volc.service_type.10029
VOLC_TTS_SPEAKER=zh_male_beijingxiaoye_emo_v2_mars_bigtts
VOLC_TTS_SAMPLE_RATE=24000
VOLC_TTS_FORMAT=mp3

ARK_BASE_URL=https://ark.example.com/api/v3
ARK_API_KEY=__PUT_YOUR_ARK_KEY__
ARK_MODEL_ID=ep-XXXXXXXXXXXX
```

`backend/config.example.yaml` 给出了通过环境变量切换 provider 的示例。若需本地验证 `/v1/tts/demo/start`，可使用下列命令准备示例音频：

```bash
mkdir -p assets
ffmpeg -y -i sample.mp3 -c:a libopus -b:a 64k -frame_duration 20 -application voip assets/demo_tts.webm
```

随后访问前端 `/tts-demo` 页面即可触发 demo 播放并测试 barge-in 打断。

如需更细颗粒的迭代拆解，可参考 `docs/auto_interview_mvp.md` 中的实施细化方案。

## 提示词设置
初始化采访时使用的默认“背景/细节/结论”提纲和示例问题定义在 `backend/app/services/outline.py`的 DEFAULT_STAGES 常量中；直接修改那里就能调整默认的采访背景与种子问题。

如果启用了 Ark 模型，提纲生成时发送给模型的系统提示词也在同一文件里（messages 列表中的 "你是采访提纲助手..." 等内容）；你可以在那里定制模型接收的上下文，以改变自动生成的初始提纲风格。

另外，正式对话阶段的策略提示词位于 backend/app/services/policy.py 的 system_prompt 中，它控制后续问题的生成逻辑；如需调整采访策略，可在这里修改提示词或传入的 payload 信息。