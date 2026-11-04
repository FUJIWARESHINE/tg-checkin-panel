"""推送渠道接口。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..core import notifier
from ..db import session_scope
from ..logging_setup import logger
from ..models import NotifyChannel
from ..schemas import NotifyChannelIn, NotifyChannelOut, OkOut, TestNotifyIn
from ..security import encrypt
from .deps import current_user

router = APIRouter(prefix="/api/notify", tags=["notify"])

# 前端据此动态渲染表单
CHANNEL_SCHEMA: dict[str, dict[str, object]] = {
    "telegram": {
        "label": "Telegram Bot",
        "hint": "用你自己的通知 Bot 给你自己发消息。token 从 @BotFather 获取，chat_id 可发给 @userinfobot 查询。",
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "type": "password", "required": True},
            {"key": "chat_id", "label": "Chat ID", "type": "text", "required": True, "placeholder": "123456789"},
            {"key": "api_base", "label": "API 反代地址", "type": "text", "placeholder": "https://api.telegram.org"},
            {"key": "message_thread_id", "label": "话题 ID（可选）", "type": "text"},
            {"key": "silent", "label": "静默发送", "type": "switch"},
        ],
    },
    "serverchan": {
        "label": "Server 酱",
        "hint": "sctapi.ftqq.com 的 SendKey。",
        "fields": [{"key": "send_key", "label": "SendKey", "type": "password", "required": True}],
    },
    "bark": {
        "label": "Bark",
        "hint": "iOS 推送，自建服务可改 server。",
        "fields": [
            {"key": "device_key", "label": "Device Key", "type": "password", "required": True},
            {"key": "server", "label": "服务器地址", "type": "text", "placeholder": "https://api.day.app"},
            {"key": "group", "label": "分组", "type": "text", "placeholder": "TG签到"},
            {"key": "sound", "label": "铃声", "type": "text"},
        ],
    },
    "gotify": {
        "label": "Gotify",
        "fields": [
            {"key": "server", "label": "服务器地址", "type": "text", "required": True, "placeholder": "https://gotify.example.com"},
            {"key": "token", "label": "应用 Token", "type": "password", "required": True},
            {"key": "priority", "label": "优先级", "type": "number", "placeholder": "5"},
        ],
    },
    "webhook": {
        "label": "通用 Webhook",
        "hint": "以 POST JSON 投递，适合接入自建服务。",
        "fields": [
            {"key": "url", "label": "URL", "type": "password", "required": True},
            {"key": "headers", "label": "自定义 Header (JSON)", "type": "json"},
        ],
    },
    "wecom": {
        "label": "企业微信机器人",
        "fields": [
            {"key": "webhook", "label": "Webhook 地址", "type": "password", "required": True},
            {"key": "mentioned_mobile", "label": "@手机号", "type": "text"},
        ],
    },
    "dingtalk": {
        "label": "钉钉机器人",
        "fields": [
            {"key": "webhook", "label": "Webhook 地址", "type": "password", "required": True},
            {"key": "secret", "label": "加签密钥", "type": "password"},
        ],
    },
    "feishu": {
        "label": "飞书机器人",
        "fields": [{"key": "webhook", "label": "Webhook 地址", "type": "password", "required": True}],
    },
    "email": {
        "label": "邮件 SMTP",
        "fields": [
            {"key": "smtp_host", "label": "SMTP 服务器", "type": "text", "required": True},
            {"key": "smtp_port", "label": "端口", "type": "number", "placeholder": "465"},
            {"key": "username", "label": "账号", "type": "text", "required": True},
            {"key": "password", "label": "密码/授权码", "type": "password", "required": True},
            {"key": "to", "label": "收件人", "type": "text", "required": True},
            {"key": "ssl", "label": "使用 SSL", "type": "switch"},
        ],
    },
}


def _mask_config(config: dict[str, object]) -> dict[str, object]:
    masked: dict[str, object] = {}
    for key, value in (config or {}).items():
        from ..security import decrypt

        plain = decrypt(value) if isinstance(value, str) else value
        if key in notifier.SENSITIVE_KEYS:
            masked[key] = "********" if plain else ""
        else:
            masked[key] = plain
    return masked


def _to_out(row: NotifyChannel) -> NotifyChannelOut:
    return NotifyChannelOut(
        id=row.id,
        name=row.name,
        type=row.type,
        config_masked=_mask_config(dict(row.config or {})),
        enabled=row.enabled,
        on_events=list(row.on_events or []),
        quiet_start=row.quiet_start or "",
        quiet_end=row.quiet_end or "",
        quiet_only_fail=row.quiet_only_fail,
        last_result=row.last_result or "",
        last_sent_at=row.last_sent_at,
        created_at=row.created_at,
    )


def _prepare_config(payload: dict[str, object], previous: dict[str, object] | None = None) -> dict[str, object]:
    """敏感字段留空时沿用旧值；否则加密存储。"""
    previous = previous or {}
    result: dict[str, object] = {}
    for key, value in (payload or {}).items():
        if key in notifier.SENSITIVE_KEYS and isinstance(value, str):
            if value == "********" or value == "":
                if key in previous:
                    result[key] = previous[key]
                continue
            result[key] = encrypt(value)
        else:
            result[key] = value
    return result


@router.get("/types")
async def channel_types(_: str = Depends(current_user)) -> dict[str, object]:
    return {"ok": True, "types": CHANNEL_SCHEMA, "events": sorted(notifier.EVENT_LEVEL.keys())}


@router.get("", response_model=list[NotifyChannelOut])
async def list_channels(_: str = Depends(current_user)) -> list[NotifyChannelOut]:
    async with session_scope() as session:
        rows = (await session.execute(select(NotifyChannel).order_by(NotifyChannel.id))).scalars().all()
        return [_to_out(r) for r in rows]


@router.post("", response_model=NotifyChannelOut)
async def create_channel(payload: NotifyChannelIn, _: str = Depends(current_user)) -> NotifyChannelOut:
    if payload.type not in CHANNEL_SCHEMA:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型：{payload.type}")
    async with session_scope() as session:
        row = NotifyChannel(
            name=payload.name,
            type=payload.type,
            config=_prepare_config(payload.config),
            enabled=payload.enabled,
            on_events=payload.on_events,
            quiet_start=payload.quiet_start,
            quiet_end=payload.quiet_end,
            quiet_only_fail=payload.quiet_only_fail,
        )
        session.add(row)
        await session.flush()
        session.expunge(row)
    logger.info("新增推送渠道：%s (%s)", payload.name, payload.type)
    return _to_out(row)


@router.put("/{channel_id}", response_model=NotifyChannelOut)
async def update_channel(
    channel_id: int, payload: NotifyChannelIn, _: str = Depends(current_user)
) -> NotifyChannelOut:
    async with session_scope() as session:
        row = await session.get(NotifyChannel, channel_id)
        if row is None:
            raise HTTPException(status_code=404, detail="渠道不存在")
        row.name = payload.name
        row.type = payload.type
        row.config = _prepare_config(payload.config, dict(row.config or {}))
        row.enabled = payload.enabled
        row.on_events = payload.on_events
        row.quiet_start = payload.quiet_start
        row.quiet_end = payload.quiet_end
        row.quiet_only_fail = payload.quiet_only_fail
        await session.flush()
        session.expunge(row)
    return _to_out(row)


@router.delete("/{channel_id}", response_model=OkOut)
async def delete_channel(channel_id: int, _: str = Depends(current_user)) -> OkOut:
    async with session_scope() as session:
        row = await session.get(NotifyChannel, channel_id)
        if row is None:
            raise HTTPException(status_code=404, detail="渠道不存在")
        await session.delete(row)
    return OkOut(message="渠道已删除")


@router.post("/test", response_model=OkOut)
async def test_channel(payload: TestNotifyIn, _: str = Depends(current_user)) -> OkOut:
    """用表单里当前填写的配置直接试推一条。"""
    if payload.type not in notifier.ADAPTERS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型：{payload.type}")

    config: dict[str, object] = {}
    for key, value in (payload.config or {}).items():
        if key in notifier.SENSITIVE_KEYS and (value in ("", "********", None)):
            continue
        config[key] = value

    # 允许用「已保存渠道」的 id 补全被脱敏的密钥
    channel_id = payload.config.get("_channel_id") if payload.config else None
    if channel_id:
        async with session_scope() as session:
            row = await session.get(NotifyChannel, int(channel_id))
            if row is not None:
                stored = notifier.channel_from_orm(row)
                for key, value in stored.config.items():
                    config.setdefault(key, value)

    view = notifier.ChannelView(id=0, name="test", type=payload.type, config=config)
    msg = notifier.NotifyMessage(
        event="success",
        task_name="连接测试",
        fields=[("渠道", notifier.CHANNEL_LABELS.get(payload.type, payload.type)), ("发送时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))],
        extra="如果你收到这条消息，说明推送配置正确。",
    )
    ok, info = await notifier.send_now(view, msg)
    if not ok:
        raise HTTPException(status_code=400, detail=f"推送失败：{info}")
    return OkOut(message="测试消息已发送，请查看接收端")


NOTIFY_PROBE_EVENTS = ("success", "fail", "auth_expired", "scheduler_error")


@router.get("/diagnose")
async def diagnose(_: str = Depends(current_user)) -> dict[str, object]:
    """通知链路自检：逐任务判断「通知到底能不能发出来」。

    排查「任务跑了但没收到推送」时先看这里：没选渠道、渠道停用、渠道没订阅该事件、
    处在静默时段、任务没注册调度，都会在这里明确写出来。
    """
    from ..core import scheduler as sched
    from ..models import Record, Task

    async with session_scope() as session:
        channels = (
            (await session.execute(select(NotifyChannel).order_by(NotifyChannel.id))).scalars().all()
        )
        tasks = (await session.execute(select(Task).order_by(Task.id))).scalars().all()
        views = {c.id: notifier.channel_from_orm(c) for c in channels}
        last_records = (
            (await session.execute(select(Record).order_by(Record.run_at.desc()).limit(200)))
            .scalars()
            .all()
        )

        channel_items = [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "enabled": bool(c.enabled),
                "on_events": list(c.on_events or []),
                "quiet_start": c.quiet_start or "",
                "quiet_end": c.quiet_end or "",
                "last_result": c.last_result or "",
                "last_sent_at": c.last_sent_at.isoformat() if c.last_sent_at else None,
            }
            for c in channels
        ]

        last_notify: dict[int, str] = {}
        for record in last_records:
            if record.task_id is not None and record.task_id not in last_notify:
                last_notify[record.task_id] = record.notify_status or ""

        task_items: list[dict[str, object]] = []
        unscheduled = 0
        no_channel = 0
        delivering = 0

        for task in tasks:
            problems: list[str] = []
            ids = [int(i) for i in (task.notify_channel_ids or [])]
            subscribed = list(task.notify_on or [])
            events = subscribed or list(NOTIFY_PROBE_EVENTS)

            delivery: dict[str, dict[str, object]] = {}
            for event in events:
                level = notifier.EVENT_LEVEL.get(event, "info")
                usable: list[str] = []
                blocked: dict[str, str] = {}
                for cid in ids:
                    view = views.get(cid)
                    if view is None:
                        blocked[f"#{cid}"] = "渠道已不存在"
                        continue
                    reason = notifier.skip_reason(view, event, level)
                    if reason:
                        blocked[view.name] = reason
                    else:
                        usable.append(view.name)
                delivery[event] = {"channels": usable, "blocked": blocked}
                if ids and not usable:
                    detail = "；".join(f"{k}：{v}" for k, v in blocked.items())
                    problems.append(f"「{notifier.EVENT_TITLE.get(event, event)}」通知发不出去（{detail}）")

            if not ids:
                problems.insert(0, "没有选择推送渠道，任何通知都不会发出")
                no_channel += 1
            elif any(delivery[e]["channels"] for e in delivery):
                delivering += 1

            live = sched.next_run_time(task.id)
            if not task.enabled:
                problems.append("任务已停用，不会自动执行")
            elif sched.scheduler.running and live is None:
                unscheduled += 1
                problems.append("调度未生效（算不出下次执行时间），请重新保存任务")

            task_items.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "enabled": bool(task.enabled),
                    "scheduled": live is not None,
                    "next_run_at": live.isoformat() if live else None,
                    "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
                    "last_status": task.last_status or "",
                    "subscribed_events": subscribed,
                    "channel_ids": ids,
                    "delivery": delivery,
                    "last_notify_status": last_notify.get(task.id, ""),
                    "problems": problems,
                }
            )

    return {
        "ok": True,
        "timezone": notifier.settings.tz,
        "channels": channel_items,
        "tasks": task_items,
        "summary": {
            "tasks_total": len(task_items),
            "tasks_can_notify": delivering,
            "tasks_without_channel": no_channel,
            "tasks_unscheduled": unscheduled,
            "channels_total": len(channel_items),
            "channels_enabled": sum(1 for c in channel_items if c["enabled"]),
        },
    }


@router.post("/{channel_id}/test", response_model=OkOut)
async def test_saved_channel(channel_id: int, _: str = Depends(current_user)) -> OkOut:
    async with session_scope() as session:
        row = await session.get(NotifyChannel, channel_id)
        if row is None:
            raise HTTPException(status_code=404, detail="渠道不存在")
        view = notifier.channel_from_orm(row)
        view.enabled = True  # 测试时忽略静默/事件订阅
        view.on_events = []
        view.quiet_start = ""
        view.quiet_end = ""
        name = row.name

    msg = notifier.NotifyMessage(
        event="success",
        task_name="连接测试",
        fields=[("渠道", name), ("发送时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))],
        extra="如果你收到这条消息，说明推送配置正确。",
    )
    ok, info = await notifier.send_now(view, msg)
    async with session_scope() as session:
        stored = await session.get(NotifyChannel, channel_id)
        if stored is not None:
            stored.last_result = "ok" if ok else info[:200]
            stored.last_sent_at = datetime.now(timezone.utc)
    if not ok:
        raise HTTPException(status_code=400, detail=f"推送失败：{info}")
    return OkOut(message="测试消息已发送，请查看接收端")
