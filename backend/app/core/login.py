"""登录状态机：手机号 + 验证码、2FA 密码。"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from ..logging_setup import logger
from ..settings import settings
from .client_pool import TelegramCallError, parse_proxy

PENDING_TTL = 600  # 10 分钟


@dataclass
class PendingLogin:
    token: str
    account_id: int
    mode: str  # phone
    client: TelegramClient
    phone: str = ""
    phone_code_hash: str = ""
    state: str = "need_code"
    message: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > PENDING_TTL


class LoginManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingLogin] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ 通用

    def _new_token(self) -> str:
        return secrets.token_urlsafe(24)

    async def _cleanup(self) -> None:
        async with self._lock:
            for token, item in list(self._pending.items()):
                if item.expired:
                    await self._dispose(item)
                    self._pending.pop(token, None)

    async def _dispose(self, item: PendingLogin) -> None:
        try:
            await item.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def get(self, token: str) -> PendingLogin | None:
        return self._pending.get(token)

    async def _put(self, item: PendingLogin) -> None:
        await self._cleanup()
        async with self._lock:
            self._pending[item.token] = item

    async def discard(self, token: str) -> None:
        item = self._pending.pop(token, None)
        if item:
            await self._dispose(item)

    # ------------------------------------------------------------ 构建

    def build_client(self, api_id: int, api_hash: str, session_path: str, proxy: str) -> TelegramClient:
        return TelegramClient(
            session_path,
            api_id,
            api_hash,
            proxy=parse_proxy(proxy or settings.tg_proxy),
            connection_retries=5,
            retry_delay=2,
            timeout=30,
            device_model="tg-checkin-panel",
            system_version="Linux",
            app_version=settings.app_version,
        )

    # ------------------------------------------------------------ 手机号登录

    async def send_code(
        self,
        *,
        account_id: int,
        api_id: int,
        api_hash: str,
        session_path: str,
        phone: str,
        proxy: str = "",
        force_sms: bool = False,
    ) -> PendingLogin:
        if not phone:
            raise TelegramCallError("请填写手机号（含国家区号，例如 +8613800000000）", kind="input")
        client = self.build_client(api_id, api_hash, session_path, proxy)
        try:
            await client.connect()
        except Exception as exc:  # noqa: BLE001
            raise TelegramCallError(f"连接 Telegram 失败：{exc}（请检查网络或代理）", kind="network") from exc

        try:
            sent = await client.send_code_request(phone, force_sms=force_sms)
        except Exception as exc:  # noqa: BLE001
            await client.disconnect()
            raise TelegramCallError(f"发送验证码失败：{exc}", kind="rpc") from exc

        item = PendingLogin(
            token=self._new_token(),
            account_id=account_id,
            mode="phone",
            client=client,
            phone=phone,
            phone_code_hash=sent.phone_code_hash,
            state="need_code",
        )
        await self._put(item)
        logger.info("账号 %s 已发送登录验证码", account_id)
        return item

    async def verify_code(self, token: str, code: str) -> PendingLogin:
        item = self._pending.get(token)
        if item is None:
            raise TelegramCallError("登录会话不存在或已过期，请重新获取验证码", kind="state")
        if item.expired:
            await self.discard(token)
            raise TelegramCallError("登录会话已过期，请重新获取验证码", kind="state")

        code = code.replace(" ", "").strip()
        try:
            await item.client.sign_in(
                phone=item.phone, code=code, phone_code_hash=item.phone_code_hash
            )
        except SessionPasswordNeededError:
            item.state = "need_password"
            item.message = "该账号已开启两步验证，请输入密码"
            return item
        except PhoneCodeInvalidError as exc:
            raise TelegramCallError("验证码不正确", kind="code") from exc
        except PhoneCodeExpiredError as exc:
            raise TelegramCallError("验证码已过期，请重新获取", kind="code") from exc
        except Exception as exc:  # noqa: BLE001
            raise TelegramCallError(f"登录失败：{exc}", kind="rpc") from exc

        item.state = "done"
        item.message = "登录成功"
        return item

    async def verify_password(self, token: str, password: str) -> PendingLogin:
        item = self._pending.get(token)
        if item is None:
            raise TelegramCallError("登录会话不存在或已过期", kind="state")
        try:
            await item.client.sign_in(password=password)
        except PasswordHashInvalidError as exc:
            raise TelegramCallError("两步验证密码不正确", kind="code") from exc
        except Exception as exc:  # noqa: BLE001
            raise TelegramCallError(f"两步验证失败：{exc}", kind="rpc") from exc
        item.state = "done"
        item.message = "登录成功"
        return item

    # ------------------------------------------------------------ 收尾

    def take_session_string(self, item: PendingLogin) -> str:
        """把已登录的会话导出成 StringSession，便于加密落库。"""
        try:
            return StringSession.save(item.client.session)
        except Exception:  # noqa: BLE001
            return ""

    async def finalize(self, item: PendingLogin) -> dict[str, Any]:
        """登录成功后读取账号信息并断开临时连接（正式连接由客户端池建立）。"""
        me = await item.client.get_me()
        me_info = {
            "id": me.id,
            "username": getattr(me, "username", "") or "",
            "first_name": getattr(me, "first_name", "") or "",
            "last_name": getattr(me, "last_name", "") or "",
            "phone": getattr(me, "phone", "") or item.phone,
        }
        await item.client.disconnect()
        item.client = None  # type: ignore[assignment]
        return me_info


login_manager = LoginManager()
