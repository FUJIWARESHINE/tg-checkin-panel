"""运行时可改设置：存库 + 覆盖 settings 对象的字段。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .db import session_scope
from .logging_setup import logger
from .models import AppSetting
from .security import decrypt, encrypt
from .settings import settings

# 允许在 Web 端修改的字段
EDITABLE = {
    "timezone",
    "tg_proxy",
    "default_random_delay_sec",
    "default_retry_max",
    "default_retry_interval",
    "task_timeout_sec",
    "step_timeout_sec",
    "max_concurrent_tasks",
    "ai_enabled",
    "openai_api_key",
    "openai_base_url",
    "openai_model",
}

SECRET_FIELDS = {"openai_api_key"}


async def load() -> dict[str, Any]:
    """启动时把库里保存的设置应用到 settings。"""
    applied: dict[str, Any] = {}
    async with session_scope() as session:
        rows = (await session.execute(select(AppSetting))).scalars().all()
        for row in rows:
            if row.key not in EDITABLE:
                continue
            value = row.value
            if row.key in SECRET_FIELDS and isinstance(value, str):
                value = decrypt(value) or ""
            setattr(settings, row.key, value)
            applied[row.key] = value
    if applied:
        logger.info("已应用 %s 项运行时设置", len(applied))
    return applied


async def save(values: dict[str, Any]) -> dict[str, Any]:
    """把前端传来的设置落库并立即生效。"""
    saved: dict[str, Any] = {}
    async with session_scope() as session:
        for key, value in values.items():
            if key not in EDITABLE or value is None:
                continue
            stored = encrypt(str(value)) if key in SECRET_FIELDS else value
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=stored))
            else:
                row.value = stored
            setattr(settings, key, value)
            saved[key] = "********" if key in SECRET_FIELDS and value else value
    return saved


async def current() -> dict[str, Any]:
    """返回当前生效的设置（敏感值脱敏）。"""
    return {
        "timezone": settings.tz,
        "tg_proxy": settings.tg_proxy,
        "default_random_delay_sec": settings.default_random_delay_sec,
        "default_retry_max": settings.default_retry_max,
        "default_retry_interval": settings.default_retry_interval,
        "task_timeout_sec": settings.task_timeout_sec,
        "step_timeout_sec": settings.step_timeout_sec,
        "max_concurrent_tasks": settings.max_concurrent_tasks,
        "ai_enabled": settings.ai_enabled,
        "openai_api_key": "********" if settings.openai_api_key else "",
        "openai_base_url": settings.openai_base_url,
        "openai_model": settings.openai_model,
    }
