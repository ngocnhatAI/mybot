"""Định dạng tin gửi cho bạn (HTML của Telegram)."""

from html import escape
from zoneinfo import ZoneInfo

from ...core.models import Incoming


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def important_message(m: Incoming, tz: ZoneInfo) -> str:
    """Tên · (nhóm) · giờ · tin — không icon, không nút."""
    parts = [m.sender_name]
    if m.chat_kind != "private" and m.chat_title != m.sender_name:
        parts.append(m.chat_title)
    parts += [m.date.astimezone(tz).strftime("%H:%M"), clip(m.text, 1500)]
    return escape(" · ".join(parts))
