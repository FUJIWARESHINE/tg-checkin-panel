"""日志：文件 + 内存环形缓冲 + 实时订阅（供 WebSocket 推送）。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime
from typing import Any

from .settings import settings

_LOGGER_NAME = "tgcheckin"


class RingBufferHandler(logging.Handler):
    """把日志塞进环形缓冲，并广播给所有订阅者。"""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.buffer: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {
                "ts": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                item["message"] += " | " + logging.Formatter().formatException(record.exc_info)
            self.buffer.append(item)
            self._broadcast(item)
        except Exception:  # noqa: BLE001 - 日志本身不能抛异常
            pass

    def _broadcast(self, item: dict[str, Any]) -> None:
        if not self._subscribers:
            return
        for queue in list(self._subscribers):
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(queue.put_nowait, item)
                else:
                    queue.put_nowait(item)
            except (RuntimeError, asyncio.QueueFull):
                self._subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        # 有界队列，防止前端卡死拖垮后端
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def tail(self, limit: int = 200, level: str | None = None, keyword: str = "") -> list[dict[str, Any]]:
        items = list(self.buffer)
        if level:
            levels = {lv.strip().upper() for lv in level.split(",") if lv.strip()}
            items = [i for i in items if i["level"] in levels]
        if keyword:
            low = keyword.lower()
            items = [i for i in items if low in i["message"].lower() or low in i["logger"].lower()]
        return items[-limit:]


ring_handler = RingBufferHandler(capacity=settings.log_buffer_size)


class PrettyFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        base = f"{ts} | {record.levelname:<7} | {record.name:<28} | {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    logger.propagate = False

    formatter = PrettyFormatter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    ring_handler.setFormatter(formatter)
    logger.addHandler(ring_handler)

    settings.ensure_dirs()
    file_handler = logging.FileHandler(settings.logs_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 让 telethon / apscheduler 的日志也汇进来
    for noisy, level in (("telethon", logging.WARNING), ("apscheduler", logging.INFO)):
        sub = logging.getLogger(noisy)
        sub.setLevel(level)
        sub.addHandler(ring_handler)

    return logger


logger = setup_logging()


def log_event(event: str, **fields: Any) -> None:
    """结构化事件日志（前端可根据 event 字段做特殊渲染）。"""
    logger.info("[%s] %s", event, json.dumps(fields, ensure_ascii=False))


def now_ts() -> float:
    return time.time()
