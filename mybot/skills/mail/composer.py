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
/mail  — chọn template rồi bot hỏi lần lượt từng chỗ cần điền
/cancel  — hủy email đang soạn
Template là các file .md trong thư mục data/templates/ trên máy."""


@dataclass
class Draft:
    template: Template
    values: dict[str, str] = field(default_factory=dict)
    # các bước còn phải hỏi; ô ngày tách thành "<tên>#start" và "<tên>#end"
    queue: list[str] = field(default_factory=list)
    starts: dict[str, date] = field(default_factory=dict)  # ngày bắt đầu của ô ngày đang hỏi
    editing: bool = False  # đang sửa một chỗ: trả lời xong thì quay lại xem trước
    busy: bool = False  # đang gửi / lưu nháp: chặn bấm hai lần

    @property
    def to(self) -> list[str]:
        return self.template.to or parse_addresses(self.values.get(TO_FIELD, ""))

    @property
    def cc(self) -> list[str]:
        if CC_FIELD in self.values:
            return parse_addresses(self.values[CC_FIELD])
        return self.template.cc

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
        warn = ("\n\n⚠️ Template lỗi, bị bỏ qua:\n" + "\n".join(f"• {escape(e)}" for e in errors)) if errors else ""
        if not templates:
            await self.send("Chưa có template nào. Thêm file .md vào thư mục data/templates/ "
                            "(xem file mau-bao-gia.md để làm theo)." + warn)
            return
        self._listing = [t.key for t in templates]
        rows = [[(f"📄 {t.key} — {t.subject}"[:60], f"ml:p:{i}")] for i, t in enumerate(templates)]
        await self.send("<b>Chọn template để soạn email:</b>" + warn, rows)

    async def cmd_cancel(self, _args=None) -> None:
        if not self.draft:
            await self.send("Không có email nào đang soạn.")
            return
        self.draft = None
        await self.send("Đã hủy email đang soạn.")

    # ---------- nút bấm ----------
    async def on_button(self, rest: str) -> tuple[str, bool]:
        action, _, arg = rest.partition(":")
        if action == "p":
            return await self._pick(int(arg)), True
        d = self.draft
        if not d:
            return "Email này đã được gửi, lưu hoặc hủy rồi.", True
        if d.busy:
            return "Đang xử lý, chờ chút…", False
        if action == "send":
            return await self._deliver(self._send_mail, "Đã gửi"), True
        if action == "draft":
            return await self._deliver(self._save_draft, "Đã lưu vào Nháp của Gmail"), True
        if action == "cancel":
            self.draft = None
            return "Đã hủy, không gửi gì.", True
        if action == "edit":
            rows = [[(f"✏️ {field_label(name)}"[:60], f"ml:ef:{i}")]
                    for i, name in enumerate(d.template.editable_fields)]
            rows.append([("↩️ Quay lại xem trước", "ml:back")])
            await self.send("Chọn chỗ cần sửa:", rows)
            return "Chọn chỗ cần sửa", True
        if action == "one":
            if d.queue and d.queue[0].endswith("#end"):
                await self.on_text("-")
                return "Nghỉ 1 ngày", True
            return "OK", True
        if action == "nocc":
            if d.queue and d.queue[0] == CC_FIELD:
                await self.on_text("-")
                return "Không CC", True
            return "OK", True
        if action == "c":
            if d.queue and choices(d.queue[0]):
                opts = choices(d.queue[0])
                if 0 <= int(arg) < len(opts):
                    await self.on_text(opts[int(arg)])
                    return opts[int(arg)], True
            return "OK", True
        if action == "ef":
            name = d.template.editable_fields[int(arg)]
            d.queue, d.editing = steps_for(name), True
            await self._ask(d.queue[0])
            return f"Sửa: {field_label(name)}", True
        if action == "back":
            await self._preview()
            return "OK", True
        return "OK", True

    async def _pick(self, index: int) -> str:
        if not 0 <= index < len(self._listing):
            return "Danh sách đã cũ, gõ /mail lại."
        key = self._listing[index]
        templates, _ = load_templates(self.templates_dir)
        tpl = next((t for t in templates if t.key == key), None)
        if not tpl:
            return "Template không còn hoặc đang lỗi, gõ /mail lại."
        self.draft = Draft(tpl, queue=[s for f in tpl.fields for s in steps_for(f)])
        if self.draft.queue:
            await self._ask(self.draft.queue[0])
        else:
            await self._preview()
        return f"Soạn theo template {key}"

    # ---------- trả lời chữ ----------
    async def on_text(self, text: str) -> bool:
        d = self.draft
        if not d or not d.queue:
            return False
        step = d.queue[0]
        name, _, part = step.partition("#")
        if name in (TO_FIELD, CC_FIELD):
            if name == CC_FIELD and dates.is_skip(text):
                text = ""
            try:
                if name == TO_FIELD and not parse_addresses(text):
                    raise TemplateError("chưa nhập địa chỉ")
                parse_addresses(text)
            except TemplateError as e:
                await self.send(f"{escape(str(e))}. Nhập lại địa chỉ email (nhiều địa chỉ thì cách nhau bằng dấu phẩy):")
                return True
        opts = choices(name)
        if opts:
            picked = next((o for o in opts if o.casefold() == text.strip().casefold()), None)
            if picked is None and text.strip().isdigit() and 1 <= int(text) <= len(opts):
                picked = opts[int(text) - 1]
            if picked is None:
                await self.send("Hãy bấm một lựa chọn bên dưới:", self._choice_buttons(opts))
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
            await self.send(f"⚠️ {escape(str(e))}. Nhập lại:")
            return True
        d.queue.pop(0)
        if d.queue:
            await self._ask(d.queue[0])
        else:
            d.editing = False
            await self._preview()
        return True

    async def _ask(self, step: str) -> None:
        d = self.draft
        name, _, part = step.partition("#")
        fields = d.template.fields
        pos = f"({fields.index(name) + 1}/{len(fields)}) " if not d.editing and name in fields else ""
        current = d.values.get(name)
        if current is None and name == CC_FIELD and d.template.cc:
            current = ", ".join(d.template.cc)
        hint = f"\nHiện tại: <code>{escape(current)}</code>" if current else ""
        title = escape(field_label(name))
        buttons = None
        if choices(name):
            question = f"<b>{title}</b>? Bấm chọn bên dưới."
            buttons = self._choice_buttons(choices(name))
        elif name == CC_FIELD:
            question = (f"<b>{title}</b>? Nhiều địa chỉ cách nhau bằng dấu phẩy; "
                        "không cần CC thì bấm nút bên dưới hoặc gõ -")
            buttons = [[("Không CC", "ml:nocc")]]
        elif part == "start":
            question = f"<b>{title}</b> — ngày bắt đầu? (ví dụ 24/10)"
        elif part == "end":
            question = (f"<b>{title}</b> — ngày kết thúc? (từ {d.starts[name]:%d/%m/%Y}; "
                        "nghỉ 1 ngày thì bấm nút bên dưới hoặc gõ -)")
            buttons = [[("Chỉ nghỉ 1 ngày", "ml:one")]]
            hint = ""
        else:
            question = f"<b>{title}</b>?"
        await self.send(f"{pos}{question}{hint}\n<i>Gõ /cancel để hủy.</i>", buttons)

    @staticmethod
    def _choice_buttons(opts: list[str]):
        return [[(o[:60], f"ml:c:{i}")] for i, o in enumerate(opts)]

    async def _preview(self) -> None:
        d = self.draft
        body = d.body
        if len(body) > PREVIEW_BODY_LIMIT:
            body = body[:PREVIEW_BODY_LIMIT] + "\n…(còn tiếp)"
        cc = f"\n<b>CC:</b> {escape(', '.join(d.cc))}" if d.cc else ""
        await self.send(
            f"📧 <b>Xem trước email</b>\n"
            f"<b>Từ:</b> {escape(self.cfg.address)}\n"
            f"<b>Tới:</b> {escape(', '.join(d.to))}{cc}\n"
            f"<b>Tiêu đề:</b> {escape(d.subject)}\n\n"
            f"{escape(body)}",
            [[("✉️ Gửi", "ml:send"), ("✏️ Sửa", "ml:edit")],
             [("📝 Lưu nháp", "ml:draft"), ("❌ Hủy", "ml:cancel")]])

    async def _deliver(self, action: Callable, done_text: str) -> str:
        d = self.draft
        d.busy = True
        try:
            msg = sender.build_message(self.cfg, d.to, d.cc, d.subject, d.body)
            await asyncio.to_thread(action, self.cfg, msg)
        except sender.MailError as e:
            d.busy = False
            await self.send(f"⚠️ {escape(str(e))}\nEmail vẫn được giữ, bạn có thể bấm lại.")
            await self._preview()
            return "Không thành công"
        self.draft = None
        return f"{done_text}: {', '.join(d.to)}"
