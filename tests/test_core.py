import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from mybot.ai import DigestItem, DigestResult, LessonProposal
from mybot.config import AIConfig, Config
from mybot.digest import Digester, chunk_by_size
from mybot.feedback import Feedback
from mybot.formatting import pack
from mybot.lessons import Lessons
from mybot.listener import message_link
from mybot.models import Incoming
from mybot.rules import find_keyword, match_rules
from mybot.schedule import RestSchedule, parse_hhmm
from mybot.storage import Storage

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
    assert match_rules(msg(text="gấp"), {"42": "An"}, ["gấp"]).kind == "vip"
    assert match_rules(msg(chat_id=-1001), {"-1001": "Nhóm Sales"}, []).kind == "vip"
    assert match_rules(msg(mentioned=True, text="gấp"), {}, ["gấp"]).kind == "mention"
    assert match_rules(msg(text="gấp"), {}, ["gấp"]).kind == "keyword"
    assert match_rules(msg(), {}, ["gấp"]) is None


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
    _, end = s.last_end(datetime(2026, 11, 3, 8, 1, tzinfo=TZ))
    assert end == datetime(2026, 11, 3, 8, 0, tzinfo=TZ)


def test_schedule_same_day_and_parse():
    s = RestSchedule(parse_hhmm("12:00"), parse_hhmm("13h30"))
    assert s.is_resting(datetime(2026, 11, 2, 12, 30, tzinfo=TZ))
    assert not s.is_resting(datetime(2026, 11, 2, 14, 0, tzinfo=TZ))
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


# ---------- bài học ----------
def test_lessons_add_list_remove(tmp_path):
    ls = Lessons(tmp_path / "lessons.md")
    ls.add("Tin về báo giá là quan trọng", datetime(2026, 11, 2).date())
    ls.add("Nhóm Kho chỉ cần tóm tắt", datetime(2026, 11, 2).date())
    assert len(ls.list()) == 2
    assert "báo giá" in ls.remove(1)
    assert ls.list() == ["[2026-11-02] Nhóm Kho chỉ cần tóm tắt"]
    assert ls.remove(5) is None


def test_pack_splits_long_text():
    parts = pack(["x" * 2000, "y" * 2000, "z" * 10], "H", limit=3000)
    assert len(parts) == 2 and all(len(p) <= 3000 for p in parts)


# ---------- tóm tắt và phản hồi (AI giả) ----------
class FakeAI:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def summarize(self, lines, about_me, lessons):
        self.calls += 1
        if self.fail:
            return None
        ids = [int(l.split("]")[0][2:]) for l in lines]
        # gom tất cả trừ tin cuối vào 1 đầu mục; tin cuối cố tình bị "bỏ sót"
        return DigestResult(items=[DigestItem(title="Báo giá", summary="Khách hỏi báo giá",
                                              important=True, reason="Khách hỏi", message_ids=ids[:-1] + [999])])

    async def propose_lesson(self, item, lines, senders, corrected, lessons):
        return LessonProposal(kind="keyword", value="báo giá", lesson="Tin có 'báo giá' là quan trọng")


def make_cfg(tmp_path):
    return Config(api_id=1, api_hash="x", bot_token="x", timezone=TZ, batch_minutes=15, ai=AIConfig())


def setup(tmp_path, ai):
    cfg = make_cfg(tmp_path)
    store = Storage(tmp_path / "db.sqlite")
    lessons = Lessons(tmp_path / "lessons.md")
    sent = []

    async def send(text, buttons):
        sent.append((text, buttons))

    return cfg, store, lessons, sent, send, Digester(cfg, store, ai, lessons, send)


def test_digest_batches_every_15_minutes_and_covers_all_messages(tmp_path):
    cfg, store, lessons, sent, send, dg = setup(tmp_path, FakeAI())
    t0 = datetime(2026, 11, 2, 9, 0, tzinfo=TZ)
    asyncio.run(dg.tick(t0))  # lần đầu: không có tin, chỉ ghi mốc thời gian
    for i in range(3):
        store.add_message(msg(msg_id=i, text=f"tin {i}"), "pending")
    asyncio.run(dg.tick(t0 + timedelta(minutes=5)))
    assert sent == []
    asyncio.run(dg.tick(t0 + timedelta(minutes=15)))
    assert len(sent) == 1
    text, buttons = sent[0]
    assert "3 tin" in text and "⭐" in text
    assert len(buttons) == 2  # 1 đầu mục của AI + 1 đầu mục gom phần AI bỏ sót
    assert store.messages_by_status("pending") == []
    item = store.get_digest_item(1)
    assert 999 not in json.loads(item["message_ids"])


def test_rest_window_holds_then_summarizes_at_end(tmp_path):
    ai = FakeAI()
    cfg, store, lessons, sent, send, dg = setup(tmp_path, ai)
    store.set_setting("schedule", RestSchedule(time(17, 30), time(8, 0), "hold").to_dict())
    store.set_setting("last_batch_at", datetime(2026, 11, 2, 17, 20, tzinfo=TZ).isoformat())
    store.add_message(msg(text="việc thường"), "pending")
    store.add_message(msg(text="gấp"), "held", match_rules(msg(text="gấp"), {}, ["gấp"]))

    asyncio.run(dg.tick(datetime(2026, 11, 2, 23, 0, tzinfo=TZ)))
    asyncio.run(dg.tick(datetime(2026, 11, 3, 7, 59, tzinfo=TZ)))
    assert sent == [] and ai.calls == 0

    asyncio.run(dg.tick(datetime(2026, 11, 3, 8, 1, tzinfo=TZ)))
    assert "Tin quan trọng trong giờ nghỉ" in sent[0][0]
    assert "Tóm tắt giờ nghỉ 17:30 → 08:00" in sent[1][0]
    assert store.messages_by_status("held") == []


def test_ai_failure_falls_back_to_raw_grouping(tmp_path):
    cfg, store, lessons, sent, send, dg = setup(tmp_path, FakeAI(fail=True))
    store.add_message(msg(text="a"), "pending")
    store.add_message(msg(chat_id=-1002, chat_title="Nhóm Kho", text="b"), "pending")
    asyncio.run(dg.run("T"))
    assert len(sent[0][1]) == 2 and "AI không tóm tắt được" in sent[0][0]


def test_wrong_label_proposes_lesson_and_applies_only_after_accept(tmp_path):
    ai = FakeAI()
    cfg, store, lessons, sent, send, dg = setup(tmp_path, ai)
    row = store.add_message(msg(text="cho xin báo giá"), "summarized")
    item_id = store.add_digest_item("Báo giá", "...", False, "chào hỏi", [row])
    fb = Feedback(cfg, store, ai, lessons, send)

    asyncio.run(fb.on_digest_item(item_id, "bad"))
    assert "Đề xuất bài học" in sent[-1][0]
    assert store.list_map("keyword") == {}  # chưa đồng ý thì chưa ghi gì

    pid = int(sent[-1][1][0][0][1].split(":")[1])
    asyncio.run(fb.on_proposal(pid, True))
    assert "báo giá" in store.list_map("keyword")
    assert "đã được xử lý" in asyncio.run(fb.on_proposal(pid, True))
    assert "rồi" in asyncio.run(fb.on_digest_item(item_id, "ok"))


def test_chunking_respects_size(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    for i in range(10):
        store.add_message(msg(msg_id=i, chat_id=-(i % 3)), "pending")
    rows = store.messages_by_status("pending")
    lines = ["x" * 100] * 10
    chunks = chunk_by_size(rows, lines, 350)
    assert sorted(i for c in chunks for i in c) == list(range(10))
    assert all(len(c) <= 3 for c in chunks)
