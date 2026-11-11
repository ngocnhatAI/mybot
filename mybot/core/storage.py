"""SQLite: danh sách VIP / từ khóa và cài đặt. Không lưu tin nhắn."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
    kind TEXT,  -- vip | keyword
    key TEXT, label TEXT,
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

# Dữ liệu của các phần đã bỏ (lưu tin nhắn, tóm tắt AI, bài học, /ignore, /interval)
OLD_TABLES = ("messages", "digest_items", "proposals", "ai_usage")
OLD_SETTINGS = ("batch_minutes", "last_batch_at", "digest_off")


class Storage:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._drop_old_data()

    def _drop_old_data(self) -> None:
        existing = {r["name"] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        dropped = [t for t in OLD_TABLES if t in existing]
        for t in dropped:
            self.db.execute(f"DROP TABLE {t}")
        self.db.execute("DELETE FROM lists WHERE kind NOT IN ('vip', 'keyword')")
        self.db.executemany("DELETE FROM settings WHERE key=?", [(k,) for k in OLD_SETTINGS])
        self.db.commit()
        if dropped:
            self.db.execute("VACUUM")  # trả lại dung lượng file

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

    # ---------- danh sách VIP / từ khóa ----------
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
