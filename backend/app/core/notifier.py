"""推送模块：多渠道适配 + 事件过滤 + 静默时段 + 失败合并降噪。"""

from __future__ import annotations

import asyncio
import re
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import Header
from email.mime.text import MIMEText
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

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
    # 机器人实际返回的原文，用来判断是真签到成功还是「假成功」
    reply: str = ""
    # 放在原文之后的收尾信息（下次执行 / 时区），避免把原文压在角落里
    tail: list[tuple[str, str]] = field(default_factory=list)

    @property
    def level(self) -> str:
        return EVENT_LEVEL.get(self.event, "info")

    @property
    def icon(self) -> str:
        return LEVEL_ICON.get(self.level, "ℹ️")

    @property
    def title(self) -> str:
        return f"{self.icon}【{EVENT_TITLE.get(self.event, self.event)}】{self.task_name}"

    @property
    def reply_lines(self) -> list[str]:
        return self.reply.split("\n") if self.reply else []

    def as_text(self) -> str:
        lines = [self.title]
        lines.extend(f"{k}：{v}" for k, v in self.fields if v not in ("", None))
        if self.reply:
            lines.append("返回内容：")
            lines.append(self.reply)
        lines.extend(f"{k}：{v}" for k, v in self.tail if v not in ("", None))
        if self.extra:
            lines.append(self.extra)
        return "\n".join(lines)

    def as_html(self) -> str:
        lines = [f"<b>{self.title}</b>"]
        for key, value in self.fields:
            if value in ("", None):
                continue
            lines.append(f"{key}：<code>{_escape(str(value))}</code>")
        if self.reply:
            # Telegram 单条上限 4096 字符，超长时去掉等宽块，避免整条被拒
            block = f"<pre>{_escape(self.reply)}</pre>"
            if len("\n".join(lines)) + len(block) + 8 <= 4000:
                lines.append("返回内容：")
                lines.append(block)
            else:
                lines.append(f"返回内容：{_escape(self.reply)}")
        for key, value in self.tail:
            if value in ("", None):
                continue
            lines.append(f"{key}：<code>{_escape(str(value))}</code>")
        if self.extra:
            lines.append(f"\n<i>{_escape(self.extra)}</i>")
        return "\n".join(lines)

    def as_markdown(self) -> str:
        lines = [f"**{self.title}**"]
        lines.extend(f"> {k}：{v}" for k, v in self.fields if v not in ("", None))
        if self.reply:
            lines.append("")
            lines.append("**返回内容**")
            lines.extend(f"> {line}" for line in self.reply_lines)
        lines.extend(f"> {k}：{v}" for k, v in self.tail if v not in ("", None))
        if self.extra:
            lines.append(f"\n{self.extra}")
        return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- 渠道适配器


class NotifyError(RuntimeError):
    pass


async def _post_json(
    url: str, payload: dict[str, Any], timeout: int = 20, proxy: str | None = None
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}


def _resolve_http_proxy() -> str | None:
    """为推送解析 httpx 可用的代理，统一取全局 settings.tg_proxy。

    Telethon 支持的 mtproxy 协议 httpx 不支持，遇到时忽略代理直连。
    """
    raw = (settings.tg_proxy or "").strip()
    if not raw:
        return None
    scheme = raw.split("://", 1)[0].lower()
    if scheme not in ("socks5", "socks4", "http", "https"):
        logger.info("推送代理协议 %r 不被 HTTP 客户端支持，本次推送将直连", scheme)
        return None
    return raw


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
    data = await _post_json(
        f"{base}/bot{token}/sendMessage", payload, proxy=_resolve_http_proxy()
    )
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
    body = "\n".join(f"{k}：{v}" for k, v in msg.fields if v)
    if msg.reply:
        body += f"\n\n返回内容：\n{msg.reply}"
    tail = "\n".join(f"{k}：{v}" for k, v in msg.tail if v)
    if tail:
        body += f"\n{tail}"
    if msg.extra:
        body += f"\n{msg.extra}"
    payload = {
        "title": msg.title,
        "body": body,
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
        "reply": msg.reply,
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


def _local_now() -> datetime:
    """按面板配置时区取当前时间（静默时段 / 降噪跨天判断都用它）。"""
    try:
        tz = ZoneInfo(settings.tz or "UTC")
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return datetime.now(tz)


class _Dedup:
    """连续失败合并推送，成功后补一条恢复通知。

    key 必须精确到「任务 + 账号」，否则多账号任务里 A 账号的连续失败会把
    B 账号的首次失败吞掉；同时按天重置，避免昨天的失败计数让今天的首条
    失败通知被静默。
    """

    def __init__(self) -> None:
        self._fail_streak: dict[str, int] = {}
        self._fail_day: dict[str, str] = {}

    def reset(self) -> None:
        self._fail_streak.clear()
        self._fail_day.clear()

    def should_send(self, key: str, event: str, day: str | None = None) -> tuple[bool, str]:
        if event in ("success", "auth_expired", "scheduler_error"):
            streak = self._fail_streak.pop(key, 0)
            self._fail_day.pop(key, None)
            if streak >= 2:
                return True, f"（此前已连续失败 {streak} 次，本次已恢复）"
            return True, ""
        if event == "fail":
            today = day or _local_now().strftime("%Y-%m-%d")
            if self._fail_day.get(key) != today:
                self._fail_day[key] = today
                self._fail_streak[key] = 0
            streak = self._fail_streak.get(key, 0) + 1
            self._fail_streak[key] = streak
            if streak in (1, 5, 10) or streak % 20 == 0:
                return True, "" if streak == 1 else f"（今日已连续失败 {streak} 次，后续将降噪）"
            return False, ""
        return True, ""


_dedup = _Dedup()


def _in_quiet_hours(view: ChannelView, level: str) -> bool:
    if not view.quiet_start or not view.quiet_end:
        return False
    # 之前用服务器本地时间，容器 TZ 与面板时区不一致时会把静默时段算错、误吞通知
    current = _local_now().strftime("%H:%M")
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


def skip_reason(view: ChannelView, event: str, level: str) -> str:
    """渠道不发送的原因；空串表示可以发送。调度自检和真实推送共用同一套判定。"""
    if not view.enabled:
        return "渠道已停用"
    if not _event_allowed(view, event):
        return f"渠道未订阅 {event} 事件"
    if _in_quiet_hours(view, level):
        return "处于静默时段"
    return ""


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
            last_error = str(exc) or exc.__class__.__name__
            logger.warning("渠道 %s 推送失败（第 %s 次）：%s", view.name, attempt, exc)
            await asyncio.sleep(min(2 ** attempt, 8))
    return False, last_error


@dataclass
class DispatchOutcome:
    """一次推送的结果：成功发出的渠道 + 一条都没发出时的原因。"""

    results: list[tuple[str, bool, str]] = field(default_factory=list)
    reason: str = ""

    @property
    def sent(self) -> bool:
        return any(ok for _, ok, _ in self.results)

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and all(ok for _, ok, _ in self.results)


async def dispatch(
    msg: NotifyMessage, channels: list[ChannelView], *, scope: str = ""
) -> DispatchOutcome:
    """向所有订阅了该事件的渠道推送。

    `scope` 是降噪用的唯一标识，调用方应带上「任务 + 账号」，避免多账号任务
    互相吞掉失败通知；不传时退回任务名。注意 key 里不能再拼事件名，否则
    成功事件查不到失败计数，「连续失败后恢复」的提示永远不会出现。
    """
    key = scope or msg.task_name
    allow, suffix = _dedup.should_send(key, msg.event)
    if not allow:
        logger.info("推送降噪：%s 的 %s 事件已合并", msg.task_name, msg.event)
        return DispatchOutcome(reason="dedup")
    if suffix:
        msg.extra = (msg.extra + " " + suffix).strip()

    outcome = DispatchOutcome()
    for view in channels:
        reason = skip_reason(view, msg.event, msg.level)
        if reason:
            logger.info("渠道 %s 跳过 %s 推送：%s", view.name, msg.event, reason)
            outcome.reason = outcome.reason or f"{view.name}：{reason}"
            continue
        ok, info = await send_now(view, msg)
        outcome.results.append((view.name, ok, info))
        if not ok:
            logger.error("渠道 %s 推送最终失败：%s", view.name, info)
    return outcome



REPLY_LIMIT = 900


def clean_reply(text: str, limit: int = REPLY_LIMIT) -> str:
    """规整机器人返回原文：统一换行、压缩空行、超长截断。"""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return ""
    value = re.sub(r"\n{3,}", "\n\n", value)
    if len(value) > limit:
        value = value[:limit].rstrip() + " …（内容过长已截断）"
    return value


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
    reply: str = "",
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
    if error:
        # 失败时把原因摆到明面上，而不是塞在末尾的小字里
        label = "失败原因" if EVENT_LEVEL.get(event) == "fail" else "说明"
        fields.append((label, clean_reply(error, 400)))
    tail: list[tuple[str, str]] = []
    if next_run:
        tail.append(("下次", next_run))
    if settings.tz:
        tail.append(("时区", settings.tz))
    return NotifyMessage(
        event=event,
        task_name=task_name,
        fields=fields,
        tail=tail,
        reply=clean_reply(reply),
    )
