from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Query

from ..core.ws_tts_manager import manager as tts_manager
from ..services.fake_tts import stream_demo_webm

router = APIRouter()

ASSET_PATH = os.environ.get("DEMO_TTS_PATH", "assets/demo_tts.webm")


@router.post("/v1/tts/demo/start")
async def start_demo(session: str = Query(...)) -> dict:
    if not os.path.exists(ASSET_PATH):
        raise HTTPException(status_code=404, detail=f"asset not found: {ASSET_PATH}")
    task = asyncio.create_task(stream_demo_webm(session, ASSET_PATH))
    return {"ok": True}


@router.post("/v1/tts/demo/stop")
async def stop_demo(session: str = Query(...)) -> dict:
    tts_manager.cancel(session)
    return {"ok": True}
