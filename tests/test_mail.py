import asyncio
from datetime import date
from pathlib import Path

import pytest

from mybot.core.config import MailConfig
from mybot.skills.mail.composer import MailComposer
from mybot.skills.mail.dates import DateInputError, format_range, parse_day
from mybot.skills.mail.sender import MailError, build_message
from mybot.skills.mail.templates import (CC_FIELD, TO_FIELD, TemplateError, ensure_examples, load_templates,
                                         parse_template, render)

TPL = """---
to: khach@abc.com
cc: sep@gmail.com
subject: Báo giá {Dự án}
---
Kính gửi {Tên khách},
Báo giá {Dự án} là {Số tiền}.
"""

TPL_NO_TO = """---
to:
subject: Hẹn gặp
---
Chào {Tên},
"""

CFG = MailConfig(address="toi@gmail.com", app_password="x", from_name="Ngọc Nhất")


def run(coro):
    return asyncio.run(coro)


# ---------- template ----------
def test_parse_template_and_placeholders_in_order():
    t = parse_template("baogia", TPL)
    assert t.to == ["khach@abc.com"] and t.cc == ["sep@gmail.com"]
    assert t.placeholders == ["Dự án", "Tên khách", "Số tiền"]
    assert t.fields == [TO_FIELD, CC_FIELD] + t.placeholders
    assert render(t.subject, {"Dự án": "VR"}) == "Báo giá VR"


def test_template_without_recipient_asks_for_it_first():
    t = parse_template("hen", TPL_NO_TO)
    assert t.fields == [TO_FIELD, CC_FIELD, "Tên"]


@pytest.mark.parametrize("text", ["không có header", "---\nto: a@b.com\n---\nbody", "---\nsubject: x\n---\n",
                                  "---\nto: sai-dia-chi\nsubject: x\n---\nbody"])
def test_invalid_templates_are_rejected(text):
    with pytest.raises(TemplateError):
        parse_template("x", text)


def test_load_templates_reports_errors_and_examples_are_valid(tmp_path):
    d = tmp_path / "templates"
    ensure_examples(d)
    (d / "loi.md").write_text("rác", encoding="utf-8")
    templates, errors = load_templates(d)
    assert [t.key for t in templates] == ["mau-bao-gia"]
    assert len(errors) == 1 and "loi.md" in errors[0]


def test_build_message_has_utf8_headers():
    msg = build_message(CFG, ["a@b.com"], ["c@d.com"], "Báo giá", "Nội dung")
    assert msg["To"] == "a@b.com" and msg["Cc"] == "c@d.com"
    assert "Ngọc Nhất" in str(msg["From"]) and msg.get_content().strip() == "Nội dung"


# ---------- hội thoại soạn mail ----------
def make(tmp_path, send_mail=None, save_draft=None):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "baogia.md").write_text(TPL, encoding="utf-8")
    (d / "hen.md").write_text(TPL_NO_TO, encoding="utf-8")
    sent_to_owner, mails = [], []

    async def send(text, buttons=None):
        sent_to_owner.append((text, buttons))

    c = MailComposer(CFG, d, send,
                     send_mail=send_mail or (lambda cfg, msg: mails.append(msg)),
                     save_draft=save_draft or (lambda cfg, msg: mails.append(("draft", msg))))
    return c, sent_to_owner, mails


KEEP_ADD_CLEAR = [[("Giữ nguyên", "ml:keep"), ("Thêm", "ml:add"), ("Xóa hết", "ml:clr")]]


def test_full_flow_pick_fill_preview_send(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    assert out[-1][1] == [[("baogia", "ml:p:0")], [("hen", "ml:p:1")]]
    run(c.on_button("p:0"))
    assert "khach@abc.com" in out[-1][0] and out[-1][1] == KEEP_ADD_CLEAR
    run(c.on_button("keep"))
    assert "sep@gmail.com" in out[-1][0] and out[-1][1] == KEEP_ADD_CLEAR
    run(c.on_button("keep"))
    assert out[-1][0] == "(3/5) Dự án?"
    for answer in ["VR Studio", "anh Minh", "50 triệu"]:
        assert run(c.on_text(answer))
    preview = out[-1][0]
    assert "Tới: khach@abc.com\nCC: sep@gmail.com" in preview
    assert "Báo giá VR Studio" in preview and "anh Minh" in preview and "50 triệu" in preview
    assert out[-1][1] == [[("Gửi", "ml:send"), ("Sửa", "ml:edit")], [("Lưu nháp", "ml:draft"), ("Hủy", "ml:cancel")]]
    assert mails == []  # chưa bấm Gửi thì chưa gửi

    answer, _ = run(c.on_button("send"))
    assert "Đã gửi" in answer and len(mails) == 1
    assert mails[0]["Subject"] == "Báo giá VR Studio"
    assert c.draft is None
    run(c.on_button("send"))  # bấm Gửi lần nữa không gửi thêm
    assert len(mails) == 1


def test_add_button_only_adds(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.on_button("add"))
    assert out[-1] == ("Nhập email cần thêm:", None)
    run(c.on_text("ketoan@abc.com, sep@gmail.com"))
    assert c.draft.to == ["khach@abc.com", "ketoan@abc.com", "sep@gmail.com"]
    assert "sep@gmail.com" in out[-1][0]  # đã sang câu CC


def test_clear_button_clears_then_asks_for_email(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.on_button("keep"))
    run(c.on_button("clr"))  # xóa hết CC
    assert out[-1] == ("Đã xóa hết. Nhập email:", None) and c.draft.cc == []
    run(c.on_text("khong-phai-email"))
    assert "không hợp lệ" in out[-1][0]
    run(c.on_text("hr@abc.com"))
    for answer in ["VR", "Minh", "50 triệu"]:
        run(c.on_text(answer))
    assert "CC: hr@abc.com" in out[-1][0]
    run(c.on_button("send"))
    assert mails[0]["Cc"] == "hr@abc.com"


def test_cannot_keep_empty_recipient(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.on_button("clr"))
    answer, _ = run(c.on_button("keep"))
    assert answer == "Chưa có người nhận" and c.draft.queue[0] == TO_FIELD


def test_empty_recipients_ask_to_type_and_cc_can_be_skipped(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:1"))  # hen: không có người nhận mặc định
    assert out[-1] == ("(1/3) Gửi tới (email)? Nhập email:", None)
    run(c.on_text("ban@x.com"))
    assert out[-1][1] == [[("Không CC", "ml:keep")]]
    run(c.on_button("keep"))
    run(c.on_text("Lan"))
    assert "Tới: ban@x.com" in out[-1][0] and "CC:" not in out[-1][0]
    run(c.on_button("draft"))
    assert mails[0][0] == "draft" and mails[0][1]["To"] == "ban@x.com"


def test_edit_one_field_returns_to_preview(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.on_button("keep"))
    run(c.on_button("keep"))
    for answer in ["VR", "Minh", "50 triệu"]:
        run(c.on_text(answer))
    run(c.on_button("edit"))
    assert [r[0][0] for r in out[-1][1]] == ["Gửi tới (email)", "CC (email)", "Dự án", "Tên khách", "Số tiền", "Quay lại"]
    run(c.on_button("ef:4"))
    assert out[-1][0] == "Số tiền?\nHiện tại: 50 triệu"
    run(c.on_text("60 triệu"))
    assert "60 triệu" in out[-1][0] and "Xem trước" in out[-1][0]


def test_send_failure_keeps_draft(tmp_path):
    def boom(cfg, msg):
        raise MailError("Gmail từ chối đăng nhập")

    c, out, mails = make(tmp_path, send_mail=boom)
    run(c.cmd_mail())
    run(c.on_button("p:1"))
    run(c.on_text("a@b.com"))
    run(c.on_button("keep"))
    run(c.on_text("Lan"))
    answer, _ = run(c.on_button("send"))
    assert answer == "Không thành công" and c.draft is not None and not c.draft.busy
    assert any("từ chối" in t for t, _ in out)


TODAY = date(2026, 11, 2)


@pytest.mark.parametrize("start,end,expected", [
    ("24/10", "-", "24/10/2026"),
    ("24/10", "25/10", "24,25/10/2026"),
    ("24/10", "27/10", "24,25,26,27/10/2026"),
    ("5/11", "6/11", "05,06/11/2026"),
    ("30/10", "02/11", "30/10 - 02/11/2026"),
    ("30/12", "2/1", "30/12/2026 - 02/01/2027"),
    ("15/01", "-", "15/01/2027"),  # đã qua quá 60 ngày -> năm sau
    ("24/10/2025", "-", "24/10/2025"),
])
def test_date_range_formatting(start, end, expected):
    s = parse_day(start, TODAY)
    e = s if end == "-" else parse_day(end, TODAY, not_before=s)
    assert format_range(s, e) == expected


@pytest.mark.parametrize("bad", ["31/02", "hôm nay", "24"])
def test_bad_dates_rejected(bad):
    with pytest.raises(DateInputError):
        parse_day(bad, TODAY)


def test_leave_request_flow_with_date_range(tmp_path):
    c, out, mails = make(tmp_path)
    (c.templates_dir / "nghiphep.md").write_text(
        "---\nto:\nsubject: ĐƠN XIN NGHỈ PHÉP_NGÀY {Ngày nghỉ:ngày}\n---\n"
        "Lý do: {Lý do}\nThời gian: {Ngày nghỉ:ngày}\n"
        "Hình thức: {Hình thức|Không hưởng lương|Nghỉ phép}\n", encoding="utf-8")
    c._today = lambda: TODAY
    run(c.cmd_mail())
    run(c.on_button("p:2"))  # baogia, hen, nghiphep
    run(c.on_text("toi@gmail.com"))
    run(c.on_text("sep@x.com, hr@x.com"))
    assert out[-1] == ("(3/5) Ngày nghỉ — từ ngày? (vd 24/10)", None)
    run(c.on_text("24/10"))
    assert out[-1] == ("(3/5) Ngày nghỉ — đến ngày?", [[("Chỉ 1 ngày", "ml:one")]])
    run(c.on_text("22/10"))  # trước ngày bắt đầu
    assert "sau ngày bắt đầu" in out[-1][0]
    run(c.on_text("25/10"))
    run(c.on_text("khám sơ tuyển"))
    assert out[-1][1] == [[("Không hưởng lương", "ml:c:0")], [("Nghỉ phép", "ml:c:1")]]
    run(c.on_text("linh tinh"))
    assert out[-1][0] == "Chọn một mục:"
    run(c.on_button("c:1"))
    preview = out[-1][0]
    assert "NGÀY 24,25/10/2026" in preview and "Thời gian: 24,25/10/2026" in preview
    assert "CC: sep@x.com, hr@x.com" in preview and "Hình thức: Nghỉ phép" in preview

    # sửa ô ngày thành 1 ngày bằng nút
    run(c.on_button("edit"))
    run(c.on_button("ef:2"))  # Gửi tới, CC, Ngày nghỉ, ...
    run(c.on_text("24/10"))
    run(c.on_button("one"))
    assert "NGÀY 24/10/2026" in out[-1][0]


def test_real_leave_template_parses():
    path = Path(__file__).parents[1] / "data" / "templates" / "don-xin-nghi-phep.md"
    if not path.exists():
        pytest.skip("template thật không có trong máy này")
    t = parse_template("don-xin-nghi-phep", path.read_text(encoding="utf-8"))
    assert t.fields == [TO_FIELD, CC_FIELD, "Ngày nghỉ:ngày", "Lý do xin nghỉ phép",
                        "Hình thức nghỉ phép|Không hưởng lương|Nghỉ phép"]


def test_cancel_and_text_ignored_when_idle(tmp_path):
    c, out, mails = make(tmp_path)
    assert run(c.on_text("xin chào")) is False
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.cmd_cancel())
    assert c.draft is None and run(c.on_text("VR")) is False


def test_stale_buttons_do_nothing(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.on_button("keep"))
    answer, _ = run(c.on_button("one"))  # nút của câu hỏi khác
    assert answer == "Câu hỏi này đã qua" and c.draft.queue[0] == CC_FIELD
