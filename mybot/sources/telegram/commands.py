"""Lệnh và nút bấm của phần Telegram: VIP, từ khóa, giờ nghỉ."""

import itertools
import logging
from html import escape

from telethon import utils

from ...control.bot import Controller, Option
from ...core.config import Config
from ...core.rules import normalize
from ...core.schedule import RestSchedule, get_schedule, parse_hhmm
from ...core.storage import Storage

log = logging.getLogger(__name__)

HELP = """<b>Theo dõi Telegram</b>
/vip — người VIP
   Thêm: tên người, @username hoặc id (chỉ người, không thêm nhóm)
   Xóa: số thứ tự trong danh sách hoặc tên
/keyword — từ khóa (viết tắt /kw)
   Thêm: từ khóa
   Xóa: số thứ tự hoặc từ khóa
/schedule — giờ nghỉ hằng ngày

<i>Chỉ báo: tin riêng từ VIP, tin có từ khóa, tin nhắc tên hoặc trả lời bạn. Còn lại bỏ qua.</i>
Gõ nhanh: /vip add An · /vip remove 2 · /kw add gấp · /schedule 17:30 08:00"""


def list_options(add_prompt: str, remove_prompt: str) -> list[Option]:
    return [Option("List", "list"), Option("Add", "add", ask=add_prompt),
            Option("Remove", "remove", ask=remove_prompt, before="list")]


LIST_NAMES = {"vip": "VIP", "keyword": "Từ khóa"}


class TelegramCommands:
    def __init__(self, cfg: Config, controller: Controller, user, store: Storage):
        self.cfg, self.controller, self.user, self.store = cfg, controller, user, store
        self.send = controller.send
        self._picks: dict[int, tuple[str, str, str]] = {}
        self._pick_ids = itertools.count(1)

    def register(self) -> None:
        c = self.controller
        c.add_command(["/vip"], lambda a: self.cmd_list("vip", a), menu="Danh sách VIP",
                      options=list_options("Nhập tên người, @username hoặc id cần thêm (không thêm nhóm):",
                                           "Nhập số thứ tự hoặc tên người cần xóa:"))
        c.add_command(["/keyword", "/kw"], lambda a: self.cmd_list("keyword", a), menu="Từ khóa báo ngay",
                      options=list_options("Nhập từ khóa cần thêm:", "Nhập số thứ tự hoặc từ khóa cần xóa:"))
        c.add_command(["/schedule"], self.cmd_schedule, menu="Giờ nghỉ", options=[
            Option("Status"), Option("Set", ask="Nhập giờ bắt đầu và kết thúc, ví dụ 17:30 08:00:"),
            Option("Off", "off")])
        c.add_callback("pk", self._on_pick)
        c.add_help(HELP)

    # ---------- nút bấm ----------
    async def _on_pick(self, rest: str):
        return self._apply_pick(int(rest)), True

    # ---------- /vip /keyword ----------
    async def cmd_list(self, kind: str, args: list[str]) -> None:
        action = args[0].lower() if args else "list"
        value = args[1].strip() if len(args) > 1 else ""
        items = self.store.list_items(kind)

        if action == "list":
            if not items:
                await self.send(f"{LIST_NAMES[kind]}: (trống)")
                return
            lines = [f"{i}. {escape(label)}" + (f" <code>{key}</code>" if kind != "keyword" else "")
                     for i, (key, label) in enumerate(items, 1)]
            await self.send(f"<b>{LIST_NAMES[kind]}</b>\n" + "\n".join(lines))
            return

        if not value:
            await self.send(f"Thiếu giá trị. Ví dụ: /{kind} {action} ...")
            return

        if action == "remove":
            target = None
            if value.isdigit() and 1 <= int(value) <= len(items):
                target = items[int(value) - 1]
            else:
                matches = [it for it in items if normalize(value) in normalize(it[1]) or value == it[0]]
                target = matches[0] if len(matches) == 1 else None
            if not target:
                await self.send("Không tìm thấy hoặc khớp nhiều mục. Dùng số thứ tự trong lệnh list.")
                return
            self.store.list_remove(kind, target[0])
            await self.send(f"Đã bỏ khỏi {LIST_NAMES[kind]}: {escape(target[1])}")
            return

        if action != "add":
            await self.send("Dùng: list, add hoặc remove. Gõ /help để xem ví dụ.")
            return

        if kind == "keyword":
            added = self.store.list_add("keyword", value.casefold(), value)
            await self.send(f"Đã thêm từ khóa: {escape(value)}" if added else "Từ khóa này đã có.")
            return

        matches = await self._resolve(value)
        if kind == "vip":
            people = [m for m in matches if not m[0].startswith("-")]
            if matches and not people:
                await self.send("VIP chỉ áp dụng cho người (tin nhắn riêng), không thêm nhóm hoặc kênh.")
                return
            matches = people
        if not matches:
            await self.send("Không tìm thấy người hoặc nhóm nào khớp. Thử @username hoặc tên đầy đủ hơn.")
        elif len(matches) == 1:
            peer_id, name = matches[0]
            added = self.store.list_add(kind, peer_id, name)
            await self.send(f"Đã thêm vào {LIST_NAMES[kind]}: {escape(name)}" if added else "Mục này đã có.")
        else:
            rows = []
            for peer_id, name in matches[:8]:
                token = next(self._pick_ids)
                self._picks[token] = (kind, peer_id, name)
                rows.append([(name[:60], f"pk:{token}")])
            await self.send(f"Có nhiều kết quả, chọn một để thêm vào {LIST_NAMES[kind]}:", rows)

    def _apply_pick(self, token: int) -> str:
        pick = self._picks.pop(token, None)
        if not pick:
            return "Lựa chọn đã hết hạn, hãy gõ lại lệnh."
        kind, peer_id, name = pick
        added = self.store.list_add(kind, peer_id, name)
        return f"Đã thêm vào {LIST_NAMES[kind]}: {name}" if added else "Mục này đã có."

    async def _resolve(self, query: str) -> list[tuple[str, str]]:
        """Tìm người/nhóm theo @username, id hoặc một phần tên trong danh sách chat của bạn."""
        q = query.strip()
        if q.startswith("@") or "t.me/" in q or q.lstrip("-").isdigit():
            try:
                ent = await self.user.get_entity(int(q) if q.lstrip("-").isdigit() else q)
                return [(str(utils.get_peer_id(ent)), utils.get_display_name(ent))]
            except (ValueError, TypeError):
                return []
        nq = normalize(q)
        found = []
        async for d in self.user.iter_dialogs(limit=1000):
            if d.name and nq in normalize(d.name):
                found.append((str(d.id), d.name))
        exact = [f for f in found if normalize(f[1]) == nq]
        return exact or found

    # ---------- /schedule ----------
    async def cmd_schedule(self, args: list[str]) -> None:
        sched = get_schedule(self.store)
        if not args:
            if not sched:
                await self.send("Chưa đặt giờ nghỉ. Ví dụ: /schedule 17:30 08:00")
            else:
                await self.send(f"Giờ nghỉ hằng ngày: <b>{sched.label()}</b>. Tắt: /schedule off")
            return
        if args[0].lower() == "off":
            self.store.set_setting("schedule", None)
            await self.send("Đã tắt giờ nghỉ. Bot báo tin cả ngày.")
            return
        tokens = " ".join(args).split()
        try:
            start, end = parse_hhmm(tokens[0]), parse_hhmm(tokens[1])
        except (ValueError, IndexError):
            await self.send("Sai cú pháp. Ví dụ: /schedule 17:30 08:00")
            return
        if start == end:
            await self.send("Giờ bắt đầu phải khác giờ kết thúc.")
            return
        new = RestSchedule(start, end)
        self.store.set_setting("schedule", new.to_dict())
        await self.send(f"Đã đặt giờ nghỉ <b>{new.label()}</b> hằng ngày. Trong giờ nghỉ bot bỏ qua hẳn "
                        "mọi tin, hết giờ nghỉ cũng không gửi bù.")
