# Interviewer Agent System Technical Plan

## 1. Overview
This document describes a feasible software plan for delivering the multi-modal interviewing agent outlined in the product brief. It maps concrete technologies, models, and service integrations to the seven-day implementation schedule (D1–D7) covering the backend (BE) and frontend (FE) responsibilities. In addition to the architecture narrative, the repository now contains runnable skeleton services and UI code that implement the day-one deliverables (mocked ASR/LLM/TTS pipeline, database tables, Docker Compose orchestration).

## 2. High-Level Architecture
- **Frontend (FE)**: React + Vite application styled with Tailwind CSS. WebRTC captures audio and video, while WebSockets deliver ASR, LLM, and TTS events. IndexedDB caches session state for reconnect scenarios.
- **Backend (BE)**: Monorepo orchestrating microservices via Docker Compose.
  - **Gateway Service** (Node.js/TypeScript + Fastify): Terminates WS/HTTP, handles auth (JWT), rate limiting, retries/backpressure, and routes to vendor APIs.
  - **Session Service** (Python FastAPI): Persists sessions/turns/notes/exports in PostgreSQL, exposes REST endpoints and WebSocket pub/sub (Redis Streams) for event fan-out.
  - **Observability Stack**: Prometheus + Grafana for metrics (p95 latency), Loki for logs, Tempo for tracing.
- **Data Stores**: PostgreSQL for structured data, Redis Streams for real-time event bus, MinIO/S3 for binary artifacts (audio segments, exports), optional Milvus/FAISS for embedding search if RAG is required later.

## 3. External AI Services & Models
| Capability | Service / Model | Notes |
|------------|-----------------|-------|
| Streaming ASR | iFlytek Spark, SenseVoice-Live, or Whisper-large-v3 via FasterWhisper server (GPU) | Supports Mandarin (98% accuracy) and accented Mandarin/English (≥93%). Latency target <1s for final transcripts. |
| Voice Activity Detection | WebRTC VAD + Mozilla WebRTC VAD or Silero VAD in-browser worker | Client-side detection for endpointing and silence reporting. |
| LLM (Interview Logic) | 34B parameter fine-tuned model such as Qwen2-32B-Instruct or Llama-3-33B-Instruct hosted via API | Context window ≥8k tokens, supports tool-use prompting for state machine decisions. |
| TTS | Microsoft Edge Neural Voices, Azure Neural TTS, or local CosyVoice2 streaming TTS | Provides ≥3 timbres, delivers <0.8s first audio packet. |
| Information Extraction | Same LLM with JSON schema enforcement or dedicated extraction model (e.g., Qwen2-32B JSON mode) | Validated with Pydantic rules for numeric/date normalization. |
| Face & Emotion Analysis (optional) | InsightFace + pyannote.audio | Supplies participant metadata when video is enabled. |

## 4. Message Protocol & State Machine
- **Event Envelope**: `{ type, event, sessionId, timestamp, payload }`. Types include `asr.partial`, `asr.final`, `llm.plan`, `llm.reply`, `tts.chunk`, `system.metric`, etc.
- **Interview State Machine**: `Warmup → Opening → Exploration → DeepDive → Clarify → Closing`. Each transition triggered by coverage percentage, slot fill status, or operator override.
- **Backpressure**: Gateway buffers and drops oldest non-essential partials when client is slow; heartbeats every 5s to detect disconnects.

## 5. Data Schema
PostgreSQL tables:
- `sessions(id, topic, interviewer, interviewee, started_at, status, metadata)`
- `turns(id, session_id, speaker, transcript, audio_url, state_stage, llm_action, created_at)`
- `notes(id, session_id, category, content, confidence, requires_clarification, created_at)`
- `exports(id, session_id, format, path, generated_at)`

Redis Stream channels:
- `session:{id}:events` for ASR/LLM/TTS events.
- `metrics:latency` for observability.

## 6. Deliverables by Day
### D1 – Skeleton & Mock Loop
- Monorepo (pnpm workspaces or Nx) with Docker Compose orchestrating gateway, session service, postgres, redis.
- `.env.example` enumerating upstream API keys and endpoints.
- FE mocks ASR/LLM/TTS via WebSocket simulation; subtitles render mock stream; TTS player uses HLS.js placeholder.
- Smoke test with mock pipeline.

### D2 – Real-Time Media Pipeline
- Integrate WebRTC audio capture, send 20–40ms Opus frames to `/ws/asr`.
- Gateway streams to ASR provider, relays partial/final transcripts back.
- TTS proxy streams audio chunks (pre-signed URLs or byte streams) to FE; playback via MediaSource Extensions.
- FE handles reconnection using session tokens; metrics panel shows counts.

### D3 – Interview Agent Logic
- Implement state machine service with prompt templates per stage.
- LLM-generated three-level outline stored as JSON (`sections -> questions -> followups`).
- Dynamic follow-up triggered on fuzzy markers (`可能`, `大概`, `不确定` etc.) using regex + semantic similarity (Sentence-BERT: `text2vec-large-chinese` hosted locally).
- Topic regression triggered when last 3 utterances cosine similarity < threshold against outline nodes.
- FE panel visualizes outline, coverage progress, pending clarifications.

### D4 – Structured Extraction & Export
- LLM extraction via JSON schema prompts; validate with Pydantic rules and regex for amounts/dates/percentages.
- Generate Excel using `openpyxl` template; DOCX via `python-docx` with merge fields.
- Notes UI allows inline correction and sends PATCH to `/v1/notes/update`.
- Metrics exported to Prometheus (ASR final p95, LLM first-token, TTS first-byte).

### D5 – Resilience & UX Polish
- Implement retry policies with exponential backoff; degrade to short responses if LLM >5s.
- FE reconnect continues same session using `sessionId` cookie/header.
- Generate closing summary (`actions`, `risks`, `next_steps`).
- Keyboard shortcuts for operators, coverage visualization enhancements.

### D6 – Load Testing & Release
- Build automated regression script replaying sample audio to validate extraction accuracy (≥92%).
- Concurrency tests (2 simultaneous sessions) using Locust or k6.
- Produce Docker images, health checks, and release notes.
- FE optimizes long-session rendering (virtualized list) and theme variants.

### D7 – Buffer & Documentation
- Final bug fixes, RBAC (viewer/editor roles) via JWT claims.
- Audit logging stored in PostgreSQL (`audit_logs`).
- Onboarding guide with 3-step tutorial and demo script.
- Record demo and archive sample sessions.

## 7. Security & Compliance
- Encrypt data at rest (PostgreSQL TDE or disk encryption) and in transit (HTTPS/WSS with TLS).
- API keys stored in Vault/Secrets Manager; rotate via CI pipeline.
- Access control enforced at gateway and session service; audit log every export/download.

## 8. Deployment Considerations
- Target OS: Ubuntu 22.04 LTS or Windows Server 2022 with WSL2.
- Hardware per spec: i7-13620H, 32GB RAM, 1TB SSD; GPU optional for local ASR/TTS acceleration.
- Support offline mode by hosting open models (Whisper, CosyVoice2, Qwen2) when internet constrained.

## 9. Risk Mitigation
- **Latency**: Pre-warm LLM sessions, use streaming responses, maintain connection pools.
- **Accuracy**: Ensemble fuzzy detection with keywords + semantic scoring; allow operator overrides.
- **Reliability**: Heartbeats, automatic failover to backup ASR/TTS provider, and circuit breaker patterns.

## 10. Next Steps
- Confirm vendor API credentials and quota.
- Prepare sample interview datasets for testing extraction metrics.
- Define success metrics dashboards in Grafana before D2 to track latency goals.

## 11. Repository Structure

```
.
├── backend
│   ├── app
│   │   ├── config.py            # Environment-driven settings
│   │   ├── database.py          # Async SQLAlchemy engine/session helpers
│   │   ├── main.py              # FastAPI entrypoint with WS/REST stubs
│   │   ├── models.py            # ORM tables: sessions/turns/notes/exports
│   │   ├── routers              # LLM, notes, export HTTP APIs
│   │   └── services             # Outline builder, state machine, follow-up helpers
│   ├── requirements.txt         # Python dependencies
│   └── tests                    # Pytest suite for core logic
├── frontend
│   ├── src
│   │   ├── components           # React components for subtitles, outline, notes, metrics
│   │   ├── lib                  # Shared types and WebSocket client base class
│   │   ├── App.tsx              # Interview console layout
│   │   └── main.tsx             # React bootstrapper
│   ├── index.html               # Vite entrypoint
│   └── package.json             # FE dependencies and scripts
├── docker-compose.yml           # Orchestrates FE + BE containers with live reload
├── .env.example                 # Configuration template
└── README.md
```

## 12. Getting Started

### Prerequisites
- Docker and Docker Compose, or alternatively Python 3.11 and Node.js 20 for local runs.
- `pip` and `npm` if running outside containers.

### Quickstart with Docker Compose

```bash
docker compose up --build
```

This boots the FastAPI backend at `http://localhost:8000` and the Vite frontend at `http://localhost:5173`. The frontend will open a WebSocket to the mocked ASR channel and render subtitles, outline progress, mock notes, and metrics counters.

### Local Development (without Docker)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd ../frontend
npm install
npm run dev
```

### Running Tests

```bash
cd backend
pytest
```
