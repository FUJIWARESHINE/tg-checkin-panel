"""推送模块：多渠道适配 + 事件过滤 + 静默时段 + 失败合并降噪。"""

from __future__ import annotations

import asyncio
import smtplib
import time
from dataclasses import dataclass, field
from email.header import Header
from email.mime.text import MIMEText
from typing import Any, Awaitable, Callable

import httpx

from ..logging_setup import logger
from ..security import decrypt
from ..settings import settings

LEVEL_ICON = {"success": "✅", "fail": "❌", "retry": "🔁", "warn": "⚠️", "info": "ℹ️"}

EVENT_LEVEL = {
    "success": "success",
    "fail": "fail",
    "retry": "retry",
    "auth_expired": "fail",
    "scheduler_error": "fail",
}

EVENT_TITLE = {
    "success": "签到成功",
    "fail": "签到失败",
    "retry": "触发重试",
    "auth_expired": "账号登录失效",
    "scheduler_error": "调度异常",
}


@dataclass
class NotifyMessage:
    event: str
    task_name: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    extra: str = ""

    @property
    def level(self) -> str:
        return EVENT_LEVEL.get(self.event, "info")

    @property
    def icon(self) -> str:
        return LEVEL_ICON.get(self.level, "ℹ️")

    @property
    def title(self) -> str:
        return f"{self.icon}【{EVENT_TITLE.get(self.event, self.event)}】{self.task_name}"

    def as_text(self) -> str:
        lines = [self.title]
        lines.extend(f"{k}：{v}" for k, v in self.fields if v not in ("", None))
        if self.extra:
            lines.append(self.extra)
        return "\n".join(lines)

    def as_html(self) -> str:
        lines = [f"<b>{self.title}</b>"]
        for key, value in self.fields:
            if value in ("", None):
                continue
            lines.append(f"{key}：<code>{_escape(str(value))}</code>")
        if self.extra:
            lines.append(f"\n<i>{_escape(self.extra)}</i>")
        return "\n".join(lines)

    def as_markdown(self) -> str:
        lines = [f"**{self.title}**"]
        lines.extend(f"> {k}：{v}" for k, v in self.fields if v not in ("", None))
        if self.extra:
            lines.append(f"\n{self.extra}")
        return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- 渠道适配器


class NotifyError(RuntimeError):
    pass


async def _post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}


async def send_telegram(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    token = (cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        raise NotifyError("Telegram 渠道缺少 bot_token 或 chat_id")
    base = (cfg.get("api_base") or "https://api.telegram.org").rstrip("/")
    payload = {
        "chat_id": chat_id,
        "text": msg.as_html(),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": bool(cfg.get("silent")),
    }
    if cfg.get("message_thread_id"):
        payload["message_thread_id"] = int(cfg["message_thread_id"])
    data = await _post_json(f"{base}/bot{token}/sendMessage", payload)
    if not data.get("ok"):
        raise NotifyError(f"Telegram 推送失败：{data.get('description') or data}")
    return "ok"


async def send_serverchan(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    key = (cfg.get("send_key") or "").strip()
    if not key:
        raise NotifyError("Server 酱渠道缺少 send_key")
    prefix = key.split("sctp")[0] if key.startswith("sctp") else ""
    endpoint = f"https://{prefix or ''}sctapi.ftqq.com/{key}.send"
    data = await _post_json(endpoint, {"title": msg.title, "desp": msg.as_markdown()})
    if data.get("code") not in (0, "0", None):
        raise NotifyError(f"Server 酱推送失败：{data}")
    return "ok"


async def send_bark(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    key = (cfg.get("device_key") or "").strip()
    if not key:
        raise NotifyError("Bark 渠道缺少 device_key")
    base = (cfg.get("server") or "https://api.day.app").rstrip("/")
    payload = {
        "title": msg.title,
        "body": "\n".join(f"{k}：{v}" for k, v in msg.fields if v),
        "group": cfg.get("group") or "TG签到",
        "level": "critical" if msg.level == "fail" else "active",
        "icon": cfg.get("icon") or "",
    }
    if cfg.get("sound"):
        payload["sound"] = cfg["sound"]
    data = await _post_json(f"{base}/{key}", payload)
    if data.get("code") not in (200, "200", None):
        raise NotifyError(f"Bark 推送失败：{data}")
    return "ok"


async def send_gotify(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    base = (cfg.get("server") or "").rstrip("/")
    token = (cfg.get("token") or "").strip()
    if not base or not token:
        raise NotifyError("Gotify 渠道缺少 server 或 token")
    priority = int(cfg.get("priority") or (8 if msg.level == "fail" else 5))
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{base}/message",
            params={"token": token},
            json={"title": msg.title, "message": msg.as_text(), "priority": priority},
        )
        resp.raise_for_status()
    return "ok"


async def send_webhook(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    url = (cfg.get("url") or "").strip()
    if not url:
        raise NotifyError("Webhook 渠道缺少 url")
    headers = cfg.get("headers") or {}
    body = {
        "event": msg.event,
        "level": msg.level,
        "title": msg.title,
        "task": msg.task_name,
        "fields": {k: v for k, v in msg.fields},
        "text": msg.as_text(),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
    return "ok"


async def send_wecom(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    url = (cfg.get("webhook") or "").strip()
    if not url:
        raise NotifyError("企业微信渠道缺少 webhook 地址")
    content = msg.as_markdown()
    if cfg.get("mentioned_mobile"):
        content += f"\n<@{cfg['mentioned_mobile']}>"
    data = await _post_json(url, {"msgtype": "markdown", "markdown": {"content": content}})
    if data.get("errcode") not in (0, None):
        raise NotifyError(f"企业微信推送失败：{data}")
    return "ok"


async def send_dingtalk(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    url = (cfg.get("webhook") or "").strip()
    if not url:
        raise NotifyError("钉钉渠道缺少 webhook 地址")
    secret = (cfg.get("secret") or "").strip()
    if secret:
        import base64
        import hashlib
        import hmac
        import urllib.parse

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(digest))
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}timestamp={timestamp}&sign={sign}"
    data = await _post_json(
        url, {"msgtype": "markdown", "markdown": {"title": msg.title, "text": msg.as_markdown()}}
    )
    if data.get("errcode") not in (0, None):
        raise NotifyError(f"钉钉推送失败：{data}")
    return "ok"


async def send_feishu(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    url = (cfg.get("webhook") or "").strip()
    if not url:
        raise NotifyError("飞书渠道缺少 webhook 地址")
    data = await _post_json(url, {"msg_type": "text", "content": {"text": msg.as_text()}})
    if data.get("code") not in (0, None) and data.get("StatusCode") not in (0, None):
        raise NotifyError(f"飞书推送失败：{data}")
    return "ok"


async def send_email(cfg: dict[str, Any], msg: NotifyMessage) -> str:
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port") or 465)
    user = cfg.get("username")
    password = cfg.get("password")
    to_addr = cfg.get("to")
    if not all([host, user, password, to_addr]):
        raise NotifyError("邮件渠道缺少 smtp_host / username / password / to")

    def _send() -> None:
        mail = MIMEText(msg.as_text(), "plain", "utf-8")
        mail["Subject"] = Header(msg.title, "utf-8")
        mail["From"] = user
        mail["To"] = to_addr
        if cfg.get("ssl", True):
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        try:
            server.login(user, password)
            server.sendmail(user, [to_addr], mail.as_string())
        finally:
            server.quit()

    await asyncio.get_running_loop().run_in_executor(None, _send)
    return "ok"


Adapter = Callable[[dict[str, Any], NotifyMessage], Awaitable[str]]

ADAPTERS: dict[str, Adapter] = {
    "telegram": send_telegram,
    "serverchan": send_serverchan,
    "bark": send_bark,
    "gotify": send_gotify,
    "webhook": send_webhook,
    "wecom": send_wecom,
    "dingtalk": send_dingtalk,
    "feishu": send_feishu,
    "email": send_email,
}

CHANNEL_LABELS = {
    "telegram": "Telegram Bot",
    "serverchan": "Server 酱",
    "bark": "Bark",
    "gotify": "Gotify",
    "webhook": "通用 Webhook",
    "wecom": "企业微信机器人",
    "dingtalk": "钉钉机器人",
    "feishu": "飞书机器人",
    "email": "邮件 SMTP",
}

SENSITIVE_KEYS = {"bot_token", "send_key", "device_key", "token", "password", "secret", "webhook"}


# ---------------------------------------------------------------- 调度


@dataclass
class ChannelView:
    """从 ORM 对象解出来的、可直接使用的渠道视图。"""

    id: int
    name: str
    type: str
    config: dict[str, Any]
    enabled: bool = True
    on_events: list[str] = field(default_factory=list)
    quiet_start: str = ""
    quiet_end: str = ""
    quiet_only_fail: bool = True


def channel_from_orm(obj: Any) -> ChannelView:
    raw = dict(obj.config or {})
    cfg: dict[str, Any] = {}
    for key, value in raw.items():
        cfg[key] = decrypt(value) if key in SENSITIVE_KEYS and isinstance(value, str) else value
    return ChannelView(
        id=obj.id,
        name=obj.name,
        type=obj.type,
        config=cfg,
        enabled=bool(obj.enabled),
        on_events=list(obj.on_events or []),
        quiet_start=obj.quiet_start or "",
        quiet_end=obj.quiet_end or "",
        quiet_only_fail=bool(obj.quiet_only_fail),
    )


class _Dedup:
    """同一任务的连续失败合并推送，成功后补一条恢复通知。"""

    def __init__(self) -> None:
        self._fail_streak: dict[str, int] = {}

    def should_send(self, key: str, event: str) -> tuple[bool, str]:
        if event in ("success", "auth_expired", "scheduler_error"):
            streak = self._fail_streak.pop(key, 0)
            if streak >= 2:
                return True, f"（此前已连续失败 {streak} 次，本次已恢复）"
            return True, ""
        if event == "fail":
            streak = self._fail_streak.get(key, 0) + 1
            self._fail_streak[key] = streak
            if streak in (1, 5, 10) or streak % 20 == 0:
                return True, "" if streak == 1 else f"（已连续失败 {streak} 次，后续将降噪）"
            return False, ""
        return True, ""


_dedup = _Dedup()


def _in_quiet_hours(view: ChannelView, level: str) -> bool:
    if not view.quiet_start or not view.quiet_end:
        return False
    current = time.strftime("%H:%M")
    start, end = view.quiet_start, view.quiet_end
    if start <= end:
        inside = start <= current <= end
    else:  # 跨零点
        inside = current >= start or current <= end
    if not inside:
        return False
    return not (view.quiet_only_fail and level == "fail")


def _event_allowed(view: ChannelView, event: str) -> bool:
    if not view.on_events:
        return True
    return event in view.on_events


async def send_now(view: ChannelView, msg: NotifyMessage) -> tuple[bool, str]:
    adapter = ADAPTERS.get(view.type)
    if adapter is None:
        return False, f"不支持的渠道类型：{view.type}"
    last_error = ""
    for attempt in range(1, 4):
        try:
            await adapter(view.config, msg)
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            logger.warning("渠道 %s 推送失败（第 %s 次）：%s", view.name, attempt, exc)
            await asyncio.sleep(min(2 ** attempt, 8))
    return False, last_error


async def dispatch(
    msg: NotifyMessage, channels: list[ChannelView]
) -> list[tuple[str, bool, str]]:
    """向所有订阅了该事件的渠道推送，返回 (渠道名, 成功, 信息)。"""
    key = f"{msg.task_name}:{msg.event}"
    allow, suffix = _dedup.should_send(key, msg.event)
    if not allow:
        logger.info("推送降噪：%s 的 %s 事件已合并", msg.task_name, msg.event)
        return []
    if suffix:
        msg.extra = (msg.extra + " " + suffix).strip()

    results: list[tuple[str, bool, str]] = []
    for view in channels:
        if not view.enabled:
            continue
        if not _event_allowed(view, msg.event):
            continue
        if _in_quiet_hours(view, msg.level):
            logger.info("渠道 %s 处于静默时段，跳过 %s 推送", view.name, msg.event)
            continue
        ok, info = await send_now(view, msg)
        results.append((view.name, ok, info))
        if not ok:
            logger.error("渠道 %s 推送最终失败：%s", view.name, info)
    return results


def build_message(
    *,
    event: str,
    task_name: str,
    account_name: str = "",
    target: str = "",
    duration_ms: int = 0,
    attempt: int = 1,
    matched_keyword: str = "",
    reward_text: str = "",
    error: str = "",
    next_run: str = "",
) -> NotifyMessage:
    fields: list[tuple[str, str]] = []
    if account_name:
        fields.append(("账号", account_name))
    if target:
        fields.append(("目标", target))
    if duration_ms:
        fields.append(("耗时", f"{duration_ms / 1000:.1f}s"))
    if attempt:
        fields.append(("尝试", f"第 {attempt} 次"))
    if matched_keyword:
        fields.append(("命中", matched_keyword))
    if reward_text:
        fields.append(("奖励", reward_text))
    if next_run:
        fields.append(("下次", next_run))
    if settings.tz:
        fields.append(("时区", settings.tz))
    return NotifyMessage(event=event, task_name=task_name, fields=fields, extra=error)
