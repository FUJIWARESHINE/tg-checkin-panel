"""鉴权接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import admin_store
from ..logging_setup import logger
from ..schemas import ChangePasswordIn, LoginIn, LoginOut, OkOut
from ..security import create_token, login_limiter
from .deps import COOKIE_NAME, current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn, request: Request, response: Response) -> LoginOut:
    key = f"{request.client.host if request.client else 'unknown'}:{payload.username}"
    if login_limiter.is_blocked(key):
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请 {login_limiter.retry_after(key)} 秒后再试",
        )
    if not admin_store.verify(payload.username, payload.password):
        login_limiter.record_failure(key)
        logger.warning("登录失败：%s", payload.username)
        raise HTTPException(status_code=401, detail="用户名或密码不正确")

    login_limiter.reset(key)
    token, max_age = create_token(payload.username)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )
    logger.info("管理员 %s 登录成功", payload.username)
    return LoginOut(username=payload.username, must_change_password=admin_store.is_default_password())


@router.post("/logout", response_model=OkOut)
async def logout(response: Response) -> OkOut:
    response.delete_cookie(COOKIE_NAME, path="/")
    return OkOut(message="已退出登录")


@router.get("/me")
async def me(user: str = Depends(current_user)) -> dict[str, object]:
    return {
        "username": user,
        "must_change_password": admin_store.is_default_password(),
    }


@router.post("/password", response_model=OkOut)
async def change_password(payload: ChangePasswordIn, user: str = Depends(current_user)) -> OkOut:
    ok, message = admin_store.change_password(payload.old_password, payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return OkOut(message=message)
