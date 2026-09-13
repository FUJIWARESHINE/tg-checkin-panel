"""调度器：APScheduler 封装。任务定义存库，启动时全量重建 job。"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from ..db import session_scope
from ..logging_setup import logger
from ..models import Task
from ..settings import settings
from ..utils.cron import ScheduleError, build_trigger, describe_schedule

scheduler = AsyncIOScheduler(timezone=settings.tz)
_semaphore: asyncio.Semaphore | None = None
_retry_jobs: dict[int, str] = {}


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_tasks))
    return _semaphore


def job_id(task_id: int) -> str:
    return f"task:{task_id}"


def _tz(task: Task) -> str:
    return task.timezone or settings.tz


async def _run_job(task_id: int, trigger: str = "schedule", attempt: int = 1) -> None:
    from . import runner

    async with _sem():
        try:
            await runner.execute_task(task_id, trigger=trigger, force=(trigger != "catchup"), attempt=attempt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务 %s 调度执行异常：%s", task_id, exc)
            await _notify_scheduler_error(task_id, str(exc))


async def _notify_scheduler_error(task_id: int, error: str) -> None:
    from ..models import Account, NotifyChannel
    from . import notifier

    try:
        async with session_scope() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return
            account = await session.get(Account, task.account_id)
            channel_ids = list(task.notify_channel_ids or [])
            if not channel_ids:
                return
            rows = (
                (await session.execute(select(NotifyChannel).where(NotifyChannel.id.in_(channel_ids))))
                .scalars()
                .all()
            )
            channels = [notifier.channel_from_orm(c) for c in rows]
            msg = notifier.build_message(
                event="scheduler_error",
                task_name=task.name,
                account_name=account.name if account else "",
                error=error,
            )
        if channels:
            await notifier.dispatch(msg, channels)
    except Exception as exc:  # noqa: BLE001
        logger.debug("调度异常通知发送失败：%s", exc)


def schedule_task(task: Task) -> bool:
    """按任务配置注册/更新 job。返回是否成功注册。"""
    tid = job_id(task.id)
    try:
        scheduler.remove_job(tid)
    except Exception:  # noqa: BLE001
        pass

    if not task.enabled:
        return False

    try:
        trigger = build_trigger(task.schedule_type, task.schedule_value, _tz(task))
    except ScheduleError as exc:
        logger.error("任务 %s 调度表达式不合法，未注册：%s", task.name, exc)
        return False

    async def _wrapped(tid_: int = task.id) -> None:
        delay = 0
        if task.random_delay_sec:
            delay = random.randint(0, max(0, int(task.random_delay_sec)))
        if delay:
            logger.info("任务 %s 随机延迟 %s 秒后执行", task.name, delay)
            await asyncio.sleep(delay)
        await _run_job(tid_, trigger="schedule")

    scheduler.add_job(
        _wrapped,
        trigger=trigger,
        id=tid,
        name=task.name,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    return True


def schedule_retry(task_id: int, delay_sec: int, attempt: int) -> None:
    rid = f"retry:{task_id}"
    try:
        scheduler.remove_job(rid)
    except Exception:  # noqa: BLE001
        pass
    scheduler.add_job(
        _run_job,
        trigger=DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=delay_sec)),
        id=rid,
        name=f"retry-{task_id}",
        kwargs={"task_id": task_id, "trigger": "retry", "attempt": attempt},
        max_instances=1,
        replace_existing=True,
    )
    _retry_jobs[task_id] = rid


def remove_task(task_id: int) -> None:
    for jid in (job_id(task_id), f"retry:{task_id}"):
        try:
            scheduler.remove_job(jid)
        except Exception:  # noqa: BLE001
            pass
    _retry_jobs.pop(task_id, None)


def next_run_time(task_id: int) -> datetime | None:
    job = scheduler.get_job(job_id(task_id))
    if job is None:
        return None
    value = getattr(job, "next_run_time", None)
    if value is None:
        return None
    return value.astimezone(timezone.utc)


async def rebuild_all() -> int:
    """启动时重建所有 enabled 任务的 job。"""
    count = 0
    async with session_scope() as session:
        tasks = (await session.execute(select(Task))).scalars().all()
        for task in tasks:
            session.expunge(task)
            if schedule_task(task):
                count += 1
    return count


async def catch_up() -> list[str]:
    """补跑：启动时对"今天本该签到但没成功"的任务立即跑一次。"""
    from . import runner

    done: list[str] = []
    async with session_scope() as session:
        tasks = (
            (await session.execute(select(Task).where(Task.enabled.is_(True), Task.catch_up.is_(True))))
            .scalars()
            .all()
        )
        pending: list[tuple[int, str]] = []
        for task in tasks:
            session.expunge(task)
            pending.append((task.id, task.name))

    for task_id, name in pending:
        try:
            if await runner._already_succeeded_today(task_id, settings.tz):  # noqa: SLF001
                continue
            logger.info("补跑任务：%s", name)
            await runner.execute_task(task_id, trigger="catchup", force=True)
            done.append(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("补跑任务 %s 失败：%s", name, exc)
    return done


def start() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("调度器已启动（时区 %s，最大并发 %s）", settings.tz, settings.max_concurrent_tasks)


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("调度器已停止")


def status() -> dict[str, Any]:
    jobs = scheduler.get_jobs() if scheduler.running else []
    return {
        "running": scheduler.running,
        "job_count": len(jobs),
        "jobs": [
            {
                "id": j.id,
                "name": j.name,
                "next_run": j.next_run_time.isoformat() if getattr(j, "next_run_time", None) else None,
            }
            for j in jobs
        ],
    }


def describe(task: Task) -> str:
    return describe_schedule(task.schedule_type, task.schedule_value)
