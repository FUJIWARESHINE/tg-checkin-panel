"""全局配置：全部可通过环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 版本号文件的候选位置：
#   parents[2] —— 本地开发：<仓库根>/VERSION
#   parents[1] —— 容器内：/app/app/settings.py -> /app/VERSION
#   /app/VERSION —— 兜底
_VERSION_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "VERSION",
    Path(__file__).resolve().parents[1] / "VERSION",
    Path("/app/VERSION"),
)


def _default_version() -> str:
    """版本号兜底来源：VERSION 文件。

    优先级：环境变量 `APP_VERSION`（CI 打镜像时注入，等于 git tag）
    > VERSION 文件 > "0.0.0-dev"。
    """
    for candidate in _VERSION_CANDIDATES:
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value.lstrip("v")
    return "0.0.0-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # ---- 基础 ----
    app_name: str = "TG 自动签到面板"
    app_version: str = Field(default_factory=_default_version)

    @field_validator("app_version", mode="before")
    @classmethod
    def _normalize_version(cls, value: object) -> object:
        """Docker 构建时 APP_VERSION 可能是空串（本地 build 未传 build-arg），
        此时回落到 VERSION 文件，避免版本显示为空。"""
        if isinstance(value, str):
            stripped = value.strip().lstrip("v")
            return stripped or _default_version()
        return value
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- 数据目录 ----
    data_dir: Path = Path("/app/data")

    # ---- 管理端鉴权 ----
    admin_username: str = "admin"
    admin_password: str = "admin123"
    secret_key: str = ""
    master_key: str = ""
    jwt_alg: str = "HS256"
    jwt_expire_hours: int = 72
    login_rate_limit: int = 5
    login_rate_window: int = 300

    # ---- 时区 / 网络 ----
    tz: str = "Asia/Shanghai"
    tg_proxy: str = ""

    # ---- 调度默认值 ----
    default_random_delay_sec: int = 300
    default_retry_max: int = 3
    default_retry_interval: int = 3600
    task_timeout_sec: int = 300
    step_timeout_sec: int = 60
    max_concurrent_tasks: int = 3
    api_min_interval: float = 0.35
    api_max_floodwait_retries: int = 2
    log_buffer_size: int = 500

    # ---- AI（预留）----
    ai_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def master_key_file(self) -> Path:
        return self.data_dir / ".master_key"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.sessions_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
