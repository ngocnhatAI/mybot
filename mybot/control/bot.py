"""Bot điều khiển dùng chung: gửi tin cho bạn, định tuyến lệnh, nút bấm và tin nhắn chữ.

Mỗi nguồn tin / kỹ năng tự đăng ký lệnh và nút của mình qua Controller.
Bot chỉ phục vụ đúng tài khoản chủ (owner_id).
"""

import logging
from html import escape
from typing import Awaitable, Callable

from telethon import Button, events

log = logging.getLogger(__name__)

Buttons = list[list[tuple[str, str]]] | None  # các hàng nút, mỗi nút là (nhãn, callback_data)
Send = Callable[[str, Buttons], Awaitable[None]]
CommandHandler = Callable[[list[str]], Awaitable[None]]
# Nút bấm: nhận phần data sau tiền tố, trả về (câu trả lời ngắn, có gỡ nút khỏi tin không)
CallbackHandler = Callable[[str], Awaitable[tuple[str, bool]]]
# Tin nhắn chữ không phải lệnh: trả về True nếu đã xử lý
TextHandler = Callable[[str], Awaitable[bool]]


class Controller:
    def __init__(self, bot, owner_id: int):
        self.bot, self.owner_id = bot, owner_id
        self._commands: dict[str, CommandHandler] = {}
        self._callbacks: dict[str, CallbackHandler] = {}
        self._text_handlers: list[TextHandler] = []
        self._help: list[str] = []

    # ---------- đăng ký ----------
    def add_command(self, names: list[str], handler: CommandHandler) -> None:
        for n in names:
            self._commands[n.lower()] = handler

    def add_callback(self, prefix: str, handler: CallbackHandler) -> None:
        self._callbacks[prefix] = handler

    def add_text_handler(self, handler: TextHandler) -> None:
        self._text_handlers.append(handler)

    def add_help(self, section: str) -> None:
        self._help.append(section)

    def register(self) -> None:
        self.add_command(["/start", "/help"], self._cmd_help)
        self.bot.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        self.bot.add_event_handler(self._on_callback, events.CallbackQuery())

    # ---------- gửi ----------
    async def send(self, text: str, buttons: Buttons = None) -> None:
        tg_buttons = [[Button.inline(lbl, data.encode()) for lbl, data in row] for row in buttons] if buttons else None
        try:
            await self.bot.send_message(self.owner_id, text, parse_mode="html", buttons=tg_buttons,
                                        link_preview=False)
        except (ValueError, TypeError) as e:
            log.error("Không gửi được cho bạn (%s). Hãy nhắn /start cho bot trên Telegram "
                      "khi bot đang chạy (chỉ cần làm một lần).", e)

    # ---------- nhận ----------
    async def _on_message(self, event) -> None:
        if event.sender_id != self.owner_id:
            return
        text = (event.raw_text or "").strip()
        try:
            if text.startswith("/"):
                parts = text.split(maxsplit=2)
                cmd = parts[0].split("@")[0].lower()
                handler = self._commands.get(cmd)
                if handler is None:
                    await self.send("Không có lệnh này. Gõ /help để xem danh sách.")
                    return
                await handler(parts[1:])
                return
            for h in self._text_handlers:
                if await h(text):
                    return
            await self.send("Gõ /help để xem các lệnh.")
        except Exception:
            log.exception("Lỗi khi xử lý tin: %s", text[:50])
            await self.send("Có lỗi khi xử lý, xem log của bot để biết chi tiết.")

    async def _on_callback(self, event) -> None:
        if event.sender_id != self.owner_id:
            return
        data = event.data.decode()
        prefix, _, rest = data.partition(":")
        handler = self._callbacks.get(prefix)
        try:
            answer, remove_buttons = await handler(rest) if handler else ("OK", True)
        except Exception:
            log.exception("Lỗi khi xử lý nút %s", data)
            answer, remove_buttons = "Có lỗi, xem log của bot.", False
        await event.answer(answer[:190])
        if remove_buttons:
            try:
                msg = await event.get_message()
                await msg.edit(f"{msg.text}\n\n<i>→ {escape(answer)}</i>", parse_mode="html", buttons=None)
            except Exception:
                log.debug("Không sửa được tin chứa nút", exc_info=True)

    async def _cmd_help(self, _args) -> None:
        await self.send("<b>Các lệnh</b>\n\n" + "\n\n".join(self._help))
