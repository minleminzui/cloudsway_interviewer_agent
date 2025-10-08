from __future__ import annotations
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_models, shutdown
from .routers import demo_tts, http_api, ws_agent, ws_asr, ws_tts
from .utils.ws_manager import WebSocketManager

# ===========================================================
# 🌐 全局应用初始化
# ===========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)

app = FastAPI(title=settings.app_name)

# ===========================================================
# 🧠 全局 WebSocketManager 单例
# ===========================================================

# ⚙️ Uvicorn reload / 多worker 模式下确保唯一实例
if not hasattr(app.state, "ws_manager") or not isinstance(app.state.ws_manager, WebSocketManager):
    app.state.ws_manager = WebSocketManager()
    logging.info("[main] 🧩 Initialized global WebSocketManager")

else:
    logging.info("[main] ♻️ Reusing existing WebSocketManager instance")


# ===========================================================
# 🔐 CORS 配置
# ===========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 部署时建议改成指定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================
# 🧩 路由注册
# ===========================================================
app.include_router(http_api.router, prefix="/v1", tags=["http"])
app.include_router(demo_tts.router, tags=["demo"])
app.include_router(ws_agent.router, tags=["ws"])
app.include_router(ws_asr.router, tags=["ws"])
app.include_router(ws_tts.router, tags=["ws"])


# ===========================================================
# ⚙️ 生命周期钩子
# ===========================================================
@app.on_event("startup")
async def on_startup() -> None:
    """启动事件：初始化数据库与全局状态"""
    await init_models()
    if not hasattr(app.state, "ws_manager"):
        app.state.ws_manager = WebSocketManager()
        logging.info("[startup] 🧩 Created new WebSocketManager")
    else:
        logging.info("[startup] ✅ Using existing WebSocketManager")
    logging.info("[startup] ✅ Database initialized, app ready")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """关闭事件：释放连接资源"""
    await shutdown()
    logging.info("[shutdown] 🛑 FastAPI shutdown complete")


# ===========================================================
# 💓 健康检查接口
# ===========================================================
@app.get("/health")
async def health_check():
    """简单健康检查接口，用于监控"""
    mgr: WebSocketManager = app.state.ws_manager
    return {
        "status": "ok",
        "active_sessions": mgr.active_sessions(),
    }
