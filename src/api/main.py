"""
src/api/main.py — Application factory.
Assembles FastAPI app with lifespan, middleware, and route modules.
This replaces the monolithic src/server.py.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.dependencies import RUNTIME_PROFILE, runtime
from src.core.serving import Overloaded

logger = logging.getLogger("projecta.api")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — nothing to do (lazy init)
    yield
    # Shutdown — close the shared HTTP client pool
    from src.core.utils import HttpClientPool
    await HttpClientPool.close()


# ---------------------------------------------------------------------------
# App Assembly
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Token", "X-User-Id", "X-Store-Id"],
)


# Middleware: attach request ID
@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", os.urandom(8).hex())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Quá tải KHÔNG phải lỗi máy chủ — nó là câu trả lời hợp lệ "đang bận, quay
# lại sau". Trả 500 ở đây khiến client retry ngay lập tức và làm tình hình tệ
# thêm; 503 kèm Retry-After nói cho client biết chờ bao lâu là đủ.
@app.exception_handler(Overloaded)
async def handle_overloaded(request: Request, exc: Overloaded):
    return JSONResponse(
        status_code=503,
        content={"error": "overloaded", "detail": str(exc),
                 "retry_after_s": exc.retry_after_s},
        headers={"Retry-After": str(exc.retry_after_s)},
    )


# Health endpoint (stays here — it's app-level, not domain-specific)
@app.get("/health")
async def health():
    # Thống kê điều tiết tải nằm ngay trong /health: chỉnh ngưỡng mà không đo
    # được hàng đợi thì chỉ là đoán. `peak_queued` và `rejected_total` là hai
    # con số quyết định nên nâng hay hạ max_concurrent.
    load: dict = {}
    engine = runtime.engine
    for name in ("text_guard", "vision_guard"):
        guard = getattr(engine, name, None)
        if guard is not None:
            load[name.replace("_guard", "")] = guard.snapshot()

    return JSONResponse(
        {
            "status": "ok",
            "runtime_profile": RUNTIME_PROFILE,
            "degraded": bool(runtime.engine_error or runtime.kb_error or runtime.vision_error),
            "engine_ready": runtime.engine is not None,
            "kb_ready": runtime.kb is not None,
            "vision_ready": runtime.vision is not None,
            "engine_error": runtime.engine_error,
            "kb_error": runtime.kb_error,
            "vision_error": runtime.vision_error,
            "load": load,
        }
    )


# Register routers
from src.api.routes.chat import router as chat_router
from src.api.routes.documents import router as documents_router
from src.api.routes.tools import mcp_router
from src.api.routes.tools import router as tools_router

app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(tools_router)   # tầng tool tất định — n8n + agentic dùng chung
app.include_router(mcp_router)     # MCP bọc đúng manifest trên (không định nghĩa lại)
