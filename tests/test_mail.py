import asyncio
from pathlib import Path

import pytest

from mybot.core.config import MailConfig
from mybot.skills.mail.composer import MailComposer
from mybot.skills.mail.sender import MailError, build_message
from mybot.skills.mail.templates import (TO_FIELD, TemplateError, ensure_examples, load_templates,
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
    assert t.fields == t.placeholders
    assert render(t.subject, {"Dự án": "VR"}) == "Báo giá VR"


def test_template_without_recipient_asks_for_it_first():
    t = parse_template("hen", TPL_NO_TO)
    assert t.fields == [TO_FIELD, "Tên"]


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


def test_full_flow_pick_fill_preview_send(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    assert len(out[-1][1]) == 2  # 2 nút template
    run(c.on_button("p:0"))  # baogia
    assert "(1/3)" in out[-1][0] and "Dự án" in out[-1][0]
    for answer in ["VR Studio", "anh Minh", "50 triệu"]:
        assert run(c.on_text(answer))
    preview = out[-1][0]
    assert "Báo giá VR Studio" in preview and "anh Minh" in preview and "50 triệu" in preview
    assert mails == []  # chưa bấm Gửi thì chưa gửi

    answer, _ = run(c.on_button("send"))
    assert "Đã gửi" in answer and len(mails) == 1
    assert mails[0]["Subject"] == "Báo giá VR Studio"
    assert c.draft is None
    # bấm Gửi lần nữa không gửi thêm
    run(c.on_button("send"))
    assert len(mails) == 1


def test_asks_recipient_and_validates_it(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:1"))  # hen: không có người nhận
    assert TO_FIELD in out[-1][0]
    run(c.on_text("khong-phai-email"))
    assert "không hợp lệ" in out[-1][0]
    run(c.on_text("ban@x.com"))
    run(c.on_text("Lan"))
    assert "ban@x.com" in out[-1][0]
    run(c.on_button("draft"))
    assert mails[0][0] == "draft" and mails[0][1]["To"] == "ban@x.com"


def test_edit_one_field_returns_to_preview(tmp_path):
    c, out, mails = make(tmp_path)
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    for answer in ["VR", "Minh", "50 triệu"]:
        run(c.on_text(answer))
    run(c.on_button("edit"))
    run(c.on_button("ef:2"))  # Số tiền
    assert "Hiện tại" in out[-1][0] and "50 triệu" in out[-1][0]
    run(c.on_text("60 triệu"))
    assert "60 triệu" in out[-1][0] and "Xem trước" in out[-1][0]


def test_send_failure_keeps_draft(tmp_path):
    def boom(cfg, msg):
        raise MailError("Gmail từ chối đăng nhập")

    c, out, mails = make(tmp_path, send_mail=boom)
    run(c.cmd_mail())
    run(c.on_button("p:1"))
    run(c.on_text("a@b.com"))
    run(c.on_text("Lan"))
    answer, _ = run(c.on_button("send"))
    assert answer == "Không thành công" and c.draft is not None and not c.draft.busy
    assert any("từ chối" in t for t, _ in out)


def test_cancel_and_text_ignored_when_idle(tmp_path):
    c, out, mails = make(tmp_path)
    assert run(c.on_text("xin chào")) is False
    run(c.cmd_mail())
    run(c.on_button("p:0"))
    run(c.cmd_cancel())
    assert c.draft is None and run(c.on_text("VR")) is False
