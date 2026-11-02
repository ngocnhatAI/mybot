"""Định dạng tin gửi cho bạn (HTML của Telegram)."""

import sqlite3
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

TELEGRAM_LIMIT = 3800  # giới hạn thật là 4096, chừa chỗ cho thẻ HTML


def local_time(iso: str, tz: ZoneInfo, fmt: str = "%H:%M") -> str:
    return datetime.fromisoformat(iso).astimezone(tz).strftime(fmt)


def where(m: sqlite3.Row) -> str:
    if m["chat_kind"] == "private":
        return f"👤 {escape(m['sender_name'])}"
    icon = "📢" if m["chat_kind"] == "channel" else "👥"
    return f"{icon} {escape(m['chat_title'])} · {escape(m['sender_name'])}"


def link_html(url: str | None, text: str = "Mở tin") -> str:
    return f' · <a href="{escape(url, quote=True)}">{text}</a>' if url else ""


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def important_message(m: sqlite3.Row, tz: ZoneInfo) -> str:
    return (f"⭐ <b>Tin quan trọng</b> — {where(m)}\n"
            f"<i>{escape(m['rule_reason'] or '')}</i> · {local_time(m['date'], tz)}"
            f"{link_html(m['link'])}\n\n"
            f"{escape(clip(m['text'], 1500))}")


def held_block(m: sqlite3.Row, tz: ZoneInfo) -> str:
    return (f"• {local_time(m['date'], tz, '%d/%m %H:%M')} {where(m)} — "
            f"<i>{escape(m['rule_reason'] or '')}</i>{link_html(m['link'])}\n"
            f"  {escape(clip(m['text'], 400))}")


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
