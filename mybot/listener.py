"""Nghe tin nhắn đến trên tài khoản Telegram của bạn và phân loại."""

import logging

from telethon import events, utils

from .digest import Send, get_schedule
from .formatting import important_message
from .models import Incoming
from .rules import match_rules
from .storage import Storage

log = logging.getLogger(__name__)

TELEGRAM_SERVICE_ID = 777000  # tài khoản hệ thống gửi mã đăng nhập: không bao giờ đọc


def message_link(kind: str, chat_id: int, username: str | None, msg_id: int) -> str | None:
    if kind == "private":
        return f"https://t.me/{username}" if username else None
    if username:
        return f"https://t.me/{username}/{msg_id}"
    s = str(chat_id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{msg_id}"
    return None


def describe_media(msg) -> str:
    if msg.voice:
        return "[Tin nhắn thoại]"
    if msg.video_note or msg.video:
        return "[Video]"
    if msg.photo:
        return "[Ảnh]"
    if msg.sticker:
        return "[Sticker]"
    if msg.document:
        name = msg.file.name if msg.file else None
        return f"[Tệp: {name}]" if name else "[Tệp]"
    if msg.poll:
        return "[Bình chọn]"
    return "[Nội dung khác]"


class Listener:
    def __init__(self, user_client, store: Storage, send: Send, tz, skip_ids: set[int]):
        self.client, self.store, self.send, self.tz = user_client, store, send, tz
        self.skip_ids = skip_ids | {TELEGRAM_SERVICE_ID}

    def register(self) -> None:
        self.client.add_event_handler(self.on_message, events.NewMessage(incoming=True))

    async def on_message(self, event) -> None:
        try:
            await self._handle(event)
        except Exception:
            log.exception("Lỗi khi xử lý tin nhắn")

    async def _handle(self, event) -> None:
        if event.out or event.chat_id in self.skip_ids or event.sender_id in self.skip_ids:
            return
        if str(event.chat_id) in self.store.list_map("ignore"):
            return

        chat = await event.get_chat()
        sender = await event.get_sender()
        kind = "private" if event.is_private else "group" if event.is_group else "channel"
        chat_username = getattr(chat, "username", None)
        text = event.raw_text or ""
        if event.message.media and not text:
            text = describe_media(event.message)
        elif event.message.media:
            text = f"{describe_media(event.message)} {text}"

        msg = Incoming(
            chat_id=event.chat_id,
            chat_title=utils.get_display_name(chat) or "?",
            chat_kind=kind,
            chat_username=chat_username,
            msg_id=event.id,
            sender_id=event.sender_id,
            sender_name=(utils.get_display_name(sender) if sender else None) or utils.get_display_name(chat) or "?",
            sender_username=getattr(sender, "username", None),
            text=text,
            mentioned=bool(event.message.mentioned),
            date=event.date,
            link=message_link(kind, event.chat_id, chat_username, event.id),
        )

        keywords = [label for _, label in self.store.list_items("keyword")]
        hit = match_rules(msg, self.store.list_map("vip"), keywords)
        if not hit:
            self.store.add_message(msg, "pending")
            return

        sched = get_schedule(self.store)
        if sched and sched.mode == "hold" and sched.is_resting(event.date.astimezone(self.tz)):
            self.store.add_message(msg, "held", hit)
            return

        row_id = self.store.add_message(msg, "notified", hit)
        row = self.store.get_message(row_id)
        await self.send(important_message(row, self.tz),
                        [[("✅ Đúng", f"nf:{row_id}:ok"), ("❌ Không quan trọng", f"nf:{row_id}:bad")]])
