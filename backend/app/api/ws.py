"""WebSocket：实时日志推送。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..logging_setup import ring_handler
from ..security import decode_token

router = APIRouter()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket) -> None:
    # 浏览器同源 WebSocket 握手会带上 Cookie，优先用 Cookie；也兼容 ?token= 传参
    token = websocket.query_params.get("token", "") or websocket.cookies.get("tgcp_token", "")
    if not token or not decode_token(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    queue = ring_handler.subscribe()
    try:
        for item in ring_handler.tail(limit=100):
            await websocket.send_text(json.dumps(item, ensure_ascii=False))
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_text(json.dumps(item, ensure_ascii=False))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        ring_handler.unsubscribe(queue)
