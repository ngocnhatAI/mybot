"""Bot điều khiển dùng chung: gửi tin cho bạn, định tuyến lệnh, nút bấm và tin nhắn chữ.

Mỗi nguồn tin / kỹ năng tự đăng ký lệnh và nút của mình qua Controller.
Bot chỉ phục vụ đúng tài khoản chủ (owner_id).
"""

import logging
from dataclasses import dataclass
from html import escape
from typing import Awaitable, Callable

from telethon import Button, events, functions, types

log = logging.getLogger(__name__)

Buttons = list[list[tuple[str, str]]] | None  # các hàng nút, mỗi nút là (nhãn, callback_data)
Send = Callable[[str, Buttons], Awaitable[None]]
CommandHandler = Callable[[list[str]], Awaitable[None]]
# Nút bấm: nhận phần data sau tiền tố, trả về (câu trả lời ngắn, có gỡ nút khỏi tin không)
CallbackHandler = Callable[[str], Awaitable[tuple[str, bool]]]
# Tin nhắn chữ không phải lệnh: trả về True nếu đã xử lý
TextHandler = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class Option:
    """Một nút hiện ra khi gõ lệnh không kèm gì (ví dụ /vip → List / Add / Remove).

    Bấm nút = chạy lệnh với `args`. Có `ask` thì bot hỏi bạn gõ tiếp, chữ bạn gõ được nối vào
    sau `args` (bấm Add của /vip rồi gõ "An" giống hệt gõ /vip add An).
    `before`: chạy lệnh với các args này trước khi hỏi (ví dụ xem danh sách để biết số thứ tự cần xóa).
    """
    label: str
    args: str = ""
    ask: str = ""
    before: str | None = None


class Controller:
    def __init__(self, bot, owner_id: int):
        self.bot, self.owner_id = bot, owner_id
        self._commands: dict[str, CommandHandler] = {}
        self._callbacks: dict[str, CallbackHandler] = {}
        self._text_handlers: list[TextHandler] = []
        self._help: list[str] = []
        self._menu: list[tuple[str, str]] = []  # (lệnh không có "/", mô tả) hiện trong menu Telegram
        self._options: dict[str, tuple[str, str, list[Option]]] = {}  # lệnh → (tên chính, mô tả, các nút)
        self._pending: tuple[str, str] | None = None  # đang chờ bạn gõ: (lệnh, args đứng trước)
        self._quick_rows: list[list[str]] = []  # nút bàn phím dưới ô nhập (reply keyboard)
        self._quick: dict[str, str] = {}  # nhãn nút → lệnh

    def set_quick_keyboard(self, rows: list[list[tuple[str, str]]]) -> None:
        """Bàn phím nút luôn hiện dưới ô nhập. Bấm nút = gõ lệnh tương ứng.
        Lệnh chưa được đăng ký (ví dụ /mail khi chưa cấu hình Gmail) thì không hiện nút."""
        self._quick_rows, self._quick = [], {}
        for row in rows:
            kept = [(label, cmd) for label, cmd in row if cmd in self._commands]
            if kept:
                self._quick_rows.append([label for label, _ in kept])
                self._quick.update(kept)

    # ---------- đăng ký ----------
    def add_command(self, names: list[str], handler: CommandHandler, menu: str = "",
                    options: list[Option] | None = None) -> None:
        """menu: mô tả ngắn để lệnh (tên đầu tiên) hiện trong nút Menu của Telegram; bỏ trống thì không hiện.
        options: các nút hiện ra khi gõ lệnh không kèm gì; không có thì chạy lệnh như bình thường."""
        primary = names[0].lower()
        for n in names:
            self._commands[n.lower()] = handler
            if options:
                self._options[n.lower()] = (primary, menu, options)
        if menu:
            self._menu.append((primary.lstrip("/"), menu))

    def add_callback(self, prefix: str, handler: CallbackHandler) -> None:
        self._callbacks[prefix] = handler

    def add_text_handler(self, handler: TextHandler) -> None:
        self._text_handlers.append(handler)

    def add_help(self, section: str) -> None:
        self._help.append(section)

    def register(self) -> None:
        self.add_command(["/help", "/start"], self._cmd_help, menu="Danh sách lệnh")
        self.add_callback("op", self._on_option)
        self.bot.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        self.bot.add_event_handler(self._on_callback, events.CallbackQuery())

    async def publish_menu(self) -> None:
        """Đưa các lệnh có mô tả vào nút Menu của bot trên Telegram (ghi đè menu cũ)."""
        commands = [types.BotCommand(command=c, description=d) for c, d in self._menu]
        try:
            await self.bot(functions.bots.SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(), lang_code="", commands=commands))
        except Exception:
            log.warning("Không cập nhật được menu lệnh của bot", exc_info=True)

    # ---------- gửi ----------
    async def send(self, text: str, buttons: Buttons = None, keyboard: bool = False) -> None:
        """keyboard=True: gửi kèm bàn phím nút nhanh (Telegram giữ nó cho tới khi được thay)."""
        if buttons:
            tg_buttons = [[Button.inline(lbl, data.encode()) for lbl, data in row] for row in buttons]
        elif keyboard and self._quick_rows:
            tg_buttons = [[Button.text(lbl, resize=True, persistent=True) for lbl in row]
                          for row in self._quick_rows]
        else:
            tg_buttons = None
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
        text = self._quick.get(text, text)  # bấm nút bàn phím nhanh = gõ lệnh
        try:
            if text.startswith("/"):
                self._pending = None  # gõ lệnh khác = thôi không trả lời câu hỏi đang chờ
                parts = text.split(maxsplit=2)
                cmd = parts[0].split("@")[0].lower()
                handler = self._commands.get(cmd)
                if handler is None:
                    await self.send("Không có lệnh này. Gõ /help để xem danh sách.")
                    return
                if len(parts) == 1 and cmd in self._options:
                    await self._send_options(cmd)
                    return
                await handler(parts[1:])
                return
            if self._pending:
                cmd, args = self._pending
                self._pending = None
                await self._run(cmd, f"{args} {text}")
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

    # ---------- nút chọn của lệnh ----------
    async def _send_options(self, cmd: str) -> None:
        primary, title, options = self._options[cmd]
        buttons = [(o.label, f"op:{primary}:{i}") for i, o in enumerate(options)]
        rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
        await self.send(f"<b>{primary}</b>{f' — {escape(title)}' if title else ''}", rows)

    async def _run(self, cmd: str, args: str) -> None:
        await self._commands[cmd](args.split(maxsplit=1))

    async def _on_option(self, rest: str) -> tuple[str, bool]:
        cmd, _, idx = rest.rpartition(":")
        if cmd not in self._options or not idx.isdigit() or int(idx) >= len(self._options[cmd][2]):
            return "Nút đã cũ, hãy gõ lại lệnh.", True
        opt = self._options[cmd][2][int(idx)]
        if opt.ask:
            if opt.before is not None:
                await self._run(cmd, opt.before)
            self._pending = (cmd, opt.args)
            await self.send(f"{escape(opt.ask)}\n<i>(gõ lệnh khác để thôi)</i>")
        else:
            await self._run(cmd, opt.args)
        return opt.label, False  # giữ nút để bấm tiếp

    async def _cmd_help(self, _args) -> None:
        await self.send("Gõ lệnh không kèm gì để hiện nút chọn.\n\n" + "\n\n".join(self._help), keyboard=True)
