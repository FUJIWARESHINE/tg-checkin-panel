"""任务执行编排：跑一次签到 → 判定 → 落记录 → 推送 → 视情况挂重试。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from telethon import utils as tg_utils

from ..db import session_scope
from ..logging_setup import logger
from ..models import Account, NotifyChannel, Record, Task
from ..security import decrypt
from ..settings import settings
from ..utils.text import mask_phone, truncate
from . import notifier
from .actions import RunContext, StepError, StepTimeout, apply_success_rule, build_variables, run_flow
from .client_pool import TelegramCallError, pool

# 运行中的任务，防止重入
_running: set[int] = set()


def is_running(task_id: int) -> bool:
    return task_id in _running


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_bounds(tz_name: str) -> tuple[datetime, datetime]:
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_name or settings.tz)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    local_now = datetime.now(tz)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


async def _load_task(task_id: int) -> tuple[Task, Account] | None:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return None
        account = await session.get(Account, task.account_id)
        if account is None:
            return None
        session.expunge(task)
        session.expunge(account)
        return task, account


async def _already_succeeded_today(task_id: int, tz_name: str) -> bool:
    start, end = _today_bounds(tz_name)
    async with session_scope() as session:
        stmt = (
            select(Record.id)
            .where(Record.task_id == task_id)
            .where(Record.status == "success")
            .where(Record.run_at >= start)
            .where(Record.run_at < end)
            .limit(1)
        )
        return (await session.execute(stmt)).first() is not None


async def _save_record(**kwargs: Any) -> int:
    async with session_scope() as session:
        record = Record(**kwargs)
        session.add(record)
        await session.flush()
        return record.id


async def _load_channels(ids: list[int]) -> list[notifier.ChannelView]:
    if not ids:
        return []
    async with session_scope() as session:
        rows = (await session.execute(select(NotifyChannel).where(NotifyChannel.id.in_(ids)))).scalars().all()
        views = [notifier.channel_from_orm(r) for r in rows]
        return views


async def _mark_channel_result(name: str, ok: bool, info: str) -> None:
    async with session_scope() as session:
        rows = (
            (await session.execute(select(NotifyChannel).where(NotifyChannel.name == name))).scalars().all()
        )
        for row in rows:
            row.last_result = ("ok" if ok else truncate(info, 200))
            row.last_sent_at = _now()


async def _notify(
    *,
    event: str,
    task: Task,
    account: Account,
    target: str,
    duration_ms: int,
    attempt: int,
    matched_keyword: str = "",
    reward_text: str = "",
    error: str = "",
) -> None:
    channel_ids = list(task.notify_channel_ids or [])
    views = await _load_channels(channel_ids)
    if not views:
        return
    next_run = task.next_run_at.astimezone(timezone.utc).isoformat() if task.next_run_at else ""
    msg = notifier.build_message(
        event=event,
        task_name=task.name,
        account_name=f"{account.name} {mask_phone(account.phone)}".strip(),
        target=target,
        duration_ms=duration_ms,
        attempt=attempt,
        matched_keyword=matched_keyword,
        reward_text=reward_text,
        error=error,
        next_run=next_run,
    )
    results = await notifier.dispatch(msg, views)
    for name, ok, info in results:
        await _mark_channel_result(name, ok, info)


async def execute_task(
    task_id: int,
    *,
    trigger: str = "schedule",
    force: bool = True,
    attempt: int = 1,
) -> dict[str, Any]:
    """执行一次任务，返回汇总结果。"""
    if task_id in _running:
        logger.warning("任务 %s 正在执行中，跳过本次触发", task_id)
        return {"ok": False, "skipped": True, "message": "任务正在执行中"}

    loaded = await _load_task(task_id)
    if loaded is None:
        return {"ok": False, "message": "任务或账号不存在"}
    task, account = loaded

    if not task.enabled and trigger != "manual":
        return {"ok": False, "skipped": True, "message": "任务已停用"}

    tz_name = task.timezone or settings.tz
    if not force and await _already_succeeded_today(task_id, tz_name):
        logger.info("任务 %s 今日已成功，跳过", task.name)
        return {"ok": True, "skipped": True, "message": "今日已签到成功"}

    _running.add(task_id)
    started = time.monotonic()
    targets: list[dict[str, Any]] = list(task.targets or [])
    if not targets:
        _running.discard(task_id)
        return {"ok": False, "message": "任务未配置签到目标"}

    summary: list[dict[str, Any]] = []
    all_ok = True
    first_error = ""
    matched = ""
    reward = ""

    try:
        api_hash = decrypt(account.api_hash) or ""
        session_string = decrypt(account.session_string) or ""
        session_path = account.session_path or str(settings.sessions_dir / f"account_{account.id}")

        acct = await pool.acquire(
            account.id,
            account.api_id,
            api_hash,
            session_path=session_path,
            session_string=session_string,
            proxy=account.proxy or settings.tg_proxy,
        )
        try:
            raw = await acct.start()
        except TelegramCallError as exc:
            error_text = str(exc)
            if exc.kind == "auth":
                await _mark_account_status(account.id, "need_login")
                await _notify(
                    event="auth_expired",
                    task=task,
                    account=account,
                    target=", ".join(t.get("chat", "") for t in targets),
                    duration_ms=0,
                    attempt=attempt,
                    error="账号 session 已失效，请在账号管理中重新登录",
                )
            raise

        await _mark_account_status(account.id, "online", active=True)

        for item in targets:
            chat = str(item.get("chat") or "").strip()
            thread_id = item.get("thread_id")
            target_started = time.monotonic()
            target_ok = False
            target_error = ""
            target_matched = ""
            target_reward = ""
            trace: list[dict[str, Any]] = []

            try:
                entity = await acct.call(raw.get_entity, chat)
                target_id = tg_utils.get_peer_id(entity)
                ctx = RunContext(
                    raw=raw,
                    acct=acct,
                    entity=entity,
                    target_label=chat,
                    thread_id=int(thread_id) if thread_id else None,
                    timeout_sec=task.timeout_sec or settings.task_timeout_sec,
                    step_timeout_sec=settings.step_timeout_sec,
                    task_name=task.name,
                    target_id=target_id,
                )
                ctx.variables = build_variables(ctx)

                await run_flow(ctx, list(task.action_flow or []))

                rule_ok, reason = apply_success_rule(ctx, dict(task.success_rule or {}))
                # 动作流里 condition 主动判定成功时，规则判定不再否决
                if ctx.outcome == "success" and ctx.outcome_reason:
                    target_ok, reason = True, ctx.outcome_reason
                else:
                    target_ok = rule_ok
                target_matched = ctx.matched_keyword or (reason if target_ok else "")
                target_reward = ctx.reward_text or str(ctx.variables.get("reward_text") or "")
                trace = ctx.trace
                if not target_ok:
                    target_error = reason
            except StepTimeout as exc:
                target_error = f"超时：{exc}"
            except StepError as exc:
                target_error = f"步骤失败（第 {exc.step_index + 1} 步 {exc.step_type}）：{exc}"
            except TelegramCallError as exc:
                target_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                target_error = f"未预期错误：{type(exc).__name__} {exc}"
                logger.exception("任务 %s 目标 %s 执行异常", task.name, chat)

            duration_ms = int((time.monotonic() - target_started) * 1000)
            status = "success" if target_ok else "fail"
            all_ok = all_ok and target_ok
            if not target_ok and not first_error:
                first_error = target_error
            if target_matched and not matched:
                matched = target_matched
            if target_reward and not reward:
                reward = target_reward

            await _save_record(
                task_id=task.id,
                task_name=task.name,
                account_id=account.id,
                account_name=account.name,
                target=chat,
                trigger=trigger,
                status=status,
                attempt=attempt,
                duration_ms=duration_ms,
                matched_keyword=truncate(target_matched, 128),
                reply_snippet=truncate(_last_reply(trace) or target_error, 800),
                reward_text=truncate(target_reward, 255),
                error=truncate(target_error, 800),
                detail={"trace": trace, "variables": _safe_variables(trace)},
            )
            summary.append(
                {"target": chat, "ok": target_ok, "error": target_error, "duration_ms": duration_ms}
            )

        total_ms = int((time.monotonic() - started) * 1000)
        await _touch_task(task.id, all_ok, first_error or "签到成功")

        if all_ok:
            await _notify(
                event="success",
                task=task,
                account=account,
                target=", ".join(str(t.get("chat")) for t in targets),
                duration_ms=total_ms,
                attempt=attempt,
                matched_keyword=matched,
                reward_text=reward,
            )
        else:
            await _notify(
                event="fail",
                task=task,
                account=account,
                target=", ".join(str(t.get("chat")) for t in targets),
                duration_ms=total_ms,
                attempt=attempt,
                error=first_error,
            )
            await _maybe_retry(task, attempt)

        logger.info(
            "任务 %s 执行完成：%s（%s 个目标，耗时 %sms）",
            task.name,
            "成功" if all_ok else "失败",
            len(targets),
            total_ms,
        )
        return {"ok": all_ok, "summary": summary, "message": "签到成功" if all_ok else first_error}

    finally:
        _running.discard(task_id)
        try:
            await pool.release(account.id)
        except Exception:  # noqa: BLE001
            pass


def _last_reply(trace: list[dict[str, Any]]) -> str:
    for item in reversed(trace):
        if item.get("type") == "wait_reply" and item.get("ok"):
            return str(item.get("message") or "")
    return ""


def _safe_variables(trace: list[dict[str, Any]]) -> dict[str, Any]:
    return {"steps": len(trace), "failed": sum(1 for t in trace if not t.get("ok"))}


async def _touch_task(task_id: int, ok: bool, message: str) -> None:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return
        task.last_run_at = _now()
        task.last_status = "success" if ok else "fail"
        task.last_message = truncate(message, 500)


async def _mark_account_status(account_id: int, status: str, active: bool = False) -> None:
    async with session_scope() as session:
        account = await session.get(Account, account_id)
        if account is None:
            return
        account.status = status
        if active:
            account.last_active_at = _now()


async def _maybe_retry(task: Task, attempt: int) -> None:
    policy = dict(task.retry_policy or {})
    max_retry = int(policy.get("max") or settings.default_retry_max)
    interval = int(policy.get("interval_sec") or settings.default_retry_interval)
    until_success = bool(policy.get("until_success"))

    if not until_success and attempt > max_retry:
        logger.info("任务 %s 已达最大重试次数 %s，停止重试", task.name, max_retry)
        return
    if attempt > 50:
        logger.warning("任务 %s 重试次数过多，强制停止", task.name)
        return

    from .scheduler import schedule_retry

    schedule_retry(task.id, max(30, interval), attempt + 1)
    logger.info("任务 %s 将在 %s 秒后重试（第 %s 次）", task.name, interval, attempt + 1)
