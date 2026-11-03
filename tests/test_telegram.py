import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from mybot.core.ai import DigestItem, DigestResult, LessonProposal
from mybot.core.config import AIConfig, Config
from mybot.sources.telegram.digest import Digester, chunk_by_size
from mybot.sources.telegram.feedback import Feedback
from mybot.sources.telegram.commands import TelegramCommands
from mybot.sources.telegram.formatting import important_message, pack
from mybot.core.lessons import Lessons
from mybot.sources.telegram.listener import message_link
from mybot.core.models import Incoming
from mybot.core.rules import find_keyword, match_rules
from mybot.core.schedule import RestSchedule, parse_hhmm
from mybot.core.storage import Storage

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

    async def propose_lesson(self, item, lines, senders, corrected, lessons, previous=None, feedback=None):
        self.lesson_calls = getattr(self, "lesson_calls", []) + [(senders, previous, feedback)]
        if feedback:
            return LessonProposal(kind="note", value="", lesson=f"Viết lại: {feedback}")
        return LessonProposal(kind="keyword", value="báo giá", lesson="Tin có 'báo giá' là quan trọng")


def make_cfg(tmp_path):
    return Config(api_id=1, api_hash="x", bot_token="x", timezone=TZ, batch_minutes=15, ai=AIConfig())


def setup(tmp_path, ai):
    cfg = make_cfg(tmp_path)
    store = Storage(tmp_path / "db.sqlite")
    lessons = Lessons(tmp_path / "lessons.md")
    sent = []

    async def send(text, buttons=None):
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


def test_interval_setting_overrides_config(tmp_path):
    cfg, store, lessons, sent, send, dg = setup(tmp_path, FakeAI())
    store.set_setting("batch_minutes", 30)
    t0 = datetime(2026, 11, 2, 9, 0, tzinfo=TZ)
    asyncio.run(dg.tick(t0))
    store.add_message(msg(text="a"), "pending")
    asyncio.run(dg.tick(t0 + timedelta(minutes=15)))
    assert sent == []
    asyncio.run(dg.tick(t0 + timedelta(minutes=30)))
    assert len(sent) == 1


def test_interval_off_never_summarizes(tmp_path):
    ai = FakeAI()
    cfg, store, lessons, sent, send, dg = setup(tmp_path, ai)
    controller = type("C", (), {"send": staticmethod(send)})()
    cmds = TelegramCommands(cfg, controller, None, store, lessons, None)
    store.add_message(msg(text="cũ"), "pending")

    asyncio.run(cmds.cmd_interval(["off"]))
    assert store.messages_by_status("pending") == []
    sent.clear()
    asyncio.run(dg.tick(datetime(2026, 11, 2, 9, 0, tzinfo=TZ)))
    asyncio.run(dg.tick(datetime(2026, 11, 2, 12, 0, tzinfo=TZ)))
    assert ai.calls == 0 and sent == []

    asyncio.run(cmds.cmd_interval(["15"]))
    assert "Đã bật lại" in sent[-1][0]
    assert store.get_setting("digest_off") is False


def test_important_message_is_one_plain_line(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    private = store.get_message(store.add_message(
        msg(chat_kind="private", chat_title="Nguyễn Phúc Thắng", sender_name="Nguyễn Phúc Thắng",
            text="chắc là thuyết minh hay gì đấy", date=datetime(2026, 11, 2, 10, 4, tzinfo=timezone.utc)),
        "notified"))
    assert important_message(private, TZ) == "Nguyễn Phúc Thắng · 17:04 · chắc là thuyết minh hay gì đấy"
    group = store.get_message(store.add_message(msg(text="<gấp>"), "notified"))
    assert important_message(group, TZ) == "An · Nhóm Sales · 16:00 · &lt;gấp&gt;"


def test_rest_window_is_silent_and_sends_nothing_after(tmp_path):
    ai = FakeAI()
    cfg, store, lessons, sent, send, dg = setup(tmp_path, ai)
    store.set_setting("schedule", RestSchedule(time(17, 30), time(8, 0)).to_dict())
    store.set_setting("last_batch_at", datetime(2026, 11, 2, 17, 20, tzinfo=TZ).isoformat())
    store.add_message(msg(text="trước giờ nghỉ"), "pending")

    # vào giờ nghỉ: gửi nốt phần tin trước giờ nghỉ một lần
    asyncio.run(dg.tick(datetime(2026, 11, 2, 17, 31, tzinfo=TZ)))
    assert len(sent) == 1 and "17:20–17:31" in sent[0][0]

    # trong giờ nghỉ và sau giờ nghỉ: không có gì để gửi
    for t in (datetime(2026, 11, 2, 23, 0, tzinfo=TZ), datetime(2026, 11, 3, 8, 1, tzinfo=TZ)):
        asyncio.run(dg.tick(t))
    assert len(sent) == 1 and ai.calls == 1


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

    assert [b[0] for b in sent[-1][1][0]] == ["Đồng ý", "Góp ý", "Bỏ qua"]
    pid = int(sent[-1][1][0][0][1].split(":")[1])
    asyncio.run(fb.on_proposal(pid, "y"))
    assert "báo giá" in store.list_map("keyword")
    assert "đã được xử lý" in asyncio.run(fb.on_proposal(pid, "y"))
    assert "rồi" in asyncio.run(fb.on_digest_item(item_id, "ok"))


def test_feedback_loop_rewrites_lesson_until_accepted(tmp_path):
    ai = FakeAI()
    cfg, store, lessons, sent, send, dg = setup(tmp_path, ai)
    row = store.add_message(msg(text="dc chưa"), "summarized")
    item_id = store.add_digest_item("Kha Vu hỏi", "...", True, "hỏi tiến độ", [row])
    fb = Feedback(cfg, store, ai, lessons, send)
    asyncio.run(fb.on_digest_item(item_id, "bad"))
    pid = int(sent[-1][1][0][0][1].split(":")[1])

    assert asyncio.run(fb.on_text("không liên quan")) is False  # chưa bấm Góp ý thì không bắt chữ
    asyncio.run(fb.on_proposal(pid, "f"))
    assert sent[-1][0] == "Nhập góp ý:"
    assert asyncio.run(fb.on_text("hỏi tiến độ ngắn trong nhóm thì không cần báo"))
    _, previous, feedback = ai.lesson_calls[-1]
    assert previous == "Tin có 'báo giá' là quan trọng" and feedback.startswith("hỏi tiến độ")
    assert "Viết lại: hỏi tiến độ" in sent[-1][0] and "Sửa thành: không quan trọng" in sent[-1][0]
    assert "đã được xử lý" in asyncio.run(fb.on_proposal(pid, "y"))  # đề xuất cũ không dùng được nữa

    new_pid = int(sent[-1][1][0][0][1].split(":")[1])
    asyncio.run(fb.on_proposal(new_pid, "y"))
    assert lessons.list()[0].endswith("Viết lại: hỏi tiến độ ngắn trong nhóm thì không cần báo")
    assert store.list_map("keyword") == {}


def test_lesson_never_proposes_group_senders_as_vip(tmp_path):
    ai = FakeAI()
    cfg, store, lessons, sent, send, dg = setup(tmp_path, ai)
    rows = [store.add_message(msg(text="nhóm"), "summarized"),
            store.add_message(msg(chat_id=7, chat_kind="private", sender_id=7, sender_name="Lan", text="riêng"),
                              "summarized")]
    item_id = store.add_digest_item("x", "...", False, "", rows)
    fb = Feedback(cfg, store, ai, lessons, send)
    asyncio.run(fb.on_digest_item(item_id, "bad"))
    senders, _, _ = ai.lesson_calls[-1]
    assert senders == ["7: Lan"]


def test_chunking_respects_size(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    for i in range(10):
        store.add_message(msg(msg_id=i, chat_id=-(i % 3)), "pending")
    rows = store.messages_by_status("pending")
    lines = ["x" * 100] * 10
    chunks = chunk_by_size(rows, lines, 350)
    assert sorted(i for c in chunks for i in c) == list(range(10))
    assert all(len(c) <= 3 for c in chunks)
