"""文本工具：模板渲染、正则提取、截断、脱敏。"""

from __future__ import annotations

import re
from typing import Any

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def render_template(template: str, context: dict[str, Any]) -> str:
    """把 {var} 替换为上下文变量，未命中的原样保留。"""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key)
        if value is None:
            return match.group(0)
        return str(value)

    return _VAR_RE.sub(repl, template or "")


def match_text(pattern: str, text: str, mode: str = "contains") -> tuple[bool, str]:
    """返回 (是否命中, 命中片段)。"""
    text = text or ""
    pattern = pattern or ""
    if mode == "all":
        return True, text
    if not pattern:
        return False, ""
    if mode == "exact":
        return (text.strip() == pattern.strip()), (text.strip() if text.strip() == pattern.strip() else "")
    if mode == "regex":
        try:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        except re.error:
            return False, ""
        return (m is not None), (m.group(0) if m else "")
    # contains
    idx = text.lower().find(pattern.lower())
    if idx < 0:
        return False, ""
    return True, text[idx : idx + len(pattern)]


def match_any(keywords: list[str], text: str, mode: str = "contains") -> tuple[bool, str]:
    for kw in keywords or []:
        hit, snippet = match_text(kw, text, mode)
        if hit:
            return True, snippet
    return False, ""


def extract_group(pattern: str, text: str, group: int = 0) -> str:
    try:
        m = re.search(pattern, text or "", re.IGNORECASE | re.MULTILINE)
    except re.error:
        return ""
    if not m:
        return ""
    try:
        return m.group(group) or ""
    except IndexError:
        return ""


def truncate(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def mask_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 6:
        return "*" * len(digits)
    return f"{phone[:4]}{'*' * 4}{phone[-2:]}"


def mask_token(token: str | None) -> str:
    if not token:
        return ""
    if ":" in token:
        head, _, tail = token.partition(":")
        return f"{head}:{'*' * 6}{tail[-4:]}" if len(tail) > 4 else f"{head}:******"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}{'*' * 6}{token[-4:]}"
