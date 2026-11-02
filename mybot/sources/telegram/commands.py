"""Lệnh và nút bấm của phần Telegram: VIP, từ khóa, bỏ qua, chu kỳ, giờ nghỉ, bài học, trạng thái."""

import itertools
import logging
from datetime import datetime
from html import escape

from telethon import utils

from .digest import MAX_INTERVAL, MIN_INTERVAL, get_interval, get_schedule
from .feedback import Feedback
from ...control.bot import Controller
from ...core.config import Config
from ...core.lessons import Lessons
from ...core.rules import normalize
from ...core.schedule import MODES, RestSchedule, parse_hhmm
from ...core.storage import Storage

log = logging.getLogger(__name__)

HELP = """<b>Theo dõi Telegram</b>
/vip list | add &lt;tên, @username hoặc id&gt; | remove &lt;số hoặc tên&gt;
  Tin từ người/nhóm VIP được báo ngay.
/keyword list | add &lt;từ khóa&gt; | remove &lt;số hoặc từ&gt;  (viết tắt /kw)
  Tin có từ khóa được báo ngay.
/ignore list | add &lt;tên nhóm/người&gt; | remove &lt;số hoặc tên&gt;
  Bỏ qua hẳn chat: không đọc, không tóm tắt, không gửi AI.
/interval  — xem chu kỳ tóm tắt · /interval 30  — tóm tắt 30 phút một lần
/schedule  — xem giờ nghỉ
/schedule 17:30 08:00 notify|hold  — đặt giờ nghỉ hằng ngày
  notify: tin quan trọng vẫn báo ngay · hold: giữ tới cuối giờ nghỉ
/schedule off  — tắt giờ nghỉ
/lessons  — xem bài học · /lessons remove &lt;số&gt;
/status  — tình trạng bot và chi phí AI"""

LIST_NAMES = {"vip": "VIP", "keyword": "Từ khóa", "ignore": "Chat bỏ qua"}


class TelegramCommands:
    def __init__(self, cfg: Config, controller: Controller, user, store: Storage, lessons: Lessons,
                 feedback: Feedback):
        self.cfg, self.controller, self.user = cfg, controller, user
        self.store, self.lessons, self.feedback = store, lessons, feedback
        self.send = controller.send
        self._picks: dict[int, tuple[str, str, str]] = {}
        self._pick_ids = itertools.count(1)

    def register(self) -> None:
        c = self.controller
        c.add_command(["/vip"], lambda a: self.cmd_list("vip", a))
        c.add_command(["/keyword", "/kw"], lambda a: self.cmd_list("keyword", a))
        c.add_command(["/ignore"], lambda a: self.cmd_list("ignore", a))
        c.add_command(["/interval"], self.cmd_interval)
        c.add_command(["/schedule"], self.cmd_schedule)
        c.add_command(["/lessons"], self.cmd_lessons)
        c.add_command(["/status"], self.cmd_status)
        c.add_callback("di", self._on_digest_item)
        c.add_callback("lp", self._on_proposal)
        c.add_callback("nf", self._on_notification)
        c.add_callback("rm", self._on_remove_rule)
        c.add_callback("pk", self._on_pick)
        c.add_help(HELP)

    # ---------- nút bấm ----------
    async def _on_digest_item(self, rest: str):
        item_id, verdict = rest.split(":")
        # giữ nút: một tin tóm tắt có nhiều đầu mục
        return await self.feedback.on_digest_item(int(item_id), verdict), False

    async def _on_proposal(self, rest: str):
        pid, yn = rest.split(":")
        return await self.feedback.on_proposal(int(pid), yn == "y"), True

    async def _on_notification(self, rest: str):
        row_id, verdict = rest.split(":")
        return await self.feedback.on_notification(int(row_id), verdict), True

    async def _on_remove_rule(self, rest: str):
        list_kind, row_id = rest.split(":")
        return await self.feedback.on_remove_rule(list_kind, int(row_id)), True

    async def _on_pick(self, rest: str):
        return self._apply_pick(int(rest)), True

    # ---------- /vip /keyword /ignore ----------
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

    # ---------- /interval ----------
    async def cmd_interval(self, args: list[str]) -> None:
        current = get_interval(self.store, self.cfg)
        if not args:
            await self.send(f"Đang tóm tắt <b>{current} phút</b> một lần. Đổi bằng: /interval 30")
            return
        value = args[0].strip().lower().removesuffix("p").removesuffix("m")
        if not value.isdigit() or not MIN_INTERVAL <= int(value) <= MAX_INTERVAL:
            await self.send(f"Chu kỳ phải là số phút từ {MIN_INTERVAL} đến {MAX_INTERVAL}. Ví dụ: /interval 60")
            return
        self.store.set_setting("batch_minutes", int(value))
        await self.send(f"Đã đổi: tóm tắt <b>{int(value)} phút</b> một lần (trước đây {current} phút).")

    # ---------- /schedule ----------
    async def cmd_schedule(self, args: list[str]) -> None:
        sched = get_schedule(self.store)
        if not args:
            if not sched:
                await self.send("Chưa đặt giờ nghỉ. Ví dụ: /schedule 17:30 08:00 hold")
            else:
                await self.send(f"Giờ nghỉ hằng ngày: <b>{sched.label()}</b>, chế độ <b>{sched.mode}</b>.")
            return
        if args[0].lower() == "off":
            self.store.set_setting("schedule", None)
            await self.send("Đã tắt giờ nghỉ.")
            return
        tokens = " ".join(args).split()
        try:
            start, end = parse_hhmm(tokens[0]), parse_hhmm(tokens[1])
        except (ValueError, IndexError):
            await self.send("Sai cú pháp. Ví dụ: /schedule 17:30 08:00 hold")
            return
        mode = tokens[2].lower() if len(tokens) > 2 else (sched.mode if sched else "notify")
        if mode not in MODES or start == end:
            await self.send("Chế độ phải là notify hoặc hold, và giờ bắt đầu khác giờ kết thúc.")
            return
        new = RestSchedule(start, end, mode)
        self.store.set_setting("schedule", new.to_dict())
        explain = ("tin quan trọng vẫn báo ngay" if mode == "notify"
                   else "tin quan trọng được giữ tới cuối giờ nghỉ")
        await self.send(f"Đã đặt giờ nghỉ <b>{new.label()}</b> hằng ngày; {explain}. "
                        "Cuối giờ nghỉ bot gửi một bản tóm tắt toàn bộ.")

    # ---------- /lessons ----------
    async def cmd_lessons(self, args: list[str]) -> None:
        if args and args[0].lower() == "remove":
            if len(args) < 2 or not args[1].strip().isdigit():
                await self.send("Dùng: /lessons remove <số>")
                return
            removed = self.lessons.remove(int(args[1]))
            await self.send(f"Đã xóa: {escape(removed)}" if removed else "Không có bài học số này.")
            return
        items = self.lessons.list()
        if not items:
            await self.send("Chưa có bài học nào. Bài học được tạo khi bạn bấm ❌ Sai nhãn rồi Đồng ý.")
            return
        await self.send("<b>Bài học</b> (file data/lessons.md)\n"
                        + "\n".join(f"{i}. {escape(t)}" for i, t in enumerate(items, 1)))

    # ---------- /status ----------
    async def cmd_status(self, _args) -> None:
        tz = self.cfg.timezone
        now = datetime.now(tz)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = today.replace(day=1)
        counts = self.store.message_counts_since(today)
        calls_d, in_d, out_d = self.store.usage_since(today)
        calls_m, in_m, out_m = self.store.usage_since(month)
        p_in, p_out = self.cfg.ai.price_input_per_mtok, self.cfg.ai.price_output_per_mtok
        cost = lambda i, o: (i * p_in + o * p_out) / 1_000_000
        sched = get_schedule(self.store)
        state = "đang nghỉ" if sched and sched.is_resting(now) else "đang làm việc"
        await self.send(
            f"<b>Tình trạng</b> ({state})\n"
            f"Hôm nay: {sum(counts.values())} tin · báo ngay {counts.get('notified', 0)} · "
            f"chờ tóm tắt {counts.get('pending', 0)} · giữ trong giờ nghỉ {counts.get('held', 0)}\n"
            f"AI hôm nay: {calls_d} lần · ~{cost(in_d, out_d):.3f} USD\n"
            f"AI tháng này: {calls_m} lần · ~{cost(in_m, out_m):.2f} USD\n"
            f"VIP: {len(self.store.list_items('vip'))} · Từ khóa: {len(self.store.list_items('keyword'))} · "
            f"Bỏ qua: {len(self.store.list_items('ignore'))} · Bài học: {len(self.lessons.list())}\n"
            f"Chu kỳ tóm tắt: {get_interval(self.store, self.cfg)} phút · "
            f"Giờ nghỉ: {f'{sched.label()} ({sched.mode})' if sched else 'chưa đặt'}")
