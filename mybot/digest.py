"""Tổng hợp tin không quan trọng theo chu kỳ, và tóm tắt cuối giờ nghỉ."""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from . import formatting as fmt
from .ai import AI, DigestItem, format_message_line
from .config import Config
from .lessons import Lessons
from .schedule import RestSchedule
from .storage import Storage

log = logging.getLogger(__name__)

# send(text, buttons): buttons là các hàng nút, mỗi nút là (nhãn, callback_data)
Send = Callable[[str, list[list[tuple[str, str]]] | None], Awaitable[None]]

ITEMS_PER_MESSAGE = 8


def get_schedule(store: Storage) -> RestSchedule | None:
    d = store.get_setting("schedule")
    return RestSchedule.from_dict(d) if d else None


def chunk_by_size(rows: list[sqlite3.Row], lines: list[str], max_chars: int) -> list[list[int]]:
    """Chia tin thành nhiều lần gọi AI, giữ các tin cùng chat ở cạnh nhau."""
    order = sorted(range(len(rows)), key=lambda i: (rows[i]["chat_id"], rows[i]["id"]))
    chunks, cur, size = [], [], 0
    for i in order:
        n = len(lines[i]) + 1
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def fallback_items(rows: list[sqlite3.Row], note: str) -> list[DigestItem]:
    by_chat: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        by_chat.setdefault(r["chat_id"], []).append(r)
    items = []
    for msgs in by_chat.values():
        first = msgs[0]
        title = first["sender_name"] if first["chat_kind"] == "private" else first["chat_title"]
        items.append(DigestItem(
            title=title, summary=f"{len(msgs)} tin. " + fmt.clip(msgs[-1]["text"], 200),
            important=False, reason=note, message_ids=[m["id"] for m in msgs]))
    return items


class Digester:
    def __init__(self, cfg: Config, store: Storage, ai: AI, lessons: Lessons, send: Send):
        self.cfg, self.store, self.ai, self.lessons, self.send = cfg, store, ai, lessons, send

    async def tick(self, now: datetime) -> None:
        """Gọi mỗi phút. Tự quyết định đã đến lúc tóm tắt chưa."""
        sched = get_schedule(self.store)
        if sched and sched.is_resting(now):
            return

        last_iso = self.store.get_setting("last_batch_at")
        last = datetime.fromisoformat(last_iso) if last_iso else None
        rest_window = sched.last_end(now) if sched else None
        after_rest = bool(rest_window and last and last < rest_window[1])
        due = last is None or after_rest or now - last >= timedelta(minutes=self.cfg.batch_minutes)
        if not due:
            return

        self.store.set_setting("last_batch_at", now.isoformat())
        if after_rest:
            title = f"🌙 <b>Tóm tắt giờ nghỉ {sched.label()}</b>"
        else:
            title = f"🗂 <b>Tóm tắt {(last or now):%H:%M}–{now:%H:%M}</b>"
        await self.run(title)

    async def run(self, title: str) -> None:
        held = self.store.messages_by_status("held")
        pending = self.store.messages_by_status("pending")
        if held:
            await self._send_held(held)
        if pending:
            await self._send_digest(pending, title)

    async def _send_held(self, held: list[sqlite3.Row]) -> None:
        tz = self.cfg.timezone
        header = f"⭐ <b>Tin quan trọng trong giờ nghỉ ({len(held)})</b>"
        for text in fmt.pack([fmt.held_block(m, tz) for m in held], header):
            await self.send(text, None)
        self.store.set_status([m["id"] for m in held], "notified")

    async def _send_digest(self, rows: list[sqlite3.Row], title: str) -> None:
        tz = self.cfg.timezone
        lines = [format_message_line(r, fmt.local_time(r["date"], tz), self.cfg.ai.max_chars_per_message)
                 for r in rows]
        by_id = {r["id"]: r for r in rows}
        lessons = self.lessons.list()

        items: list[DigestItem] = []
        for chunk in chunk_by_size(rows, lines, self.cfg.ai.max_chars_per_request):
            chunk_rows = [rows[i] for i in chunk]
            result = await self.ai.summarize([lines[i] for i in chunk], self.cfg.about_me, lessons)
            if result is None:
                items += fallback_items(chunk_rows, "AI không tóm tắt được, đây là bản gom thô")
                continue
            valid = {r["id"] for r in chunk_rows}
            seen: set[int] = set()
            for it in result.items:
                it.message_ids = [i for i in it.message_ids if i in valid and i not in seen]
                seen.update(it.message_ids)
                if it.message_ids:
                    items.append(it)
            leftover = [r for r in chunk_rows if r["id"] not in seen]
            if leftover:
                items += fallback_items(leftover, "AI bỏ sót, bot tự gom lại")

        items.sort(key=lambda it: not it.important)
        stored = []
        for it in items:
            item_id = self.store.add_digest_item(it.title, it.summary, it.important, it.reason,
                                                 it.message_ids)
            first = by_id[it.message_ids[0]]
            stored.append((item_id, it, first["link"]))

        n_imp = sum(1 for _, it, _ in stored if it.important)
        header = f"{title}\n{len(rows)} tin · {len(stored)} đầu mục · {n_imp} ⭐"
        text, buttons = header, []
        for no, (item_id, it, url) in enumerate(stored, start=1):
            block = fmt.digest_item(no, fmt.clip(it.title, 150), fmt.clip(it.summary, 800),
                                    it.important, fmt.clip(it.reason, 200), url)
            if buttons and (len(buttons) >= ITEMS_PER_MESSAGE
                            or len(text) + len(block) + 2 > fmt.TELEGRAM_LIMIT):
                await self.send(text, buttons)
                text, buttons = f"{title} (tiếp)", []
            text += "\n\n" + block
            buttons.append([(f"{no} ✅ Đúng", f"di:{item_id}:ok"), (f"{no} ❌ Sai nhãn", f"di:{item_id}:bad")])
        if buttons:
            await self.send(text, buttons)

        self.store.set_status(list(by_id), "summarized")
