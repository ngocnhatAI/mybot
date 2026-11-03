"""Định dạng tin gửi cho bạn (HTML của Telegram)."""

import sqlite3
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

TELEGRAM_LIMIT = 3800  # giới hạn thật là 4096, chừa chỗ cho thẻ HTML


def local_time(iso: str, tz: ZoneInfo, fmt: str = "%H:%M") -> str:
    return datetime.fromisoformat(iso).astimezone(tz).strftime(fmt)


def link_html(url: str | None, text: str = "Mở tin") -> str:
    return f' · <a href="{escape(url, quote=True)}">{text}</a>' if url else ""


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def important_message(m: sqlite3.Row, tz: ZoneInfo) -> str:
    """Tên · (nhóm) · giờ · tin — không icon, không nút."""
    parts = [m["sender_name"]]
    if m["chat_kind"] != "private" and m["chat_title"] != m["sender_name"]:
        parts.append(m["chat_title"])
    parts += [local_time(m["date"], tz), clip(m["text"], 1500)]
    return escape(" · ".join(parts))


def digest_item(number: int, title: str, summary: str, important: bool, reason: str,
                url: str | None) -> str:
    mark = "⭐" if important else "▫️"
    return (f"{mark} <b>{number}. {escape(title)}</b>\n{escape(summary)}\n"
            f"<i>{escape(reason)}</i>{link_html(url)}")


def pack(blocks: list[str], header: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Ghép các khối thành ít tin nhắn nhất có thể mà không vượt giới hạn độ dài."""
    out, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + 2 > limit and cur != header:
            out.append(cur)
            cur = header + " (tiếp)"
        cur += "\n\n" + b
    out.append(cur)
    return out
