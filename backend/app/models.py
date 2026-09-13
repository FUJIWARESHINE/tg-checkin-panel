"""ORM 模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """统一用带时区的 UTC 时间，避免 SQLite 混合格式导致比较错乱。"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def _now_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow)


class Account(Base):
    """Telegram 账号（个人号，走 MTProto）。"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="")
    api_id: Mapped[int] = mapped_column(Integer, nullable=False)
    api_hash: Mapped[str] = mapped_column(Text, nullable=False)  # 加密存储
    session_path: Mapped[str] = mapped_column(String(255), default="")
    session_string: Mapped[str | None] = mapped_column(Text, default=None)  # 加密存储
    proxy: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(24), default="offline")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    me_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = _now_col()

    tasks: Mapped[list["Task"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class TaskTemplate(Base):
    """任务模板：模板一改，所有引用它的任务同步。"""

    __tablename__ = "task_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    action_flow: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    success_rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=utcnow
    )


class Task(Base):
    """签到任务。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="")
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_templates.id", ondelete="SET NULL"), default=None
    )

    targets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    action_flow: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    schedule_type: Mapped[str] = mapped_column(String(16), default="cron")  # cron | daily | interval
    schedule_value: Mapped[str] = mapped_column(String(64), default="0 8 * * *")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    random_delay_sec: Mapped[int] = mapped_column(Integer, default=300)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=300)

    success_rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    catch_up: Mapped[bool] = mapped_column(Boolean, default=False)

    notify_channel_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    notify_on: Mapped[list[str]] = mapped_column(JSON, default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_status: Mapped[str] = mapped_column(String(16), default="")
    last_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=utcnow
    )

    account: Mapped[Account] = relationship(back_populates="tasks")


class Record(Base):
    """执行记录。"""

    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)
    task_name: Mapped[str] = mapped_column(String(128), default="")
    account_id: Mapped[int | None] = mapped_column(Integer, default=None)
    account_name: Mapped[str] = mapped_column(String(64), default="")
    target: Mapped[str] = mapped_column(String(128), default="")
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")
    status: Mapped[str] = mapped_column(String(16), default="fail")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    matched_keyword: Mapped[str] = mapped_column(String(128), default="")
    reply_snippet: Mapped[str] = mapped_column(Text, default="")
    reward_text: Mapped[str] = mapped_column(String(255), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    run_at: Mapped[datetime] = _now_col()


class NotifyChannel(Base):
    """推送渠道。"""

    __tablename__ = "notify_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 敏感值加密
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    on_events: Mapped[list[str]] = mapped_column(JSON, default=list)
    quiet_start: Mapped[str] = mapped_column(String(5), default="")
    quiet_end: Mapped[str] = mapped_column(String(5), default="")
    quiet_only_fail: Mapped[bool] = mapped_column(Boolean, default=True)
    last_result: Mapped[str] = mapped_column(Text, default="")
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = _now_col()


class AppSetting(Base):
    """通用 KV 设置。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now_col()
