"""Telethon 客户端池：单例、引用计数、API 串行化、FloodWait 自动重试。

设计要点（借鉴 amchii/tg-signer）：
- 同一账号全局只维持一个 TelegramClient，多任务共享连接
- 所有 API 调用经由 call() 串行化，并保证最小调用间隔，避免触发风控
- 遇到 FloodWaitError 自动按服务端给的秒数等待后重试
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession

from ..logging_setup import logger
from ..settings import settings


class TelegramCallError(RuntimeError):
    """包装后的调用异常，便于上层展示。"""

    def __init__(self, message: str, *, kind: str = "unknown") -> None:
        super().__init__(message)
        self.kind = kind


def parse_proxy(raw: str | None) -> dict[str, Any] | None:
    """把 socks5://user:pass@host:port 解析成 Telethon 需要的 dict。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "socks5://" + raw
    scheme, _, rest = raw.partition("://")
    credentials, _, hostport = rest.rpartition("@")
    username = password = None
    if credentials:
        username, _, password = credentials.partition(":")
    host, _, port = hostport.partition(":")
    if not host or not port.isdigit():
        raise TelegramCallError(f"代理地址格式不正确：{raw}", kind="proxy")
    scheme = scheme.lower()
    if scheme not in ("socks5", "socks4", "http", "mtproxy"):
        raise TelegramCallError(f"不支持的代理协议：{scheme}", kind="proxy")
    proxy: dict[str, Any] = {
        "proxy_type": scheme if scheme != "http" else "http",
        "addr": host,
        "port": int(port),
        "rdns": True,
    }
    if username:
        proxy["username"] = username
        proxy["password"] = password or ""
    return proxy


class AccountClient:
    """单个账号的客户端包装。"""

    def __init__(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        session_path: str,
        session_string: str = "",
        proxy: str = "",
    ) -> None:
        self.account_id = account_id
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path
        self.session_string = session_string
        self.tz_proxy = proxy
        self._client: TelegramClient | None = None
        self._start_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        self._last_call_at = 0.0
        self.refs = 0

    # ------------------------------------------------------------ 生命周期

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise TelegramCallError("客户端尚未创建", kind="not_ready")
        return self._client

    def _build(self, start: bool = True) -> TelegramClient:
        session = StringSession(self.session_string) if self.session_string else self.session_path
        proxy = parse_proxy(self.tz_proxy or settings.tg_proxy)
        client = TelegramClient(
            session,
            self.api_id,
            self.api_hash,
            proxy=proxy,
            connection_retries=5,
            retry_delay=2,
            timeout=30,
            request_retries=5,
            auto_reconnect=True,
            device_model="tg-checkin-panel",
            system_version="Linux",
            app_version=settings.app_version,
        )
        self._client = client
        return client

    async def start(self) -> TelegramClient:
        async with self._start_lock:
            if self._client is None:
                self._build()
            client = self._client
            assert client is not None
            if not client.is_connected():
                try:
                    await client.connect()
                except Exception as exc:  # noqa: BLE001
                    raise TelegramCallError(f"连接 Telegram 失败：{exc}", kind="network") from exc
            if not await client.is_user_authorized():
                raise TelegramCallError("该账号尚未登录或 session 已失效", kind="auth")
            return client

    async def stop(self) -> None:
        async with self._start_lock:
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    # ------------------------------------------------------------ 调用

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        _retries: int = 0,
        **kwargs: Any,
    ) -> Any:
        """串行化 + 限速 + FloodWait 重试地执行一次 API 调用。"""
        async with self._call_lock:
            gap = settings.api_min_interval - (time.monotonic() - self._last_call_at)
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                result = await func(*args, **kwargs)
                self._last_call_at = time.monotonic()
                return result
            except FloodWaitError as exc:
                wait = int(getattr(exc, "seconds", 60)) + 1
                logger.warning(
                    "账号 %s 触发 FloodWait，需等待 %s 秒后重试（第 %s 次）",
                    self.account_id,
                    wait,
                    _retries + 1,
                )
                if _retries >= settings.api_max_floodwait_retries:
                    raise TelegramCallError(
                        f"Telegram 限流，需等待约 {wait} 秒", kind="floodwait"
                    ) from exc
                await asyncio.sleep(wait)
                await self.start()
                return await self.call(func, *args, _retries=_retries + 1, **kwargs)
            except RPCError as exc:
                raise TelegramCallError(
                    f"Telegram API 错误：{type(exc).__name__} {exc}", kind="rpc"
                ) from exc
            except (OSError, asyncio.TimeoutError) as exc:
                raise TelegramCallError(f"网络错误：{exc}", kind="network") from exc


class ClientPool:
    """账号 -> AccountClient 的全局池。"""

    def __init__(self) -> None:
        self._clients: dict[int, AccountClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._meta: dict[int, tuple[str, str]] = {}

    def _lock(self, account_id: int) -> asyncio.Lock:
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    async def acquire(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        session_path: str,
        session_string: str = "",
        proxy: str = "",
    ) -> AccountClient:
        async with self._lock(account_id):
            existing = self._clients.get(account_id)
            if existing is not None:
                existing.refs += 1
                return existing
            client = AccountClient(
                account_id,
                api_id,
                api_hash,
                session_path=session_path,
                session_string=session_string,
                proxy=proxy,
            )
            client.refs = 1
            self._clients[account_id] = client
            return client

    async def release(self, account_id: int) -> None:
        async with self._lock(account_id):
            client = self._clients.get(account_id)
            if client is None:
                return
            client.refs = max(0, client.refs - 1)
            if client.refs == 0:
                # 保留连接以便复用，仅在显式 drop 时断开
                pass

    async def drop(self, account_id: int) -> None:
        """删除账号或登出时调用，断开并清理。"""
        async with self._lock(account_id):
            client = self._clients.pop(account_id, None)
            self._meta.pop(account_id, None)
            if client is not None:
                await client.stop()

    def get(self, account_id: int) -> AccountClient | None:
        return self._clients.get(account_id)

    def is_online(self, account_id: int) -> bool:
        client = self._clients.get(account_id)
        return bool(client and client.connected)

    async def shutdown(self) -> None:
        for account_id in list(self._clients):
            await self.drop(account_id)


pool = ClientPool()
