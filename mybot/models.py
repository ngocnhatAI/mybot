from dataclasses import dataclass
from datetime import datetime


@dataclass
class Incoming:
    """Một tin nhắn đến, đã rút gọn từ sự kiện Telethon."""

    chat_id: int
    chat_title: str
    chat_kind: str  # private | group | channel
    chat_username: str | None
    msg_id: int
    sender_id: int | None
    sender_name: str
    sender_username: str | None
    text: str
    mentioned: bool
    date: datetime
    link: str | None = None


@dataclass
class RuleHit:
    kind: str  # vip | mention | keyword
    value: str
    reason: str
