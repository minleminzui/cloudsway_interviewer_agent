# Interviewer Agent MVP

This repository contains a runnable minimum viable product of the multi模态采访机器人. It ships a FastAPI backend with WebSocket channels for ASR、Agent 决策、TTS，并提供结构化纪要导出，同时配套一个 React + Vite 控制台用于演示「自动提问 → 受访者回答 → 实时记录 → 下一轮追问」的闭环。

## 功能概览

- **会话管理与提纲生成**：后端提供 `/v1/sessions` 创建接口，自动生成三级采访提纲并初始化状态机。
- **实时事件通道**：`/ws/asr`、`/ws/agent`、`/ws/tts` 三路 WebSocket 在 MVP 中使用内置模拟器完成文本转写、策略推理与音频合成，接口签名与正式对接保持一致。
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
│   │   ├── routers/             # http_api、ws_asr、ws_agent、ws_tts
│   │   └── services/            # outline、state_machine、agent、tts 等逻辑
│   └── requirements.txt         # 后端依赖
├── frontend/
│   ├── src/
│   │   ├── components/          # React UI 组件
│   │   ├── store/               # Zustand 会话状态
│   │   ├── api/                 # WebSocket 客户端封装
│   │   ├── hooks/               # 会话初始化、连接管理
│   │   └── App.tsx              # 控制台布局
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

### 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可访问：

- REST: `http://localhost:8000/v1/sessions`
- WebSocket: `ws://localhost:8000/ws/{agent|asr|tts}`

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
| WS   | `/ws/tts` | 将下一问合成为 16 kHz PCM 并推送给前端播放 |

> 真实接入外部 ASR / TTS / LLM 时，只需在 `services` 模块替换对应客户端实现，维持接口契约即可。

## 关键模块说明

- `services/state_machine.py`：维护覆盖率、待澄清列表与阶段切换逻辑，保证采访流程不会偏离主题。
- `services/agent.py`：协调状态机、信息抽取与数据库持久化，返回统一的 `AgentDecision`。
- `services/extraction.py`：规则化提取数字、模糊回答等关键信息，并写入 `notes` 表。
- `routers/ws_*`：提供最小可运行的 WS 协议实现，方便后续对接真实供应商 API。
- 前端 `hooks/useInterviewClients.ts`：集中管理三路 WebSocket 连接并提供 `sendUserUtterance` API。

## 下一步集成建议

1. **替换语音模块**：在 `ws_asr` / `ws_tts` 中接入真实流式 ASR、TTS 服务，沿用现有推送协议即可。
2. **连接大模型策略器**：在 `services/agent.py` 内调用外部 LLM，根据会话上下文生成更丰富的追问。
3. **增强抽取准确率**：扩展 `services/extraction.py`，引入 JSON Schema + LLM 校验，或使用正则/词典组合提升精度。
4. **观测与回放**：补充 Prometheus 指标、S3/MinIO 音频上传与回放页面，支撑正式部署。

如需更细颗粒的迭代拆解，可参考 `docs/auto_interview_mvp.md` 中的实施细化方案。