"""请求 / 响应 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .utils.cron import ScheduleError, to_cron_expression

STEP_TYPES = {
    "send_text",
    "send_dice",
    "click_button",
    "wait_reply",
    "ai_choose",
    "condition",
    "sleep",
    "extract",
}

SCHEDULE_TYPES = {"cron", "daily", "interval"}
EVENT_TYPES = {"success", "fail", "retry", "auth_expired", "scheduler_error"}


# ---------------------------------------------------------------- 通用


class Page(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[Any]


class OkOut(BaseModel):
    ok: bool = True
    message: str = ""


# ---------------------------------------------------------------- 鉴权


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    ok: bool = True
    username: str
    must_change_password: bool = False


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


# ---------------------------------------------------------------- 账号


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    phone: str = Field(default="", max_length=32)
    api_id: int
    api_hash: str = Field(min_length=8)
    proxy: str = ""
    session_string: str = ""


class AccountUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    proxy: str | None = None
    is_active: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    api_id: int
    api_hash_masked: str
    proxy: str
    status: str
    is_active: bool
    me_info: dict[str, Any] | None = None
    has_session: bool = False
    last_login_at: datetime | None = None
    last_active_at: datetime | None = None
    created_at: datetime | None = None


class SendCodeIn(BaseModel):
    phone: str = ""
    force_sms: bool = False


class SendCodeOut(BaseModel):
    ok: bool = True
    phone_code_hash: str
    login_token: str
    hint: str = ""


class VerifyCodeIn(BaseModel):
    login_token: str
    code: str = Field(min_length=1, max_length=16)


class VerifyPasswordIn(BaseModel):
    login_token: str
    password: str


class LoginStateOut(BaseModel):
    ok: bool = True
    state: Literal["need_code", "need_password", "done", "error"]
    login_token: str = ""
    message: str = ""
    account_id: int | None = None


class QrStartOut(BaseModel):
    ok: bool = True
    login_token: str
    url: str
    expires_at: datetime | None = None


class QrPollOut(BaseModel):
    ok: bool = True
    state: Literal["pending", "need_password", "done", "error"]
    message: str = ""
    account_id: int | None = None


class DialogOut(BaseModel):
    id: int
    title: str
    kind: str
    username: str = ""
    is_bot: bool = False


# ---------------------------------------------------------------- 动作流


class ActionStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str

    @field_validator("type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if value not in STEP_TYPES:
            raise ValueError(f"不支持的动作类型：{value}，可选：{', '.join(sorted(STEP_TYPES))}")
        return value


def validate_flow(flow: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(flow, list):
        raise ValueError("action_flow 必须是数组")
    if len(flow) > 50:
        raise ValueError("动作流步骤过多（上限 50）")
    return [ActionStep(**step).model_dump() for step in flow]


# ---------------------------------------------------------------- 任务


class RetryPolicy(BaseModel):
    max: int = 3
    interval_sec: int = 3600
    until_success: bool = False


class SuccessRule(BaseModel):
    mode: Literal["contains", "regex", "exact", "all"] = "contains"
    keywords: list[str] = Field(default_factory=list)


class TargetIn(BaseModel):
    chat: str
    thread_id: int | None = None


class TaskBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    remark: str = ""
    account_id: int
    template_id: int | None = None
    targets: list[TargetIn] = Field(default_factory=list)
    action_flow: list[dict[str, Any]] = Field(default_factory=list)
    schedule_type: str = "cron"
    schedule_value: str = "0 8 * * *"
    timezone: str = ""
    random_delay_sec: int = 300
    timeout_sec: int = 300
    success_rule: SuccessRule = Field(default_factory=SuccessRule)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    catch_up: bool = False
    notify_channel_ids: list[int] = Field(default_factory=list)
    notify_on: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("schedule_type")
    @classmethod
    def _check_schedule_type(cls, value: str) -> str:
        if value not in SCHEDULE_TYPES:
            raise ValueError(f"调度类型只能是 {', '.join(sorted(SCHEDULE_TYPES))}")
        return value

    @field_validator("schedule_value")
    @classmethod
    def _check_schedule_value(cls, value: str, info) -> str:
        schedule_type = info.data.get("schedule_type", "cron")
        try:
            to_cron_expression(schedule_type, value)
        except ScheduleError as exc:
            if schedule_type != "interval":
                raise ValueError(str(exc)) from exc
        return value

    @field_validator("action_flow")
    @classmethod
    def _check_flow(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_flow(value or [])

    @field_validator("notify_on")
    @classmethod
    def _check_events(cls, value: list[str]) -> list[str]:
        bad = [v for v in value or [] if v not in EVENT_TYPES]
        if bad:
            raise ValueError(f"未知事件类型：{bad}")
        return value


class TaskCreate(TaskBase):
    pass


class TaskUpdate(TaskBase):
    pass


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    remark: str
    account_id: int
    account_name: str = ""
    template_id: int | None = None
    targets: list[dict[str, Any]] = []
    action_flow: list[dict[str, Any]] = []
    schedule_type: str
    schedule_value: str
    timezone: str
    random_delay_sec: int
    timeout_sec: int
    success_rule: dict[str, Any] = {}
    retry_policy: dict[str, Any] = {}
    catch_up: bool
    notify_channel_ids: list[int] = []
    notify_on: list[str] = []
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_status: str = ""
    last_message: str = ""
    schedule_text: str = ""
    next_runs: list[datetime] = []


class TaskToggleIn(BaseModel):
    enabled: bool


class RunNowIn(BaseModel):
    force: bool = True


class TaskTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    action_flow: list[dict[str, Any]] = Field(default_factory=list)
    success_rule: SuccessRule = Field(default_factory=SuccessRule)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

    @field_validator("action_flow")
    @classmethod
    def _check_flow(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_flow(value or [])


class TaskTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    action_flow: list[dict[str, Any]]
    success_rule: dict[str, Any]
    retry_policy: dict[str, Any]
    ref_count: int = 0
    created_at: datetime | None = None


# ---------------------------------------------------------------- 记录


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int | None
    task_name: str
    account_name: str
    target: str
    trigger: str
    status: str
    attempt: int
    duration_ms: int
    matched_keyword: str
    reply_snippet: str
    reward_text: str
    error: str
    detail: dict[str, Any] | None = None
    run_at: datetime


class StatsOut(BaseModel):
    today_success: int
    today_fail: int
    today_total: int
    success_rate_7d: float
    heatmap: list[dict[str, Any]]
    recent: list[RecordOut]


# ---------------------------------------------------------------- 推送


class NotifyChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    on_events: list[str] = Field(default_factory=list)
    quiet_start: str = ""
    quiet_end: str = ""
    quiet_only_fail: bool = True

    @field_validator("on_events")
    @classmethod
    def _check_events(cls, value: list[str]) -> list[str]:
        bad = [v for v in value or [] if v not in EVENT_TYPES]
        if bad:
            raise ValueError(f"未知事件类型：{bad}")
        return value


class NotifyChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    config_masked: dict[str, Any] = {}
    enabled: bool
    on_events: list[str]
    quiet_start: str
    quiet_end: str
    quiet_only_fail: bool
    last_result: str = ""
    last_sent_at: datetime | None = None
    created_at: datetime | None = None


class TestNotifyIn(BaseModel):
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- 系统


class SystemSettingsIn(BaseModel):
    timezone: str | None = None
    tg_proxy: str | None = None
    default_random_delay_sec: int | None = None
    default_retry_max: int | None = None
    default_retry_interval: int | None = None
    task_timeout_sec: int | None = None
    max_concurrent_tasks: int | None = None
    ai_enabled: bool | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None


class SystemInfoOut(BaseModel):
    app_name: str
    version: str
    timezone: str
    proxy: str
    scheduler_running: bool
    accounts_online: int
    tasks_total: int
    tasks_enabled: int
    data_dir: str
    db_size: int
    ai_enabled: bool
    mask_hint: str
