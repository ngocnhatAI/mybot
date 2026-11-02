"""Xử lý nút ✅/❌ và đề xuất bài học. Mọi thay đổi chỉ được ghi khi bạn bấm Đồng ý."""

import json
from datetime import datetime
from html import escape

from . import formatting as fmt
from .ai import AI, format_message_line
from .config import Config
from .digest import Send
from .lessons import Lessons
from .storage import Storage

KIND_TEXT = {
    "note": "Ghi chú cho AI (ghi vào lessons.md, ảnh hưởng cách gán nhãn trong bản tóm tắt)",
    "keyword": "Thêm từ khóa (tin có từ này sẽ được báo ngay)",
    "vip": "Thêm VIP (tin từ người/nhóm này sẽ được báo ngay)",
}


class Feedback:
    def __init__(self, cfg: Config, store: Storage, ai: AI, lessons: Lessons, send: Send):
        self.cfg, self.store, self.ai, self.lessons, self.send = cfg, store, ai, lessons, send

    def _today(self):
        return datetime.now(self.cfg.timezone).date()

    # ---------- nút trên bản tóm tắt ----------
    async def on_digest_item(self, item_id: int, verdict: str) -> str:
        """Trả về câu ngắn hiện lên khi bấm nút."""
        item = self.store.get_digest_item(item_id)
        if not item:
            return "Đầu mục này đã hết hạn."
        if item["feedback"]:
            return "Bạn đã phản hồi đầu mục này rồi."
        self.store.set_feedback(item_id, verdict)
        if verdict == "ok":
            return "Đã ghi nhận ✅"

        corrected = not item["important"]
        rows = [r for i in json.loads(item["message_ids"]) if (r := self.store.get_message(i))]
        tz = self.cfg.timezone
        lines = [format_message_line(r, fmt.local_time(r["date"], tz), self.cfg.ai.max_chars_per_message)
                 for r in rows]
        candidates: dict[str, str] = {}
        for r in rows:
            if r["sender_id"] is not None:
                candidates[str(r["sender_id"])] = r["sender_name"]
            if r["chat_kind"] != "private":
                candidates[str(r["chat_id"])] = f"nhóm/kênh {r['chat_title']}"
        senders = [f"{k}: {v}" for k, v in candidates.items()]

        proposal = await self.ai.propose_lesson(item, lines, senders, corrected, self.lessons.list())
        if proposal is None:
            await self.send("Không tạo được đề xuất bài học lần này. Bạn có thể tự thêm bằng /vip hoặc /keyword.", None)
            return "Đã ghi nhận ❌"

        kind, value = proposal.kind, proposal.value.strip()
        if kind == "vip" and value not in candidates:
            kind = "note"
        if kind == "keyword" and not value:
            kind = "note"
        label = candidates.get(value, value) if kind != "note" else ""
        pid = self.store.add_proposal(kind, value if kind != "note" else "", label, proposal.lesson)

        await self.send(
            f"📝 <b>Đề xuất bài học</b> cho đầu mục «{escape(item['title'])}» "
            f"(sửa thành {'⭐ quan trọng' if corrected else '▫️ không quan trọng'}):\n\n"
            f"{escape(proposal.lesson)}\n\n<i>{KIND_TEXT[kind]}</i>"
            + (f"\nGiá trị: <code>{escape(label or value)}</code>" if kind != "note" else ""),
            [[("👍 Đồng ý", f"lp:{pid}:y"), ("Bỏ qua", f"lp:{pid}:n")]])
        return "Đã ghi nhận ❌, xem đề xuất bài học bên dưới"

    async def on_proposal(self, pid: int, accept: bool) -> str:
        p = self.store.get_proposal(pid)
        if not p or p["status"] != "pending":
            return "Đề xuất này đã được xử lý."
        if not accept:
            self.store.set_proposal_status(pid, "rejected")
            return "Đã bỏ qua, không ghi gì."
        if p["kind"] == "note":
            self.lessons.add(p["lesson"], self._today())
            msg = "Đã ghi vào lessons.md"
        elif p["kind"] == "keyword":
            self.store.list_add("keyword", p["value"].casefold(), p["value"])
            msg = f"Đã thêm từ khóa: {p['value']}"
        else:
            self.store.list_add("vip", p["value"], p["label"])
            msg = f"Đã thêm VIP: {p['label']}"
        self.store.set_proposal_status(pid, "accepted")
        return msg

    # ---------- nút trên thông báo báo ngay ----------
    async def on_notification(self, row_id: int, verdict: str) -> str:
        m = self.store.get_message(row_id)
        if not m:
            return "Tin này đã hết hạn."
        if verdict == "ok":
            return "Đã ghi nhận ✅"
        if m["rule_kind"] == "keyword":
            await self.send(f"Tin này được báo vì có từ khóa <b>{escape(m['rule_value'])}</b>. Bỏ từ khóa này?",
                            [[("Bỏ từ khóa", f"rm:keyword:{row_id}"), ("Giữ nguyên", "noop")]])
        elif m["rule_kind"] == "vip":
            name = self.store.list_map("vip").get(m["rule_value"], m["rule_value"])
            await self.send(f"Tin này được báo vì <b>{escape(name)}</b> là VIP. Bỏ khỏi danh sách VIP?",
                            [[("Bỏ VIP", f"rm:vip:{row_id}"), ("Giữ nguyên", "noop")]])
        else:
            return "Tin nhắc tên hoặc trả lời bạn luôn được báo ngay."
        return "Đã ghi nhận ❌"

    async def on_remove_rule(self, kind: str, row_id: int) -> str:
        m = self.store.get_message(row_id)
        if not m or m["rule_kind"] != kind:
            return "Không tìm thấy luật tương ứng."
        key = m["rule_value"].casefold() if kind == "keyword" else m["rule_value"]
        if self.store.list_remove(kind, key):
            return "Đã bỏ."
        return "Luật này đã được bỏ trước đó."
