"""Nghe tin nhắn đến trên tài khoản Telegram của bạn: tin khớp luật thì báo ngay, còn lại bỏ qua."""

import logging

from telethon import events, utils

from .formatting import important_message
from ...control.bot import Send
from ...core.models import Incoming
from ...core.rules import match_rules
from ...core.schedule import get_schedule
from ...core.storage import Storage

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
        sched = get_schedule(self.store)
        if sched and sched.is_resting(event.date.astimezone(self.tz)):
            return  # giờ nghỉ: bỏ qua hẳn

        kind = "private" if event.is_private else "group" if event.is_group else "channel"
        text = event.raw_text or ""
        if event.message.media:
            text = f"{describe_media(event.message)} {text}".strip()
        keywords = [label for _, label in self.store.list_items("keyword")]
        # Xét luật trước khi hỏi Telegram tên chat/người gửi: tin không khớp thì bỏ qua luôn
        probe = Incoming(chat_id=event.chat_id, chat_title="", chat_kind=kind, chat_username=None,
                         msg_id=event.id, sender_id=event.sender_id, sender_name="", sender_username=None,
                         text=text, mentioned=bool(event.message.mentioned), date=event.date)
        if not match_rules(probe, self.store.list_map("vip"), keywords):
            return

        chat = await event.get_chat()
        sender = await event.get_sender()
        probe.chat_title = utils.get_display_name(chat) or "?"
        probe.chat_username = getattr(chat, "username", None)
        probe.sender_name = ((utils.get_display_name(sender) if sender else None)
                             or utils.get_display_name(chat) or "?")
        probe.sender_username = getattr(sender, "username", None)
        probe.link = message_link(kind, event.chat_id, probe.chat_username, event.id)
        await self.send(important_message(probe, self.tz))
