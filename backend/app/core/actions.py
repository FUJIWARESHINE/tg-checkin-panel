"""动作流执行器：把配置化的步骤数组跑成真实的 Telegram 交互。

支持 8 种步骤：send_text / send_dice / click_button / wait_reply / ai_choose / condition / sleep / extract
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

from telethon import TelegramClient, events
from telethon.tl import types

from ..logging_setup import logger
from ..utils.text import extract_group, match_text, render_template
from .client_pool import AccountClient


class StepError(RuntimeError):
    """单个步骤执行失败。"""

    def __init__(self, message: str, *, step_index: int = -1, step_type: str = "") -> None:
        super().__init__(message)
        self.step_index = step_index
        self.step_type = step_type


class StepTimeout(StepError):
    pass


@dataclass
class RunContext:
    raw: TelegramClient
    acct: AccountClient
    entity: Any
    target_label: str
    thread_id: int | None = None
    timeout_sec: int = 300
    step_timeout_sec: int = 60
    variables: dict[str, Any] = field(default_factory=dict)
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    last_sent: Any = None
    reply_message: Any = None
    reply_text: str = ""
    task_name: str = ""
    target_id: int | None = None
    # 本次发送的消息 id 基线：只接受比它更新的来消息，
    # 避免把「上一条指令」的延迟回复误当成当前步骤的回复
    since_message_id: int | None = None
    # 执行结果
    outcome: str = "fail"  # success | fail
    outcome_reason: str = ""
    matched_keyword: str = ""
    reward_text: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)

    def note(self, index: int, step_type: str, message: str, ok: bool = True) -> None:
        self.trace.append(
            {"index": index, "type": step_type, "ok": ok, "message": message, "at": time.time()}
        )


def _require(value: Any, name: str, index: int, step_type: str) -> Any:
    if value is None or value == "":
        raise StepError(f"{step_type} 缺少必填参数：{name}", step_index=index, step_type=step_type)
    return value


async def _delete_later(raw: TelegramClient, acct: AccountClient, message: Any, seconds: float) -> None:
    try:
        await asyncio.sleep(seconds)
        await acct.call(raw.delete_messages, message.chat_id, [message.id])
        logger.debug("已删除签到消息 %s", message.id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("删除消息失败（忽略）：%s", exc)


def _message_id(message: Any) -> int | None:
    value = getattr(message, "id", None)
    return value if isinstance(value, int) else None


def _is_stale(ctx: RunContext, message: Any) -> bool:
    """消息是否早于本次发送（例如上一条指令的延迟回复）。"""
    if ctx.since_message_id is None:
        return False
    msg_id = _message_id(message)
    return msg_id is not None and msg_id <= ctx.since_message_id


async def _mark_baseline(ctx: RunContext, sent: Any) -> None:
    """记录本次发送的消息 id，并丢弃队列里比它更旧的来消息。

    场景：同一个会话里目标 1 超时后，bot 才把它那条「签到成功」补回来；
    目标 2 的 wait_reply 会立刻命中这条陈旧回复，导致流程走错分支。
    以「我们自己发出的那条消息的 id」为分界线即可精准排除。
    """
    msg_id = _message_id(sent)
    if msg_id is None:
        return
    ctx.since_message_id = msg_id
    dropped = 0
    kept: list[Any] = []
    while not ctx.inbox.empty():
        try:
            item = ctx.inbox.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - 竞态兜底
            break
        item_id = _message_id(item)
        if item_id is not None and item_id <= msg_id:
            dropped += 1
        else:
            kept.append(item)
    for item in kept:
        ctx.inbox.put_nowait(item)
    if dropped:
        logger.debug("丢弃 %s 条早于本次发送的陈旧消息（基线 id=%s）", dropped, msg_id)


async def _visible_buttons(
    ctx: RunContext, message: Any, index: int, step_type: str
) -> list[Any]:
    """取出消息上可点击的按钮并拍平；没有按钮时返回空列表。"""
    try:
        raw = await ctx.acct.call(message.get_buttons)
    except Exception as exc:  # noqa: BLE001
        raise StepError(
            f"读取消息按钮失败：{exc}", step_index=index, step_type=step_type
        ) from exc
    flat: list[Any] = []
    for item in raw or []:
        if isinstance(item, (list, tuple)):
            flat.extend(item)
        else:
            flat.append(item)
    return flat


def _button_labels(buttons: list[Any]) -> list[str]:
    return [str(getattr(b, "text", "") or "?") for b in buttons]


# ---------------------------------------------------------------- handlers


async def h_send_text(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    st = "send_text"
    text = render_template(str(_require(step.get("text"), "text", index, st)), ctx.variables)
    kwargs: dict[str, Any] = {}
    if ctx.thread_id:
        kwargs["reply_to"] = ctx.thread_id
    ctx.last_sent = await ctx.acct.call(ctx.raw.send_message, ctx.entity, text, **kwargs)
    await _mark_baseline(ctx, ctx.last_sent)
    if step.get("delay_after"):
        await asyncio.sleep(float(step["delay_after"]))
    if step.get("delete_after"):
        asyncio.create_task(
            _delete_later(ctx.raw, ctx.acct, ctx.last_sent, float(step["delete_after"]))
        )
    return f"已发送文本：{text[:40]}"


async def h_send_dice(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    st = "send_dice"
    emoji = str(step.get("emoji") or "🎲")
    kwargs: dict[str, Any] = {}
    if ctx.thread_id:
        kwargs["reply_to"] = ctx.thread_id
    ctx.last_sent = await ctx.acct.call(
        ctx.raw.send_message, ctx.entity, file=types.InputMediaDice(emoji), **kwargs
    )
    await _mark_baseline(ctx, ctx.last_sent)
    if step.get("wait_result"):
        ctx.variables["dice_value"] = getattr(ctx.last_sent, "dice", None) and ctx.last_sent.dice.value
    if step.get("delay_after"):
        await asyncio.sleep(float(step["delay_after"]))
    if step.get("delete_after"):
        asyncio.create_task(
            _delete_later(ctx.raw, ctx.acct, ctx.last_sent, float(step["delete_after"]))
        )
    return f"已发送骰子 {emoji}"


async def h_click_button(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    st = "click_button"
    message = ctx.reply_message or ctx.last_sent
    if message is None:
        raise StepError("没有可点击的消息（请先 wait_reply 或 send_text）", step_index=index, step_type=st)
    text = render_template(str(step.get("text") or ""), ctx.variables) or None
    idx = step.get("index")
    # Telethon 1.37+ 的 Message.click() 已没有 timeout 参数（只能在外面包一层超时）
    timeout = float(step.get("timeout") or ctx.step_timeout_sec)

    # 没有按钮时 Telethon 的 click() 会静默返回 None，以前会被记成「已点击按钮」
    # 但实际什么都没点，这里先自己确认按钮存在，把问题暴露在第 3 步而不是后面的「等待回复超时」。
    buttons = await _visible_buttons(ctx, message, index, st)
    if not buttons:
        raise StepError(
            f"这条消息上没有可点击的按钮（回复内容：{(ctx.reply_text or '')[:40] or '空'}），"
            "请检查上一步等待的是哪条回复",
            step_index=index,
            step_type=st,
        )

    if text:
        # 字符串 text 是「完全相等」匹配，按钮常带 emoji/空格（如「🎯 签到」），
        # 这里做不区分大小写的包含匹配，并在找不到时把可用按钮列出来。
        matched = [b for b in buttons if text.lower() in str(getattr(b, "text", "") or "").lower()]
        if not matched:
            raise StepError(
                f"未找到按钮「{text}」，可点击的按钮有：{_button_labels(buttons)}",
                step_index=index,
                step_type=st,
            )
        target_label = str(getattr(matched[0], "text", "") or text)
        click_kwargs: dict[str, Any] = {"text": re.compile(re.escape(text), re.IGNORECASE).search}
    else:
        i = int(idx or 0)
        if i >= len(buttons):
            raise StepError(
                f"按钮序号 {i} 越界，可点击的按钮有：{_button_labels(buttons)}",
                step_index=index,
                step_type=st,
            )
        target_label = f"#{i}"
        click_kwargs = {"i": i}

    try:
        clicked = await asyncio.wait_for(
            ctx.acct.call(message.click, **click_kwargs), timeout=timeout
        )
    except ValueError as exc:
        raise StepError(f"未找到指定按钮：{target_label}（{exc}）", step_index=index, step_type=st) from exc
    except asyncio.TimeoutError as exc:
        raise StepTimeout("点击按钮后等待响应超时", step_index=index, step_type=st) from exc

    if clicked is None:
        # 按钮确实点了（上面已确认存在），只是机器人没回 answer：
        # 常见于 URL 按钮 / 纯回调按钮，这种情况不算失败，但要提示清楚。
        logger.warning(
            "[%s] 步骤 %s 已点击按钮「%s」，但机器人没有返回应答",
            ctx.task_name,
            index + 1,
            target_label,
        )
        note = "（机器人未返回应答）"
    else:
        note = ""
    if clicked is not None and getattr(clicked, "raw_text", None):
        ctx.reply_message = clicked
        ctx.reply_text = clicked.raw_text or ""
    if step.get("delay_after"):
        await asyncio.sleep(float(step["delay_after"]))
    return f"已点击按钮：{target_label}{note}"


async def h_wait_reply(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    st = "wait_reply"
    timeout = float(step.get("timeout") or ctx.step_timeout_sec)
    match_cfg = step.get("match") or {}
    mode = str(match_cfg.get("mode") or "contains")
    keyword = str(match_cfg.get("keyword") or "")
    require_match = bool(keyword) and str(step.get("require_match", True)).lower() != "false"
    deadline = time.monotonic() + timeout
    seen: list[str] = []

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StepTimeout(
                f"等待回复超时（{timeout}s），已收到：{seen[-3:] if seen else '无'}",
                step_index=index,
                step_type=st,
            )
        try:
            message = await asyncio.wait_for(ctx.inbox.get(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise StepTimeout(f"等待回复超时（{timeout}s）", step_index=index, step_type=st) from exc

        if _is_stale(ctx, message):
            logger.debug("忽略早于本次发送的陈旧回复 id=%s", _message_id(message))
            continue

        text = (getattr(message, "raw_text", "") or "").strip()
        if not text:
            continue
        seen.append(text[:60])
        hit, snippet = match_text(keyword, text, mode)
        ctx.reply_message = message
        ctx.reply_text = text
        ctx.variables["last_reply"] = text
        if hit or not require_match:
            ctx.matched_keyword = snippet or keyword
            return f"收到回复：{text[:60]}"
        logger.debug("回复未命中关键词，继续等待：%s", text[:60])


async def h_ai_choose(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    """AI 识图答题（预留接口）。

    配置示例：
      {"type":"ai_choose","prompt":"选择正确的选项","options":["A","B","C"]}
    需要 AI_ENABLED=true 且配置 OPENAI_API_KEY。
    """
    from . import ai as ai_module

    st = "ai_choose"
    if not ai_module.is_enabled():
        raise StepError(
            "AI 识图答题未启用（需在系统设置中开启并配置 OpenAI 兼容 API Key）",
            step_index=index,
            step_type=st,
        )
    message = ctx.reply_message
    if message is None or not getattr(message, "photo", None):
        raise StepError("AI 识图需要一个带图片的回复消息", step_index=index, step_type=st)

    photo_bytes = await ctx.acct.call(ctx.raw.download_media, message, bytes)
    options = step.get("options") or []
    answer = await ai_module.choose_option(
        image_bytes=photo_bytes,
        prompt=str(step.get("prompt") or "请根据图片内容选出正确选项"),
        options=[str(o) for o in options],
    )
    if not answer:
        raise StepError("AI 未能给出答案", step_index=index, step_type=st)

    ctx.variables["ai_answer"] = answer
    if step.get("reply_text"):
        text = render_template(str(step["reply_text"]), ctx.variables)
        ctx.last_sent = await ctx.acct.call(ctx.raw.send_message, ctx.entity, text)
    elif step.get("click"):
        buttons = await _visible_buttons(ctx, message, index, st)
        matched = [
            b for b in buttons if answer.lower() in str(getattr(b, "text", "") or "").lower()
        ]
        if not matched:
            raise StepError(
                f"未找到选项按钮「{answer}」，可点击的按钮有：{_button_labels(buttons)}",
                step_index=index,
                step_type=st,
            )
        await asyncio.wait_for(
            ctx.acct.call(
                message.click, text=re.compile(re.escape(answer), re.IGNORECASE).search
            ),
            timeout=float(ctx.step_timeout_sec),
        )
    return f"AI 答案：{answer}"


async def h_condition(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    st = "condition"
    source = render_template(str(step.get("if") or "{last_reply}"), ctx.variables)
    op = str(step.get("op") or "contains")
    value = render_template(str(step.get("value") or ""), ctx.variables)
    then = str(step.get("then") or "continue")

    if op in ("contains", "not_contains", "regex", "exact"):
        hit, _ = match_text(value, source, "exact" if op == "exact" else ("regex" if op == "regex" else "contains"))
        if op == "not_contains":
            hit = not hit
    elif op in ("equals", "=="):
        hit = source.strip() == value.strip()
    elif op in ("!=", "not_equals"):
        hit = source.strip() != value.strip()
    elif op in ("empty",):
        hit = not source.strip()
    elif op in ("not_empty",):
        hit = bool(source.strip())
    else:
        hit = False

    if not hit:
        return f"条件不成立（跳过 {then}）"

    if then == "stop":
        ctx.outcome = "success"
        ctx.outcome_reason = f"条件命中并主动结束：{value or op}"
        raise _StopFlow("条件触发 stop")
    if then == "fail":
        raise StepError(f"条件命中并判定失败：{value or op}", step_index=index, step_type=st)
    if then == "success":
        ctx.outcome = "success"
        ctx.outcome_reason = f"条件命中并判定成功：{value or op}"
        raise _StopFlow("条件触发 success")
    return f"条件成立：{value or op}"


async def h_sleep(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    seconds = float(step.get("seconds") or 1)
    await asyncio.sleep(min(seconds, 300))
    return f"等待 {seconds}s"


async def h_extract(ctx: RunContext, step: dict[str, Any], index: int) -> str:
    st = "extract"
    pattern = str(_require(step.get("regex"), "regex", index, st))
    source = render_template(str(step.get("from") or "{last_reply}"), ctx.variables)
    group = int(step.get("group") or 0)
    value = extract_group(pattern, source, group)
    name = str(step.get("as") or "extracted")
    ctx.variables[name] = value
    if name in ("reward", "points", "reward_text"):
        ctx.reward_text = value
    return f"提取 {name} = {value or '(空)'}"


class _StopFlow(Exception):
    """内部信号：提前结束动作流且不算失败。"""


HANDLERS = {
    "send_text": h_send_text,
    "send_dice": h_send_dice,
    "click_button": h_click_button,
    "wait_reply": h_wait_reply,
    "ai_choose": h_ai_choose,
    "condition": h_condition,
    "sleep": h_sleep,
    "extract": h_extract,
}


async def attach_inbox(ctx: RunContext) -> Any:
    """注册消息监听，把目标会话的来消息塞进 ctx.inbox。"""
    target_id = ctx.target_id

    async def _on_message(event: Any) -> None:
        try:
            message = event.message
            if message is None:
                return
            if getattr(message, "out", False) and not ctx.variables.get("_capture_own"):
                return
            if target_id is not None and getattr(event, "chat_id", None) != target_id:
                return
            if _is_stale(ctx, message):
                return
            await ctx.inbox.put(message)
        except Exception:  # noqa: BLE001
            pass

    handler = _on_message
    ctx.raw.add_event_handler(handler, events.NewMessage())
    return handler


def detach_inbox(ctx: RunContext, handler: Any) -> None:
    try:
        ctx.raw.remove_event_handler(handler)
    except Exception:  # noqa: BLE001
        pass


async def run_flow(ctx: RunContext, flow: list[dict[str, Any]]) -> RunContext:
    """顺序执行动作流。异常向外抛，由 runner 统一处理。"""
    handler = await attach_inbox(ctx)
    started = time.monotonic()
    try:
        for index, step in enumerate(flow):
            if time.monotonic() - started > ctx.timeout_sec:
                raise StepTimeout(
                    f"任务总超时（{ctx.timeout_sec}s）", step_index=index, step_type=str(step.get("type"))
                )
            step_type = str(step.get("type") or "")
            handler_fn = HANDLERS.get(step_type)
            if handler_fn is None:
                raise StepError(f"未知动作类型：{step_type}", step_index=index, step_type=step_type)
            try:
                message = await asyncio.wait_for(
                    handler_fn(ctx, step, index), timeout=ctx.step_timeout_sec + 120
                )
                ctx.note(index, step_type, message, ok=True)
                logger.info("[%s] 步骤 %s %s -> %s", ctx.task_name, index + 1, step_type, message)
            except StepError as exc:
                ctx.note(index, step_type, str(exc), ok=False)
                logger.warning("[%s] 步骤 %s %s 失败：%s", ctx.task_name, index + 1, step_type, exc)
                raise
    except _StopFlow:
        pass
    finally:
        detach_inbox(ctx, handler)
    return ctx


def apply_success_rule(ctx: RunContext, rule: dict[str, Any]) -> tuple[bool, str]:
    """按成功规则判定；规则为空时以是否收到回复为准。"""
    mode = str(rule.get("mode") or "contains")
    keywords = [str(k) for k in (rule.get("keywords") or [])]
    source = ctx.reply_text or ""

    if mode == "all" or not keywords:
        ok = bool(source.strip())
        return ok, (ctx.matched_keyword or ("收到回复" if ok else "未收到任何回复"))

    for kw in keywords:
        hit, snippet = match_text(kw, source, "regex" if mode == "regex" else mode)
        if hit:
            return True, snippet or kw
    return False, f"回复未命中成功关键词：{keywords}"


def build_variables(ctx: RunContext) -> dict[str, Any]:
    return {
        "task": ctx.task_name,
        "target": ctx.target_label,
        "last_reply": "",
        "date": time.strftime("%Y-%m-%d"),
        **ctx.variables,
    }


__all__ = [
    "RunContext",
    "StepError",
    "StepTimeout",
    "run_flow",
    "apply_success_rule",
    "build_variables",
]
