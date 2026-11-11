import asyncio
import sqlite3
from datetime import datetime, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from mybot.core.models import Incoming
from mybot.core.rules import find_keyword, match_rules
from mybot.core.schedule import RestSchedule, parse_hhmm
from mybot.core.storage import Storage
from mybot.sources.telegram.formatting import important_message
from mybot.sources.telegram.listener import Listener, message_link

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def msg(**kw) -> Incoming:
    base = dict(chat_id=-1001, chat_title="Nhóm Sales", chat_kind="group", chat_username=None,
                msg_id=1, sender_id=42, sender_name="An", sender_username="an", text="xin chào",
                mentioned=False, date=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))
    base.update(kw)
    return Incoming(**base)


# ---------- luật ----------
def test_keyword_is_whole_word_and_case_insensitive():
    assert find_keyword("Việc này GẤP lắm", ["gấp"]) == "gấp"
    assert find_keyword("deadlines", ["deadline"]) is None
    assert find_keyword("chuyển khoản giúp mình", ["chuyển khoản"]) == "chuyển khoản"


def test_rules_priority_vip_then_mention_then_keyword():
    private = dict(chat_id=42, chat_kind="private", chat_title="An")
    assert match_rules(msg(text="gấp", **private), {"42": "An"}, ["gấp"]).kind == "vip"
    assert match_rules(msg(mentioned=True, text="gấp"), {}, ["gấp"]).kind == "mention"
    assert match_rules(msg(text="gấp"), {}, ["gấp"]).kind == "keyword"
    assert match_rules(msg(), {}, ["gấp"]) is None


def test_vip_only_counts_in_private_chats():
    # người VIP nhắn trong nhóm: không báo ngay (trừ khi nhắc tên bạn hoặc có từ khóa)
    assert match_rules(msg(sender_id=42), {"42": "An"}, []) is None
    assert match_rules(msg(sender_id=42, mentioned=True), {"42": "An"}, []).kind == "mention"
    # id nhóm có trong VIP cũng không còn tác dụng
    assert match_rules(msg(chat_id=-1001), {"-1001": "Nhóm Sales"}, []) is None


def test_message_link():
    assert message_link("group", -1001234, None, 5) == "https://t.me/c/1234/5"
    assert message_link("channel", -1001234, "tin", 5) == "https://t.me/tin/5"
    assert message_link("private", 42, "an", 5) == "https://t.me/an"
    assert message_link("private", 42, None, 5) is None


# ---------- giờ nghỉ ----------
def test_schedule_overnight():
    s = RestSchedule(time(17, 30), time(8, 0))
    assert s.is_resting(datetime(2026, 11, 2, 23, 0, tzinfo=TZ))
    assert s.is_resting(datetime(2026, 11, 3, 7, 59, tzinfo=TZ))
    assert not s.is_resting(datetime(2026, 11, 3, 8, 0, tzinfo=TZ))
    assert not s.is_resting(datetime(2026, 11, 3, 12, 0, tzinfo=TZ))
    # lịch cũ còn lưu chế độ notify/hold vẫn đọc được
    assert RestSchedule.from_dict({"start": "17:30", "end": "08:00", "mode": "hold"}).label() == "17:30 → 08:00"


def test_schedule_same_day_and_parse():
    s = RestSchedule(parse_hhmm("12:00"), parse_hhmm("13h30"))
    assert s.is_resting(datetime(2026, 11, 2, 12, 30, tzinfo=TZ))
    assert not s.is_resting(datetime(2026, 11, 2, 14, 0, tzinfo=TZ))
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


# ---------- định dạng ----------
def test_important_message_is_one_plain_line():
    private = msg(chat_kind="private", chat_title="Nguyễn Phúc Thắng", sender_name="Nguyễn Phúc Thắng",
                  text="chắc là thuyết minh hay gì đấy", date=datetime(2026, 11, 2, 10, 4, tzinfo=timezone.utc))
    assert important_message(private, TZ) == "Nguyễn Phúc Thắng · 17:04 · chắc là thuyết minh hay gì đấy"
    assert important_message(msg(text="<gấp>"), TZ) == "An · Nhóm Sales · 16:00 · &lt;gấp&gt;"


# ---------- dữ liệu cũ ----------
def test_storage_drops_old_ai_data_and_ignore_list(tmp_path):
    path = tmp_path / "db.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE messages (id INTEGER PRIMARY KEY, text TEXT);
        CREATE TABLE digest_items (id INTEGER PRIMARY KEY);
        CREATE TABLE proposals (id INTEGER PRIMARY KEY);
        CREATE TABLE ai_usage (id INTEGER PRIMARY KEY);
        CREATE TABLE lists (kind TEXT, key TEXT, label TEXT, PRIMARY KEY (kind, key));
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO messages(text) VALUES ('cũ');
        INSERT INTO lists VALUES ('vip', '42', 'An'), ('keyword', 'gấp', 'gấp'), ('ignore', '-1001', 'Nhóm');
        INSERT INTO settings VALUES ('digest_off', 'true'), ('batch_minutes', '30'), ('seeded', 'true');
    """)
    db.commit()
    db.close()

    store = Storage(path)
    tables = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"lists", "settings"}
    assert store.list_map("vip") == {"42": "An"} and store.list_map("keyword") == {"gấp": "gấp"}
    assert store.list_items("ignore") == []
    assert store.get_setting("digest_off") is None and store.get_setting("seeded") is True


# ---------- nghe tin ----------
class FakeEvent:
    def __init__(self, text="", private=False, sender_id=42, mentioned=False, hour_utc=2):
        self.out, self.chat_id, self.sender_id, self.id = False, (sender_id if private else -1001), sender_id, 7
        self.is_private, self.is_group = private, not private
        self.raw_text = text
        self.date = datetime(2026, 11, 2, hour_utc, 0, tzinfo=timezone.utc)
        self.message = SimpleNamespace(media=None, mentioned=mentioned)
        self.network_calls = 0

    async def get_chat(self):
        self.network_calls += 1
        return SimpleNamespace(title="Nhóm Sales", username=None) if not self.is_private else             SimpleNamespace(first_name="An", last_name=None, username="an")

    async def get_sender(self):
        self.network_calls += 1
        return SimpleNamespace(first_name="An", last_name=None, username="an")


def make_listener(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    store.list_add("vip", "42", "An")
    store.list_add("keyword", "gấp", "gấp")
    sent = []

    async def send(text, buttons=None):
        sent.append(text)

    return store, sent, Listener(SimpleNamespace(), store, send, TZ, skip_ids=set())


def test_listener_notifies_rule_hits_only(tmp_path, monkeypatch):
    from mybot.sources.telegram import listener
    monkeypatch.setattr(listener.utils, "get_display_name", lambda e: getattr(e, "title", None) or e.first_name)
    store, sent, lis = make_listener(tmp_path)
    run = lambda ev: asyncio.run(lis._handle(ev))

    plain = FakeEvent("xin chào")
    run(plain)
    assert sent == [] and plain.network_calls == 0  # không khớp: bỏ qua, không hỏi Telegram gì thêm

    run(FakeEvent("việc này gấp"))
    run(FakeEvent("alo", mentioned=True))
    run(FakeEvent("chào anh", private=True))  # VIP nhắn riêng
    run(FakeEvent("chào", sender_id=99, private=True))  # người thường nhắn riêng: bỏ qua
    assert len(sent) == 3
    assert sent[0] == "An · Nhóm Sales · 09:00 · việc này gấp"


def test_listener_ignores_everything_during_rest(tmp_path):
    store, sent, lis = make_listener(tmp_path)
    store.set_setting("schedule", RestSchedule(time(8, 0), time(10, 0)).to_dict())
    asyncio.run(lis._handle(FakeEvent("gấp lắm", hour_utc=2)))  # 09:00 giờ VN: đang nghỉ
    asyncio.run(lis._handle(FakeEvent("gấp lắm", hour_utc=4)))  # 11:00: báo
    assert len(sent) == 1
