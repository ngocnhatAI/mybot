"""Hội thoại soạn email: chọn template → hỏi từng chỗ trống → xem trước → Gửi / Sửa / Lưu nháp / Hủy.

Không dùng AI. Email chỉ được gửi khi bạn bấm nút Gửi.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path
from typing import Callable

from . import dates, sender
from .templates import (CC_FIELD, TO_FIELD, Template, TemplateError, choices, field_label, load_templates,
                        parse_addresses, render)
from ...control.bot import Send
from ...core.config import MailConfig

PREVIEW_BODY_LIMIT = 3000

HELP = """<b>Soạn email</b>
/mail  — chọn template rồi trả lời từng câu hỏi
/cancel  — hủy email đang soạn
Template là các file .md trong data/templates/."""

RECIPIENT_FIELDS = (TO_FIELD, CC_FIELD)


@dataclass
class Draft:
    template: Template
    values: dict[str, str] = field(default_factory=dict)
    # các bước còn phải hỏi; ô ngày tách thành "<tên>#start" và "<tên>#end"
    queue: list[str] = field(default_factory=list)
    starts: dict[str, date] = field(default_factory=dict)  # ngày bắt đầu của ô ngày đang hỏi
    editing: bool = False  # đang sửa một chỗ: trả lời xong thì quay lại xem trước
    busy: bool = False  # đang gửi / lưu nháp: chặn bấm hai lần
    # người nhận / CC: khởi tạo từ template (mặc định); Giữ nguyên / Thêm / Xóa hết
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)

    def recipients(self, name: str) -> list[str]:
        return self.to if name == TO_FIELD else self.cc

    @property
    def subject(self) -> str:
        return render(self.template.subject, self.values)

    @property
    def body(self) -> str:
        return render(self.template.body, self.values)


def steps_for(name: str) -> list[str]:
    return [f"{name}#start", f"{name}#end"] if dates.is_date_field(name) else [name]


class MailComposer:
    def __init__(self, cfg: MailConfig, templates_dir: Path, send: Send,
                 send_mail: Callable = sender.send, save_draft: Callable = sender.save_draft,
                 today: Callable[[], date] = date.today):
        self.cfg, self.templates_dir, self.send = cfg, templates_dir, send
        self._send_mail, self._save_draft = send_mail, save_draft
        self._today = today
        self.draft: Draft | None = None
        self._listing: list[str] = []

    def register(self, controller) -> None:
        controller.add_command(["/mail"], self.cmd_mail)
        controller.add_command(["/cancel"], self.cmd_cancel)
        controller.add_callback("ml", self.on_button)
        controller.add_text_handler(self.on_text)
        controller.add_help(HELP)

    # ---------- lệnh ----------
    async def cmd_mail(self, _args=None) -> None:
        templates, errors = load_templates(self.templates_dir)
        warn = ("\n\nTemplate lỗi, bị bỏ qua:\n" + "\n".join(escape(e) for e in errors)) if errors else ""
        if not templates:
            await self.send("Chưa có template. Thêm file .md vào data/templates/." + warn)
            return
        self._listing = [t.key for t in templates]
        rows = [[(t.key[:60], f"ml:p:{i}")] for i, t in enumerate(templates)]
        await self.send("Chọn template:" + warn, rows)

    async def cmd_cancel(self, _args=None) -> None:
        if not self.draft:
            await self.send("Không có email nào đang soạn.")
            return
        self.draft = None
        await self.send("Đã hủy.")

    # ---------- nút bấm ----------
    async def on_button(self, rest: str) -> tuple[str, bool]:
        action, _, arg = rest.partition(":")
        if action == "p":
            return await self._pick(int(arg)), True
        d = self.draft
        if not d:
            return "Email này đã xong hoặc đã hủy.", True
        if d.busy:
            return "Đang xử lý…", False
        step = d.queue[0] if d.queue else ""

        if action == "send":
            return await self._deliver(self._send_mail, "Đã gửi"), True
        if action == "draft":
            return await self._deliver(self._save_draft, "Đã lưu nháp"), True
        if action == "cancel":
            self.draft = None
            return "Đã hủy", True
        if action == "edit":
            rows = [[(field_label(name)[:60], f"ml:ef:{i}")] for i, name in enumerate(d.template.fields)]
            rows.append([("Quay lại", "ml:back")])
            await self.send("Sửa mục nào?", rows)
            return "Sửa", True
        if action == "ef":
            name = d.template.fields[int(arg)]
            d.queue, d.editing = steps_for(name), True
            await self._ask(d.queue[0])
            return field_label(name), True
        if action == "back":
            await self._preview()
            return "Quay lại", True

        # các nút trả lời câu hỏi đang hỏi
        if action == "keep" and step in RECIPIENT_FIELDS:
            if step == TO_FIELD and not d.to:
                return "Chưa có người nhận", False
            await self._advance()
            return "Giữ nguyên", True
        if action == "add" and step in RECIPIENT_FIELDS:
            await self.send("Nhập email cần thêm:")
            return "Thêm", True
        if action == "clr" and step in RECIPIENT_FIELDS:
            d.recipients(step).clear()
            await self.send("Đã xóa hết. Nhập email:")
            return "Xóa hết", True
        if action == "one" and step.endswith("#end"):
            await self.on_text(d.starts[step.partition("#")[0]].strftime("%d/%m/%Y"))
            return "Chỉ 1 ngày", True
        if action == "c" and choices(step):
            opts = choices(step)
            if 0 <= int(arg) < len(opts):
                await self.on_text(opts[int(arg)])
                return opts[int(arg)], True
        return "Câu hỏi này đã qua", True

    async def _pick(self, index: int) -> str:
        if not 0 <= index < len(self._listing):
            return "Danh sách đã cũ, gõ /mail lại."
        key = self._listing[index]
        templates, _ = load_templates(self.templates_dir)
        tpl = next((t for t in templates if t.key == key), None)
        if not tpl:
            return "Template không còn hoặc đang lỗi, gõ /mail lại."
        self.draft = Draft(tpl, queue=[s for f in tpl.fields for s in steps_for(f)],
                           to=list(tpl.to), cc=list(tpl.cc))
        await self._ask(self.draft.queue[0])
        return key

    # ---------- trả lời chữ ----------
    async def on_text(self, text: str) -> bool:
        d = self.draft
        if not d or not d.queue:
            return False
        step = d.queue[0]
        name, _, part = step.partition("#")

        if name in RECIPIENT_FIELDS:  # gõ email = thêm vào danh sách
            try:
                added = parse_addresses(text)
            except TemplateError as e:
                await self.send(f"{escape(str(e))}. Nhập lại:")
                return True
            if not added:
                await self.send("Nhập email:")
                return True
            current = d.recipients(name)
            current.extend(a for a in added if a.lower() not in {c.lower() for c in current})
            await self._advance()
            return True

        opts = choices(name)
        if opts:
            picked = next((o for o in opts if o.casefold() == text.strip().casefold()), None)
            if picked is None and text.strip().isdigit() and 1 <= int(text) <= len(opts):
                picked = opts[int(text) - 1]
            if picked is None:
                await self.send("Chọn một mục:", self._choice_buttons(opts))
                return True
            text = picked

        try:
            if part == "start":
                d.starts[name] = dates.parse_day(text, self._today())
            elif part == "end":
                start = d.starts[name]
                end = start if dates.is_skip(text) else dates.parse_day(text, self._today(), not_before=start)
                d.values[name] = dates.format_range(start, end)
            else:
                d.values[name] = text.strip()
        except dates.DateInputError as e:
            await self.send(f"{escape(str(e))}. Nhập lại:")
            return True
        await self._advance()
        return True

    async def _advance(self) -> None:
        """Xong bước hiện tại: hỏi bước tiếp theo, hoặc hiện bản xem trước."""
        d = self.draft
        d.queue.pop(0)
        if d.queue:
            await self._ask(d.queue[0])
        else:
            d.editing = False
            await self._preview()

    async def _ask(self, step: str) -> None:
        d = self.draft
        name, _, part = step.partition("#")
        fields = d.template.fields
        pos = f"({fields.index(name) + 1}/{len(fields)}) " if not d.editing else ""
        title = escape(field_label(name))
        buttons = None

        if name in RECIPIENT_FIELDS:
            current = d.recipients(name)
            if current:
                text = f"{title}:\n" + "\n".join(escape(a) for a in current)
                buttons = [[("Giữ nguyên", "ml:keep"), ("Thêm", "ml:add"), ("Xóa hết", "ml:clr")]]
            elif name == TO_FIELD:
                text = f"{title}? Nhập email:"
            else:
                text = f"{title}? Nhập email:"
                buttons = [[("Không CC", "ml:keep")]]
        elif choices(name):
            text = f"{title}?"
            buttons = self._choice_buttons(choices(name))
        elif part == "start":
            text = f"{title} — từ ngày? (vd 24/10)"
        elif part == "end":
            text = f"{title} — đến ngày?"
            buttons = [[("Chỉ 1 ngày", "ml:one")]]
        else:
            text = f"{title}?"
            if d.values.get(name):
                text += f"\nHiện tại: {escape(d.values[name])}"
        await self.send(pos + text, buttons)

    @staticmethod
    def _choice_buttons(opts: list[str]):
        return [[(o[:60], f"ml:c:{i}")] for i, o in enumerate(opts)]

    async def _preview(self) -> None:
        d = self.draft
        body = d.body
        if len(body) > PREVIEW_BODY_LIMIT:
            body = body[:PREVIEW_BODY_LIMIT] + "\n…(còn tiếp)"
        cc = f"\nCC: {escape(', '.join(d.cc))}" if d.cc else ""
        await self.send(
            f"<b>Xem trước</b>\n"
            f"Tới: {escape(', '.join(d.to))}{cc}\n"
            f"Tiêu đề: {escape(d.subject)}\n\n"
            f"{escape(body)}",
            [[("Gửi", "ml:send"), ("Sửa", "ml:edit")],
             [("Lưu nháp", "ml:draft"), ("Hủy", "ml:cancel")]])

    async def _deliver(self, action: Callable, done_text: str) -> str:
        d = self.draft
        d.busy = True
        try:
            msg = sender.build_message(self.cfg, d.to, d.cc, d.subject, d.body)
            await asyncio.to_thread(action, self.cfg, msg)
        except sender.MailError as e:
            d.busy = False
            await self.send(f"Lỗi: {escape(str(e))}\nEmail vẫn được giữ, bấm lại để thử.")
            await self._preview()
            return "Không thành công"
        self.draft = None
        return f"{done_text}: {', '.join(d.to)}"
