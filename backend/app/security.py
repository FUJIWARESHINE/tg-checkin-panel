"""鉴权与加密：密码哈希 / JWT / 敏感字段 Fernet 加解密 / 登录限流。"""

from __future__ import annotations

import base64
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from .settings import settings

_PREFIX = "enc::"


# ---------------------------------------------------------------- 密码


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- JWT


def _jwt_secret() -> str:
    if settings.secret_key:
        return settings.secret_key
    # 未配置时自动生成并落盘，保证重启后 token 仍有效
    key_file = settings.data_dir / ".jwt_secret"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    settings.ensure_dirs()
    value = secrets.token_urlsafe(48)
    key_file.write_text(value, encoding="utf-8")
    return value


def create_token(subject: str) -> tuple[str, int]:
    expire_seconds = settings.jwt_expire_hours * 3600
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expire_seconds)).timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_alg)
    return token, expire_seconds


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[settings.jwt_alg])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------- Fernet


def _master_key() -> bytes:
    """优先用环境变量 MASTER_KEY，否则读取/生成 data/.master_key。"""
    raw = settings.master_key
    if raw:
        return raw.encode("utf-8") if not raw.endswith("=") else raw.encode("utf-8")
    if settings.master_key_file.exists():
        return settings.master_key_file.read_bytes().strip()
    settings.ensure_dirs()
    key = Fernet.generate_key()
    settings.master_key_file.write_bytes(key)
    try:
        settings.master_key_file.chmod(0o600)
    except OSError:
        pass
    return key


_fernet: Fernet | None = None


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        raw = _master_key()
        try:
            _fernet = Fernet(raw)
        except (ValueError, TypeError):
            # 允许用户直接给一段任意字符串，做一遍 padding 归一化
            pad = base64.urlsafe_b64encode(raw.ljust(32, b"0")[:32])
            _fernet = Fernet(pad)
    return _fernet


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith(_PREFIX):
        return value
    return _PREFIX + _cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith(_PREFIX):
        return value
    try:
        return _cipher().decrypt(value[len(_PREFIX) :].encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_secret(value: str | None, head: int = 4, tail: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}{'*' * 6}{value[-tail:]}"


# ---------------------------------------------------------------- 限流


class LoginRateLimiter:
    """滑动窗口：N 次失败 / 窗口秒 内锁定。"""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        bucket = self._hits[key]
        cutoff = time.time() - settings.login_rate_window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= settings.login_rate_limit

    def retry_after(self, key: str) -> int:
        bucket = self._prune(key)
        if not bucket:
            return 0
        return max(0, int(settings.login_rate_window - (time.time() - bucket[0])))

    def record_failure(self, key: str) -> None:
        self._prune(key).append(time.time())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = LoginRateLimiter()
