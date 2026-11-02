"""Xử lý nút Đúng / Sai nhãn và đề xuất bài học.

Luồng bài học: Sai nhãn → AI đề xuất → bạn bấm Đồng ý / Góp ý / Bỏ qua.
Góp ý: bạn gõ ý của mình, AI viết lại bài học rồi hỏi lại. Chỉ ghi khi bạn bấm Đồng ý.
"""

import json
import sqlite3
from datetime import datetime
from html import escape

from . import formatting as fmt
from ...control.bot import Send
from ...core.ai import AI, LessonProposal, format_message_line
from ...core.config import Config
from ...core.lessons import Lessons
from ...core.storage import Storage


class Feedback:
    def __init__(self, cfg: Config, store: Storage, ai: AI, lessons: Lessons, send: Send):
        self.cfg, self.store, self.ai, self.lessons, self.send = cfg, store, ai, lessons, send
        self.awaiting_feedback: int | None = None  # id đề xuất đang chờ bạn gõ góp ý

    def _today(self):
        return datetime.now(self.cfg.timezone).date()

    def _context(self, item: sqlite3.Row) -> tuple[list[str], dict[str, str]]:
        """Tin nhắn gốc của đầu mục, và những người có thể đề xuất làm VIP (chỉ người nhắn riêng)."""
        rows = [r for i in json.loads(item["message_ids"]) if (r := self.store.get_message(i))]
        tz = self.cfg.timezone
        lines = [format_message_line(r, fmt.local_time(r["date"], tz), self.cfg.ai.max_chars_per_message)
                 for r in rows]
        candidates = {str(r["sender_id"]): r["sender_name"]
                      for r in rows if r["chat_kind"] == "private" and r["sender_id"] is not None}
        return lines, candidates

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
            return "Đã ghi nhận"

        corrected = not item["important"]
        lines, candidates = self._context(item)
        proposal = await self.ai.propose_lesson(item, lines, _sender_lines(candidates), corrected,
                                                self.lessons.list())
        if proposal is None:
            await self.send("Không tạo được đề xuất bài học. Bạn có thể tự thêm bằng /vip hoặc /keyword.")
            return "Đã ghi nhận"
        await self._store_and_show(item, corrected, proposal, candidates)
        return "Đã ghi nhận, xem đề xuất bên dưới"

    async def _store_and_show(self, item: sqlite3.Row, corrected: bool, proposal: LessonProposal,
                              candidates: dict[str, str]) -> None:
        kind, value = proposal.kind, proposal.value.strip()
        if (kind == "vip" and value not in candidates) or (kind == "keyword" and not value):
            kind = "note"
        if kind == "note":
            value = ""
        label = candidates.get(value, value)
        pid = self.store.add_proposal(kind, value, label, proposal.lesson, item["id"], corrected)

        kind_text = {
            "note": "ghi chú cho AI (lessons.md)",
            "keyword": f"thêm từ khóa «{escape(value)}» (báo ngay)",
            "vip": f"thêm VIP {escape(label)} (báo ngay khi nhắn riêng)",
        }[kind]
        await self.send(
            f"<b>Đề xuất bài học</b> — «{escape(item['title'])}»\n"
            f"Sửa thành: {'quan trọng' if corrected else 'không quan trọng'}\n\n"
            f"{escape(proposal.lesson)}\n\n"
            f"Loại: {kind_text}",
            [[("Đồng ý", f"lp:{pid}:y"), ("Góp ý", f"lp:{pid}:f"), ("Bỏ qua", f"lp:{pid}:n")]])

    # ---------- nút trên đề xuất ----------
    async def on_proposal(self, pid: int, action: str) -> str:
        p = self.store.get_proposal(pid)
        if not p or p["status"] != "pending":
            return "Đề xuất này đã được xử lý."
        if self.awaiting_feedback == pid:
            self.awaiting_feedback = None

        if action == "f":
            self.awaiting_feedback = pid
            await self.send("Nhập góp ý:")
            return "Góp ý"
        if action == "n":
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

    async def on_text(self, text: str) -> bool:
        """Nhận góp ý thô của bạn cho đề xuất đang chờ, nhờ AI viết lại bài học."""
        pid = self.awaiting_feedback
        if pid is None:
            return False
        self.awaiting_feedback = None
        p = self.store.get_proposal(pid)
        item = self.store.get_digest_item(p["item_id"]) if p and p["item_id"] else None
        if not p or p["status"] != "pending" or not item:
            await self.send("Đề xuất này đã hết hạn.")
            return True

        lines, candidates = self._context(item)
        corrected = bool(p["corrected"])
        proposal = await self.ai.propose_lesson(item, lines, _sender_lines(candidates), corrected,
                                                self.lessons.list(), previous=p["lesson"], feedback=text)
        if proposal is None:
            self.awaiting_feedback = pid
            await self.send("AI chưa viết lại được. Nhập góp ý lại:")
            return True
        self.store.set_proposal_status(pid, "revised")
        await self._store_and_show(item, corrected, proposal, candidates)
        return True

    # ---------- nút trên thông báo báo ngay ----------
    async def on_notification(self, row_id: int, verdict: str) -> str:
        m = self.store.get_message(row_id)
        if not m:
            return "Tin này đã hết hạn."
        if verdict == "ok":
            return "Đã ghi nhận"
        if m["rule_kind"] == "keyword":
            await self.send(f"Tin này được báo vì có từ khóa <b>{escape(m['rule_value'])}</b>. Bỏ từ khóa này?",
                            [[("Bỏ từ khóa", f"rm:keyword:{row_id}"), ("Giữ nguyên", "noop")]])
        elif m["rule_kind"] == "vip":
            name = self.store.list_map("vip").get(m["rule_value"], m["rule_value"])
            await self.send(f"Tin này được báo vì <b>{escape(name)}</b> là VIP. Bỏ khỏi danh sách VIP?",
                            [[("Bỏ VIP", f"rm:vip:{row_id}"), ("Giữ nguyên", "noop")]])
        else:
            return "Tin nhắc tên hoặc trả lời bạn luôn được báo ngay."
        return "Đã ghi nhận"

    async def on_remove_rule(self, kind: str, row_id: int) -> str:
        m = self.store.get_message(row_id)
        if not m or m["rule_kind"] != kind:
            return "Không tìm thấy luật tương ứng."
        key = m["rule_value"].casefold() if kind == "keyword" else m["rule_value"]
        if self.store.list_remove(kind, key):
            return "Đã bỏ."
        return "Luật này đã được bỏ trước đó."


def _sender_lines(candidates: dict[str, str]) -> list[str]:
    return [f"{k}: {v}" for k, v in candidates.items()]
