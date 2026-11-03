"""SQLite: tin nhắn, bản tóm tắt, phản hồi, danh sách VIP/từ khóa/bỏ qua, cài đặt."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Incoming

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER, chat_title TEXT, chat_kind TEXT, chat_username TEXT,
    msg_id INTEGER, sender_id INTEGER, sender_name TEXT, sender_username TEXT,
    text TEXT, date TEXT, link TEXT,
    -- pending: chờ tóm tắt | notified: đã báo ngay | skipped: bỏ qua (giờ nghỉ, /interval off)
    -- summarized: đã nằm trong bản tóm tắt
    status TEXT,
    rule_kind TEXT, rule_value TEXT, rule_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, date);

CREATE TABLE IF NOT EXISTS digest_items (
    id INTEGER PRIMARY KEY,
    created_at TEXT, title TEXT, summary TEXT, important INTEGER, reason TEXT,
    message_ids TEXT,
    feedback TEXT  -- NULL | ok | wrong
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    created_at TEXT, kind TEXT, value TEXT, label TEXT, lesson TEXT,
    status TEXT,  -- pending | accepted | rejected | revised (đã được viết lại theo góp ý)
    item_id INTEGER, corrected INTEGER
);

CREATE TABLE IF NOT EXISTS lists (
    kind TEXT,  -- vip | keyword | ignore
    key TEXT, label TEXT,
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY, at TEXT, purpose TEXT, input_tokens INTEGER, output_tokens INTEGER
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Storage:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(proposals)")}
        for col in ("item_id", "corrected"):
            if col not in cols:
                self.db.execute(f"ALTER TABLE proposals ADD COLUMN {col} INTEGER")

    # ---------- cài đặt ----------
    def get_setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def seed_keywords(self, keywords: list[str]) -> None:
        if self.get_setting("seeded"):
            return
        for kw in keywords:
            self.list_add("keyword", kw.casefold(), kw)
        self.set_setting("seeded", True)

    # ---------- danh sách VIP / từ khóa / bỏ qua ----------
    def list_add(self, kind: str, key: str, label: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO lists(kind, key, label) VALUES (?, ?, ?)",
                              (kind, key, label))
        self.db.commit()
        return cur.rowcount > 0

    def list_remove(self, kind: str, key: str) -> bool:
        cur = self.db.execute("DELETE FROM lists WHERE kind=? AND key=?", (kind, key))
        self.db.commit()
        return cur.rowcount > 0

    def list_items(self, kind: str) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT key, label FROM lists WHERE kind=? ORDER BY rowid", (kind,))
        return [(r["key"], r["label"]) for r in rows]

    def list_map(self, kind: str) -> dict[str, str]:
        return dict(self.list_items(kind))

    # ---------- tin nhắn ----------
    def add_message(self, m: Incoming, status: str, rule=None) -> int:
        cur = self.db.execute(
            """INSERT INTO messages(chat_id, chat_title, chat_kind, chat_username, msg_id,
               sender_id, sender_name, sender_username, text, date, link, status,
               rule_kind, rule_value, rule_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m.chat_id, m.chat_title, m.chat_kind, m.chat_username, m.msg_id, m.sender_id,
             m.sender_name, m.sender_username, m.text, m.date.astimezone(timezone.utc).isoformat(),
             m.link, status, rule.kind if rule else None, rule.value if rule else None,
             rule.reason if rule else None))
        self.db.commit()
        return cur.lastrowid

    def get_message(self, row_id: int):
        return self.db.execute("SELECT * FROM messages WHERE id=?", (row_id,)).fetchone()

    def messages_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM messages WHERE status=? ORDER BY date, id",
                               (status,)).fetchall()

    def set_status(self, ids: list[int], status: str) -> None:
        self.db.executemany("UPDATE messages SET status=? WHERE id=?", [(status, i) for i in ids])
        self.db.commit()

    def recent_in_chat(self, chat_id: int, before_id: int, limit: int) -> list[sqlite3.Row]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE chat_id=? AND id<? ORDER BY id DESC LIMIT ?",
            (chat_id, before_id, limit)).fetchall()
        return list(reversed(rows))

    def purge_older_than(self, days: int) -> None:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        self.db.execute("DELETE FROM messages WHERE date<? AND status!='pending'",
                        (cutoff,))
        self.db.execute("DELETE FROM digest_items WHERE created_at<?", (cutoff,))
        self.db.execute("DELETE FROM proposals WHERE created_at<?", (cutoff,))
        self.db.commit()

    # ---------- bản tóm tắt ----------
    def add_digest_item(self, title: str, summary: str, important: bool, reason: str,
                        message_ids: list[int]) -> int:
        cur = self.db.execute(
            """INSERT INTO digest_items(created_at, title, summary, important, reason, message_ids)
               VALUES (?,?,?,?,?,?)""",
            (utcnow().isoformat(), title, summary, int(important), reason, json.dumps(message_ids)))
        self.db.commit()
        return cur.lastrowid

    def get_digest_item(self, item_id: int):
        return self.db.execute("SELECT * FROM digest_items WHERE id=?", (item_id,)).fetchone()

    def set_feedback(self, item_id: int, feedback: str) -> None:
        self.db.execute("UPDATE digest_items SET feedback=? WHERE id=?", (feedback, item_id))
        self.db.commit()

    # ---------- đề xuất bài học ----------
    def add_proposal(self, kind: str, value: str, label: str, lesson: str,
                     item_id: int | None = None, corrected: bool = False) -> int:
        cur = self.db.execute(
            """INSERT INTO proposals(created_at, kind, value, label, lesson, status, item_id, corrected)
               VALUES (?,?,?,?,?, 'pending', ?, ?)""",
            (utcnow().isoformat(), kind, value, label, lesson, item_id, int(corrected)))
        self.db.commit()
        return cur.lastrowid

    def get_proposal(self, pid: int):
        return self.db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()

    def set_proposal_status(self, pid: int, status: str) -> None:
        self.db.execute("UPDATE proposals SET status=? WHERE id=?", (status, pid))
        self.db.commit()

    # ---------- thống kê ----------
    def log_usage(self, purpose: str, input_tokens: int, output_tokens: int) -> None:
        self.db.execute("INSERT INTO ai_usage(at, purpose, input_tokens, output_tokens) VALUES (?,?,?,?)",
                        (utcnow().isoformat(), purpose, input_tokens, output_tokens))
        self.db.commit()

    def usage_since(self, since: datetime) -> tuple[int, int, int]:
        r = self.db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o "
            "FROM ai_usage WHERE at>=?", (since.astimezone(timezone.utc).isoformat(),)).fetchone()
        return r["n"], r["i"], r["o"]

    def message_counts_since(self, since: datetime) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) n FROM messages WHERE date>=? GROUP BY status",
                               (since.astimezone(timezone.utc).isoformat(),))
        return {r["status"]: r["n"] for r in rows}
