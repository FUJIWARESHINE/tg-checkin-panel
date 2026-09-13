"""API 依赖。"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..security import decode_token

COOKIE_NAME = "tgcp_token"


def extract_token(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME) or ""
    if not token:
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    return token


async def current_user(request: Request) -> str:
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    return str(payload.get("sub") or "admin")


def error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "message": message})
