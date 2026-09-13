"""FastAPI 入口。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import admin_store, runtime_config
from .api import accounts, auth, notify, records, system, tasks, ws
from .core import scheduler as sched
from .core.client_pool import pool
from .db import dispose_db, init_db
from .logging_setup import logger, ring_handler
from .settings import settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


async def _startup() -> None:
    settings.ensure_dirs()
    await init_db()
    admin_store.ensure_admin()
    await runtime_config.load()

    ring_handler.bind_loop(asyncio.get_running_loop())
    sched.start()
    count = await sched.rebuild_all()
    logger.info("=" * 60)
    logger.info("%s v%s 已启动", settings.app_name, settings.app_version)
    logger.info("数据目录：%s", settings.data_dir)
    logger.info("管理员：%s", admin_store.username())
    logger.info("调度任务：%s 个已注册", count)
    logger.info("=" * 60)

    async def _deferred_catchup() -> None:
        await asyncio.sleep(10)
        try:
            done = await sched.catch_up()
            if done:
                logger.info("启动补跑完成：%s", ", ".join(done))
        except Exception as exc:  # noqa: BLE001
            logger.warning("启动补跑失败：%s", exc)

    asyncio.create_task(_deferred_catchup())


async def _shutdown() -> None:
    sched.shutdown()
    await pool.shutdown()
    await dispose_db()
    logger.info("已安全退出")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup()
    try:
        yield
    finally:
        await _shutdown()


app = FastAPI(
    title="TG 自动签到面板",
    version=settings.app_version,
    description="Docker 化的 Telegram 自动签到服务，带 Web 管理界面、可视化定时任务与多渠道推送。",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "message": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"ok": False, "message": f"服务器内部错误：{exc}"})


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "version": settings.app_version,
        "scheduler": sched.scheduler.running,
        "timezone": settings.tz,
    }


for router in (auth.router, accounts.router, tasks.router, records.router, notify.router, system.router, ws.router):
    app.include_router(router)


if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # 未知的 /api 路径不能回退到 index.html，否则前端拿到 HTML 会报 JSON 解析错误
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404, detail=f"接口不存在：/{full_path}")
        # 只允许读取 static 目录内的真实文件，防目录穿越
        if full_path and ".." not in full_path:
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.is_file() and str(candidate).startswith(str(STATIC_DIR.resolve())):
                return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:  # 开发模式下前端由 Vite 单独跑

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, object]:
        return {
            "ok": True,
            "message": "前端静态资源未构建。开发模式下请访问 Vite 端口（默认 5173），生产模式请先构建 frontend。",
            "docs": "/api/docs",
        }
