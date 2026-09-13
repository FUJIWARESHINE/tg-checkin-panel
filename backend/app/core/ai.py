"""AI 能力（预留接口）：识别图片中的选项并用文字作答。

启用方式：系统设置里开启 AI_ENABLED 并填写 OpenAI 兼容的 API Key / Base URL。
目前仅暴露 choose_option()，动作流的 ai_choose 步骤会调用它。
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from ..logging_setup import logger
from ..settings import settings


def is_enabled() -> bool:
    return bool(settings.ai_enabled and settings.openai_api_key)


async def choose_option(*, image_bytes: bytes, prompt: str, options: list[str]) -> str:
    """把图片交给多模态模型，返回它选择的选项文本。"""
    if not is_enabled():
        return ""

    option_hint = "、".join(options) if options else "（无预设选项，请自行判断）"
    instruction = (
        f"{prompt}\n\n可选选项：{option_hint}\n"
        "只回复你选择的那一项的原文，不要任何解释、标点或多余文字。"
    )
    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image_bytes).decode("ascii")
                        },
                    },
                ],
            }
        ],
        "max_tokens": 32,
    }
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        answer = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI 识图调用失败：%s", exc)
        return ""

    if options:
        for opt in options:
            if opt and opt in answer:
                return opt
    return answer
