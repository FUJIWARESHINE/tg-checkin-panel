"""管理员账号存储：首次启动用环境变量初始化，之后以落盘文件为准。"""

from __future__ import annotations

import json
from typing import Any

from .logging_setup import logger
from .security import hash_password, verify_password
from .settings import settings

_ADMIN_FILE = settings.data_dir / ".admin.json"


def _read() -> dict[str, Any] | None:
    if not _ADMIN_FILE.exists():
        return None
    try:
        return json.loads(_ADMIN_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _write(data: dict[str, Any]) -> None:
    settings.ensure_dirs()
    _ADMIN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        _ADMIN_FILE.chmod(0o600)
    except OSError:
        pass


def ensure_admin() -> dict[str, Any]:
    data = _read()
    if data:
        return data
    data = {
        "username": settings.admin_username,
        "password_hash": hash_password(settings.admin_password),
        "is_default": True,
    }
    _write(data)
    logger.warning(
        "已使用环境变量初始化管理员账号（%s）。请尽快在「系统设置」里修改默认密码！",
        settings.admin_username,
    )
    return data


def verify(username: str, password: str) -> bool:
    data = ensure_admin()
    if username != data.get("username"):
        return False
    return verify_password(password, data.get("password_hash", ""))


def change_password(old_password: str, new_password: str) -> tuple[bool, str]:
    data = ensure_admin()
    if not verify_password(old_password, data.get("password_hash", "")):
        return False, "原密码不正确"
    if len(new_password) < 6:
        return False, "新密码至少 6 位"
    data["password_hash"] = hash_password(new_password)
    data["is_default"] = False
    _write(data)
    logger.info("管理员密码已更新")
    return True, "密码已更新"


def is_default_password() -> bool:
    return bool(ensure_admin().get("is_default"))


def username() -> str:
    return str(ensure_admin().get("username") or settings.admin_username)
