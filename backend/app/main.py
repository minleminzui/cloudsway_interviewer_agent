from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_models, shutdown
from .routers import demo_tts, http_api, ws_agent, ws_asr, ws_tts

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(http_api.router, prefix="/v1", tags=["http"])
app.include_router(demo_tts.router, tags=["demo"])
app.include_router(ws_agent.router, tags=["ws"])
app.include_router(ws_asr.router, tags=["ws"])
app.include_router(ws_tts.router, tags=["ws"])


@app.on_event("startup")
async def on_startup() -> None:
    await init_models()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await shutdown()
