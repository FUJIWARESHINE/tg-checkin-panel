"""系统接口：信息 / 设置 / 日志 / 调度状态 / 备份。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from .. import runtime_config
from ..core import scheduler as sched
from ..core.client_pool import pool
from ..db import session_scope
from ..logging_setup import logger, ring_handler
from ..models import Account, Task
from ..schemas import OkOut, SystemInfoOut, SystemSettingsIn
from ..settings import settings
from .deps import current_user

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info", response_model=SystemInfoOut)
async def info(_: str = Depends(current_user)) -> SystemInfoOut:
    async with session_scope() as session:
        accounts = (await session.execute(select(Account))).scalars().all()
        online = sum(1 for a in accounts if pool.is_online(a.id))
        tasks_total = (await session.execute(select(func.count(Task.id)))).scalar_one()
        tasks_enabled = (
            await session.execute(select(func.count(Task.id)).where(Task.enabled.is_(True)))
        ).scalar_one()

    db_size = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    return SystemInfoOut(
        app_name=settings.app_name,
        version=settings.app_version,
        timezone=settings.tz,
        proxy=settings.tg_proxy or "未配置",
        scheduler_running=sched.scheduler.running,
        accounts_online=online,
        tasks_total=tasks_total,
        tasks_enabled=tasks_enabled,
        data_dir=str(settings.data_dir),
        db_size=db_size,
        ai_enabled=bool(settings.ai_enabled and settings.openai_api_key),
        mask_hint="敏感信息已加密存储",
    )


@router.get("/settings")
async def get_settings_api(_: str = Depends(current_user)) -> dict[str, object]:
    return {"ok": True, "settings": await runtime_config.current()}


@router.put("/settings", response_model=OkOut)
async def put_settings(payload: SystemSettingsIn, _: str = Depends(current_user)) -> OkOut:
    values = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not values:
        return OkOut(message="没有需要更新的设置")

    if "timezone" in values:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(str(values["timezone"]))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"时区不合法：{values['timezone']}") from exc
    if "tg_proxy" in values and values["tg_proxy"]:
        from ..core.client_pool import parse_proxy

        try:
            parse_proxy(str(values["tg_proxy"]))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"代理地址不合法：{exc}") from exc

    saved = await runtime_config.save(values)
    logger.info("系统设置已更新：%s", ", ".join(saved.keys()))

    # 时区变了要重建调度。
    # 注意：APScheduler 3.x 在运行中调用 scheduler.configure() 会抛
    # SchedulerAlreadyRunningError，所以这里不重配调度器本身 —— 每个 job 的
    # trigger 都是按任务自己的时区显式构造的，重建 job 即可生效。
    if "timezone" in values:
        await sched.rebuild_all()
    if "max_concurrent_tasks" in values:
        sched._semaphore = None  # noqa: SLF001 - 触发下次重建信号量
    return OkOut(message="设置已保存并生效")


@router.get("/logs")
async def logs(
    limit: int = Query(200, ge=1, le=2000),
    level: str = "",
    keyword: str = "",
    _: str = Depends(current_user),
) -> dict[str, object]:
    return {"ok": True, "items": ring_handler.tail(limit=limit, level=level, keyword=keyword)}


@router.get("/scheduler")
async def scheduler_status(_: str = Depends(current_user)) -> dict[str, object]:
    return {"ok": True, **sched.status()}


@router.post("/scheduler/rebuild", response_model=OkOut)
async def rebuild_scheduler(_: str = Depends(current_user)) -> OkOut:
    count = await sched.rebuild_all()
    return OkOut(message=f"已重建 {count} 个调度任务")


@router.post("/catch-up", response_model=OkOut)
async def catch_up_now(_: str = Depends(current_user)) -> OkOut:
    names = await sched.catch_up()
    if not names:
        return OkOut(message="没有需要补跑的任务")
    return OkOut(message=f"已补跑 {len(names)} 个任务：{', '.join(names)}")


@router.get("/backup")
async def backup(_: str = Depends(current_user)) -> FileResponse:
    if not settings.db_path.exists():
        raise HTTPException(status_code=404, detail="数据库文件不存在")
    from datetime import datetime

    filename = f"tg-checkin-panel-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    return FileResponse(settings.db_path, filename=filename, media_type="application/octet-stream")
