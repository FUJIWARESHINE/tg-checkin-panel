"""任务执行编排：跑一次签到 → 判定 → 落记录 → 推送 → 视情况挂重试。

一个任务可以绑定多个账号（`Task.account_ids`），执行时按账号依次签到，
每个账号独立判定、独立落记录、独立推送；只有全部账号成功才算任务成功。
"""

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


def task_account_ids(task: Task) -> list[int]:
    """任务绑定的执行账号；老数据（account_ids 为空）回落到主账号。"""
    ids = [int(i) for i in (task.account_ids or [])]
    if not ids and task.account_id:
        ids = [int(task.account_id)]
    return ids


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


async def _load_task(task_id: int) -> tuple[Task, list[Account]] | None:
    """加载任务及其全部执行账号（保持配置顺序，忽略已删除的账号）。"""
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return None
        accounts: list[Account] = []
        for account_id in task_account_ids(task):
            account = await session.get(Account, account_id)
            if account is not None:
                session.expunge(account)
                accounts.append(account)
        session.expunge(task)
        if not accounts:
            return None
        return task, accounts


async def _already_succeeded_today(
    task_id: int, tz_name: str, account_id: int | None = None
) -> bool:
    start, end = _today_bounds(tz_name)
    async with session_scope() as session:
        stmt = (
            select(Record.id)
            .where(Record.task_id == task_id)
            .where(Record.status == "success")
            .where(Record.run_at >= start)
            .where(Record.run_at < end)
        )
        if account_id is not None:
            stmt = stmt.where(Record.account_id == account_id)
        stmt = stmt.limit(1)
        return (await session.execute(stmt)).first() is not None


async def pending_accounts_today(task_id: int, tz_name: str) -> list[int]:
    """返回今天还没签到成功的账号 id（用于补跑 / 非强制执行时跳过）。"""
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return []
        ids = task_account_ids(task)
    if not ids:
        return []

    start, end = _today_bounds(tz_name)
    async with session_scope() as session:
        stmt = (
            select(Record.account_id)
            .where(Record.task_id == task_id)
            .where(Record.status == "success")
            .where(Record.run_at >= start)
            .where(Record.run_at < end)
            .where(Record.account_id.in_(ids))
            .distinct()
        )
        done = {row[0] for row in (await session.execute(stmt)).all() if row[0] is not None}
    return [i for i in ids if i not in done]


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
    reply: str = "",
) -> str:
    """推送一条通知，返回结局码（写进执行记录，便于事后排查漏通知）。

    结局码：sent / failed / skip:unsubscribed / skip:no-channel /
    skip:channel-missing / skip:filtered / skip:dedup
    """
    subscribed = list(task.notify_on or [])
    if subscribed and event not in subscribed:
        logger.info("任务 %s 未订阅 %s 事件，跳过推送", task.name, event)
        return "skip:unsubscribed"

    channel_ids = list(task.notify_channel_ids or [])
    if not channel_ids:
        # 以前这里直接 return，任务配漏渠道时一句日志都没有，排查时完全看不见
        logger.warning(
            "任务 %s（账号 %s）未配置推送渠道，%s 通知未发送", task.name, account.name, event
        )
        return "skip:no-channel"

    views = await _load_channels(channel_ids)
    if not views:
        logger.warning(
            "任务 %s 绑定的推送渠道 %s 已不存在，%s 通知未发送", task.name, channel_ids, event
        )
        return "skip:channel-missing"

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
        reply=reply,
    )
    outcome = await notifier.dispatch(
        msg, views, scope=f"task{task.id}:account{account.id}"
    )
    for name, ok, info in outcome.results:
        await _mark_channel_result(name, ok, info)

    if outcome.all_ok:
        return "sent"
    if outcome.results:
        return "failed"
    if outcome.reason == "dedup":
        return "skip:dedup"
    logger.warning(
        "任务 %s（账号 %s）的 %s 通知没有任何渠道发出：%s",
        task.name,
        account.name,
        event,
        outcome.reason or "未知原因",
    )
    return "skip:filtered"


async def _mark_notify_status(record_ids: list[int], status: str) -> None:
    """把通知结局写回本次执行产生的记录。"""
    if not record_ids or not status:
        return
    async with session_scope() as session:
        for record_id in record_ids:
            record = await session.get(Record, record_id)
            if record is not None:
                record.notify_status = status


async def _run_account(
    task: Task,
    account: Account,
    targets: list[dict[str, Any]],
    *,
    trigger: str,
    attempt: int,
) -> dict[str, Any]:
    """在单个账号上把所有签到目标跑一遍，返回该账号的汇总结果。"""
    started = time.monotonic()
    all_ok = True
    first_error = ""
    matched = ""
    reward = ""
    summary: list[dict[str, Any]] = []
    recorded: set[str] = set()
    record_ids: list[int] = []
    replies: list[tuple[str, str, bool]] = []
    target_label = ", ".join(str(t.get("chat") or "") for t in targets)

    api_hash = decrypt(account.api_hash) or ""
    session_string = decrypt(account.session_string) or ""
    session_path = account.session_path or str(settings.sessions_dir / f"account_{account.id}")

    async def _record_fail_rest(error_text: str) -> None:
        """账号级失败（连不上 / session 失效）：给还没落记录的目标补一条失败记录。"""
        for item in targets:
            if str(item.get("chat") or "").strip() in recorded:
                continue
            chat = str(item.get("chat") or "").strip()
            record_ids.append(await _save_record(
                task_id=task.id,
                task_name=task.name,
                account_id=account.id,
                account_name=account.name,
                target=chat,
                trigger=trigger,
                status="fail",
                attempt=attempt,
                duration_ms=0,
                reply_snippet=truncate(error_text, 800),
                error=truncate(error_text, 800),
                detail={"account_error": True},
            ))
            summary.append({"target": chat, "ok": False, "error": error_text, "duration_ms": 0})

    try:
        acct = await pool.acquire(
            account.id,
            account.api_id,
            api_hash,
            session_path=session_path,
            session_string=session_string,
        )
        try:
            raw = await acct.start()
        except TelegramCallError as exc:
            if exc.kind == "auth":
                await _mark_account_status(account.id, "need_login")
                await _notify(
                    event="auth_expired",
                    task=task,
                    account=account,
                    target=target_label,
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
            ctx = None

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
                logger.exception("任务 %s 账号 %s 目标 %s 执行异常", task.name, account.name, chat)

            duration_ms = int((time.monotonic() - target_started) * 1000)
            status = "success" if target_ok else "fail"
            all_ok = all_ok and target_ok
            if not target_ok and not first_error:
                first_error = target_error
            if target_matched and not matched:
                matched = target_matched
            if target_reward and not reward:
                reward = target_reward

            # 机器人原话：ctx.replies 记录本次收到的每一条完整文本（含未命中关键词的那条），
            # 比 trace 里被截成 60 字的摘要更适合判断「真成功还是假成功」
            target_reply = ""
            if ctx is not None:
                texts = [str(t).strip() for t in getattr(ctx, "replies", []) if str(t).strip()]
                target_reply = _join_replies(texts) or str(getattr(ctx, "reply_text", "") or "").strip()
            if not target_reply:
                target_reply = _last_reply(trace)
            replies.append((chat, target_reply, target_ok))

            record_ids.append(
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
                    reply_snippet=truncate(target_reply or target_error, 800),
                    reward_text=truncate(target_reward, 255),
                    error=truncate(target_error, 800),
                    detail={"trace": trace, "variables": _safe_variables(trace)},
                )
            )
            recorded.add(chat)
            summary.append(
                {
                    "target": chat,
                    "ok": target_ok,
                    "error": target_error,
                    "reply": target_reply,
                    "duration_ms": duration_ms,
                }
            )

    except Exception as exc:  # noqa: BLE001
        # 账号级失败不能拖垮同任务的其他账号
        error_text = str(exc) or type(exc).__name__
        all_ok = False
        first_error = error_text
        logger.warning("任务 %s 账号 %s 执行失败：%s", task.name, account.name, error_text)
        try:
            await _record_fail_rest(error_text)
        except Exception:  # noqa: BLE001
            logger.exception("任务 %s 账号 %s 的失败记录写入失败", task.name, account.name)
    finally:
        try:
            await pool.release(account.id)
        except Exception:  # noqa: BLE001
            pass

    return {
        "account_id": account.id,
        "account_name": account.name,
        "ok": all_ok,
        "error": first_error,
        "matched": matched,
        "reward": reward,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "targets": summary,
        "reply": _compose_reply(replies, multi=len(targets) > 1),
        "record_ids": record_ids,
    }


async def execute_task(
    task_id: int,
    *,
    trigger: str = "schedule",
    force: bool = True,
    attempt: int = 1,
    only_accounts: list[int] | None = None,
) -> dict[str, Any]:
    """执行一次任务，返回汇总结果。

    - `force=False`：今天已成功的账号自动跳过（补跑 / 非手动触发）
    - `only_accounts`：只跑指定账号（失败重试时只补失败的账号）
    """
    if task_id in _running:
        logger.warning("任务 %s 正在执行中，跳过本次触发", task_id)
        return {"ok": False, "skipped": True, "message": "任务正在执行中"}

    loaded = await _load_task(task_id)
    if loaded is None:
        return {"ok": False, "message": "任务或账号不存在"}
    task, accounts = loaded

    if only_accounts:
        wanted = {int(i) for i in only_accounts}
        accounts = [a for a in accounts if a.id in wanted]
        if not accounts:
            return {"ok": True, "skipped": True, "message": "没有需要重试的账号"}

    if not task.enabled and trigger != "manual":
        return {"ok": False, "skipped": True, "message": "任务已停用"}

    tz_name = task.timezone or settings.tz
    if not force:
        pending = set(await pending_accounts_today(task_id, tz_name))
        accounts = [a for a in accounts if a.id in pending]
        if not accounts:
            logger.info("任务 %s 今日所有账号已成功，跳过", task.name)
            return {"ok": True, "skipped": True, "message": "今日已签到成功"}

    _running.add(task_id)
    started = time.monotonic()
    targets: list[dict[str, Any]] = list(task.targets or [])
    if not targets:
        _running.discard(task_id)
        return {"ok": False, "message": "任务未配置签到目标"}

    summary: list[dict[str, Any]] = []
    account_results: list[dict[str, Any]] = []
    all_ok = True
    first_error = ""
    failed_accounts: list[int] = []
    matched = ""
    reward = ""

    try:
        for account in accounts:
            result = await _run_account(task, account, targets, trigger=trigger, attempt=attempt)
            account_results.append(result)
            summary.extend(result["targets"])
            if not result["ok"]:
                all_ok = False
                failed_accounts.append(account.id)
                first_error = first_error or result["error"]
            if result["matched"] and not matched:
                matched = result["matched"]
            if result["reward"] and not reward:
                reward = result["reward"]

            # 每个账号独立推送，多账号时能一眼看出是哪个号失败
            notify_status = await _notify(
                event="success" if result["ok"] else "fail",
                task=task,
                account=account,
                target=", ".join(str(t.get("chat")) for t in targets),
                duration_ms=result["duration_ms"],
                attempt=attempt,
                matched_keyword=result["matched"],
                reward_text=result["reward"],
                error=result["error"],
                reply=result.get("reply", ""),
            )
            try:
                await _mark_notify_status(list(result.get("record_ids") or []), notify_status)
            except Exception:  # noqa: BLE001
                logger.exception("任务 %s 账号 %s 的通知状态写入失败", task.name, account.name)

        ok_count = sum(1 for r in account_results if r["ok"])
        if all_ok:
            message = (
                f"{ok_count} 个账号签到成功"
                if len(account_results) > 1
                else "签到成功"
            )
        else:
            message = first_error or f"{ok_count}/{len(account_results)} 个账号签到成功"

        await _touch_task(task.id, all_ok, message)
        if not all_ok:
            await _maybe_retry(task, attempt, failed_accounts)

        total_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "任务 %s 执行完成：%s（%s 个账号 / %s 个目标，耗时 %sms）",
            task.name,
            "成功" if all_ok else "失败",
            len(account_results),
            len(targets),
            total_ms,
        )
        return {
            "ok": all_ok,
            "summary": summary,
            "accounts": account_results,
            "message": message,
        }

    finally:
        _running.discard(task_id)


def _last_reply(trace: list[dict[str, Any]]) -> str:
    for item in reversed(trace):
        if item.get("type") == "wait_reply" and item.get("ok"):
            return str(item.get("message") or "")
    return ""


def _join_replies(texts: list[str], keep: int = 3, per_line: int = 400) -> str:
    """把一次执行里收到的多条回复拼成一段，最多保留最后 keep 条。"""
    picked = [t[:per_line] for t in texts[-keep:]] if texts else []
    return "\n".join(picked)


def _compose_reply(items: list[tuple[str, str, bool]], multi: bool = False) -> str:
    """把各目标的机器人原文拼成一段推送内容。

    多目标时优先展示失败的那几个（排查失败原因比看成功文案更急），
    并带上目标名，避免几个对话的回复混在一起分不清。
    """
    filled = [(chat, text.strip(), ok) for chat, text, ok in items if (text or "").strip()]
    if not filled:
        return ""
    failed = [(chat, text) for chat, text, ok in filled if not ok]
    picked = failed or [(chat, text) for chat, text, ok in filled]
    if not multi:
        return picked[0][1]
    # 多目标任务一定要标出这条回复来自哪个会话，否则几个机器人的话分不清
    return "\n\n".join(f"【{chat}】\n{text}" for chat, text in picked[:3])


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


async def _maybe_retry(task: Task, attempt: int, account_ids: list[int] | None = None) -> None:
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

    schedule_retry(task.id, max(30, interval), attempt + 1, account_ids=account_ids)
    logger.info(
        "任务 %s 将在 %s 秒后重试（第 %s 次，%s 个账号）",
        task.name,
        interval,
        attempt + 1,
        len(account_ids or []),
    )
