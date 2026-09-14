"""账号管理接口：CRUD + 登录（手机号/验证码/2FA/二维码）+ 会话列表。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..core.client_pool import TelegramCallError, pool
from ..core.login import login_manager
from ..db import session_scope
from ..logging_setup import logger
from ..models import Account, Task
from ..schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    DialogOut,
    LoginStateOut,
    OkOut,
    SendCodeIn,
    SendCodeOut,
    VerifyCodeIn,
    VerifyPasswordIn,
)
from ..security import decrypt, encrypt
from ..settings import settings
from ..utils.text import mask_phone
from .deps import current_user

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def session_path_for(account_id: int) -> str:
    return str(settings.sessions_dir / f"account_{account_id}")


def _hash_file(account_id: int) -> bool:
    return (settings.sessions_dir / f"account_{account_id}.session").exists()


def _to_out(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        name=account.name,
        phone=mask_phone(account.phone),
        api_id=account.api_id,
        api_hash_masked="********",
        proxy=account.proxy or "",
        status=account.status,
        is_active=account.is_active,
        me_info=account.me_info,
        has_session=bool(account.session_string) or _hash_file(account.id),
        last_login_at=account.last_login_at,
        last_active_at=account.last_active_at,
        created_at=account.created_at,
    )


async def _get_account(account_id: int) -> Account:
    async with session_scope() as session:
        account = await session.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        session.expunge(account)
        return account


@router.get("", response_model=list[AccountOut])
async def list_accounts(_: str = Depends(current_user)) -> list[AccountOut]:
    async with session_scope() as session:
        rows = (await session.execute(select(Account).order_by(Account.id))).scalars().all()
        return [_to_out(a) for a in rows]


@router.post("", response_model=AccountOut)
async def create_account(payload: AccountCreate, _: str = Depends(current_user)) -> AccountOut:
    async with session_scope() as session:
        account = Account(
            name=payload.name,
            phone=payload.phone,
            api_id=payload.api_id,
            api_hash=encrypt(payload.api_hash) or "",
            proxy=payload.proxy or "",
            session_string=encrypt(payload.session_string) or None,
            status="offline",
        )
        session.add(account)
        await session.flush()
        account.session_path = session_path_for(account.id)
        await session.flush()
        session.expunge(account)
        logger.info("新增 Telegram 账号：%s", account.name)
        return _to_out(account)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: int, payload: AccountUpdate, _: str = Depends(current_user)
) -> AccountOut:
    async with session_scope() as session:
        account = await session.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        if payload.name is not None:
            account.name = payload.name
        if payload.phone is not None:
            account.phone = payload.phone
        if payload.proxy is not None:
            account.proxy = payload.proxy
        if payload.is_active is not None:
            account.is_active = payload.is_active
        await session.flush()
        session.expunge(account)
        return _to_out(account)


@router.delete("/{account_id}", response_model=OkOut)
async def delete_account(account_id: int, _: str = Depends(current_user)) -> OkOut:
    async with session_scope() as session:
        account = await session.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        task_count = len(
            (await session.execute(select(Task.id).where(Task.account_id == account_id))).all()
        )
        if task_count:
            raise HTTPException(status_code=400, detail=f"该账号下还有 {task_count} 个任务，请先删除任务")
        await session.delete(account)

    await pool.drop(account_id)
    for suffix in (".session", ".session-journal"):
        path = settings.sessions_dir / f"account_{account_id}{suffix}"
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    logger.info("已删除账号 %s", account_id)
    return OkOut(message="账号已删除")


# ---------------------------------------------------------------- 登录


@router.post("/{account_id}/login/send-code", response_model=SendCodeOut)
async def send_code(
    account_id: int, payload: SendCodeIn, _: str = Depends(current_user)
) -> SendCodeOut:
    account = await _get_account(account_id)
    phone = payload.phone or account.phone
    api_hash = decrypt(account.api_hash) or ""
    try:
        item = await login_manager.send_code(
            account_id=account_id,
            api_id=account.api_id,
            api_hash=api_hash,
            session_path=account.session_path or session_path_for(account_id),
            phone=phone,
            proxy=account.proxy or settings.tg_proxy,
            force_sms=payload.force_sms,
        )
    except TelegramCallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with session_scope() as session:
        row = await session.get(Account, account_id)
        if row is not None:
            row.phone = phone
            row.status = "need_code"
    return SendCodeOut(
        phone_code_hash=item.phone_code_hash,
        login_token=item.token,
        hint="验证码已发送到该账号的 Telegram 客户端；若收不到可改用短信（force_sms）。",
    )


@router.post("/login/verify-code", response_model=LoginStateOut)
async def verify_code(payload: VerifyCodeIn, _: str = Depends(current_user)) -> LoginStateOut:
    try:
        item = await login_manager.verify_code(payload.login_token, payload.code)
    except TelegramCallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if item.state == "need_password":
        return LoginStateOut(state="need_password", login_token=item.token, message=item.message)
    return await _finish_login(item)


@router.post("/login/verify-password", response_model=LoginStateOut)
async def verify_password(payload: VerifyPasswordIn, _: str = Depends(current_user)) -> LoginStateOut:
    try:
        item = await login_manager.verify_password(payload.login_token, payload.password)
    except TelegramCallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _finish_login(item)


async def _finish_login(item) -> LoginStateOut:  # noqa: ANN001
    try:
        me_info = await login_manager.finalize(item)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取账号信息失败：{exc}") from exc

    async with session_scope() as session:
        account = await session.get(Account, item.account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        account.status = "online"
        account.me_info = me_info
        account.last_login_at = datetime.now(timezone.utc)
        account.phone = me_info.get("phone") or account.phone
        name = me_info.get("username") or me_info.get("first_name") or account.name
        if account.name.startswith("账号") or not account.name:
            account.name = name

    await login_manager.discard(item.token)
    await pool.drop(item.account_id)
    logger.info("账号 %s 登录成功：%s", item.account_id, me_info.get("username") or me_info.get("id"))
    return LoginStateOut(state="done", message="登录成功", account_id=item.account_id)


@router.post("/{account_id}/logout", response_model=OkOut)
async def logout_account(account_id: int, _: str = Depends(current_user)) -> OkOut:
    account = await _get_account(account_id)
    api_hash = decrypt(account.api_hash) or ""
    try:
        acct = await pool.acquire(
            account_id,
            account.api_id,
            api_hash,
            session_path=account.session_path or session_path_for(account_id),
            session_string=decrypt(account.session_string) or "",
            proxy=account.proxy or settings.tg_proxy,
        )
        raw = await acct.start()
        await acct.call(raw.log_out)
    except TelegramCallError as exc:
        logger.warning("登出时调用 Telegram 失败（继续本地清理）：%s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("登出异常（继续本地清理）：%s", exc)

    await pool.drop(account_id)
    for suffix in (".session", ".session-journal"):
        path = settings.sessions_dir / f"account_{account_id}{suffix}"
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    async with session_scope() as session:
        row = await session.get(Account, account_id)
        if row is not None:
            row.status = "offline"
            row.session_string = None
            row.me_info = None
    return OkOut(message="已登出并清除本地会话")


@router.post("/{account_id}/check", response_model=OkOut)
async def check_account(account_id: int, _: str = Depends(current_user)) -> OkOut:
    account = await _get_account(account_id)
    api_hash = decrypt(account.api_hash) or ""
    try:
        acct = await pool.acquire(
            account_id,
            account.api_id,
            api_hash,
            session_path=account.session_path or session_path_for(account_id),
            session_string=decrypt(account.session_string) or "",
            proxy=account.proxy or settings.tg_proxy,
        )
        raw = await acct.start()
        me = await acct.call(raw.get_me)
    except TelegramCallError as exc:
        async with session_scope() as session:
            row = await session.get(Account, account_id)
            if row is not None:
                row.status = "need_login" if exc.kind == "auth" else "error"
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with session_scope() as session:
        row = await session.get(Account, account_id)
        if row is not None:
            row.status = "online"
            row.last_active_at = datetime.now(timezone.utc)
            row.me_info = {
                "id": me.id,
                "username": getattr(me, "username", "") or "",
                "first_name": getattr(me, "first_name", "") or "",
            }
    return OkOut(message=f"连接正常：{getattr(me, 'username', '') or me.id}")


@router.get("/{account_id}/dialogs", response_model=list[DialogOut])
async def list_dialogs(
    account_id: int, limit: int = 300, _: str = Depends(current_user)
) -> list[DialogOut]:
    account = await _get_account(account_id)
    api_hash = decrypt(account.api_hash) or ""
    try:
        acct = await pool.acquire(
            account_id,
            account.api_id,
            api_hash,
            session_path=account.session_path or session_path_for(account_id),
            session_string=decrypt(account.session_string) or "",
            proxy=account.proxy or settings.tg_proxy,
        )
        raw = await acct.start()
        dialogs = await acct.call(raw.get_dialogs, limit=min(limit, 500))
    except TelegramCallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result: list[DialogOut] = []
    for dialog in dialogs:
        entity = dialog.entity
        is_bot = bool(getattr(entity, "bot", False))
        if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
            kind = "channel"
        elif is_bot:
            kind = "bot"
        elif getattr(entity, "participants_count", None) is not None:
            kind = "group"
        else:
            kind = "user"
        username = getattr(entity, "username", "") or ""
        chat_ref = f"@{username}" if username else str(dialog.id)
        result.append(
            DialogOut(
                id=dialog.id,
                title=dialog.name or getattr(entity, "title", "") or str(dialog.id),
                kind=kind,
                username=chat_ref,
                is_bot=is_bot,
            )
        )
    result.sort(key=lambda d: (not d.is_bot, d.title))
    return result
