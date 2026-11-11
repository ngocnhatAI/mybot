import asyncio

from mybot.control.bot import Controller
from mybot.skills import ultraviewer


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, to, text, **kw):
        self.sent.append(text)


class Event:
    def __init__(self, text):
        self.sender_id, self.raw_text = 1, text


def test_reply_formats_id_password_and_errors():
    ok = ultraviewer.format_reply({"id": "12 345 678", "password": "ab12", "started": True})
    assert "<code>12 345 678</code>" in ok and "<code>ab12</code>" in ok and "Vừa mở" in ok
    assert "Vừa mở" not in ultraviewer.format_reply({"id": "1", "password": "2", "started": False})
    assert "không thấy" in ultraviewer.format_reply({"error": "không thấy <exe>"})


def test_command_calls_agent(monkeypatch):
    bot = FakeBot()
    c = Controller(bot, owner_id=1)
    monkeypatch.setattr(ultraviewer, "_fetch", lambda url, token: {"id": "9", "password": "x", "started": False})
    assert ultraviewer.setup(c, url="http://x", token="t")
    asyncio.run(c._on_message(Event("/uv")))
    assert "Đang lấy" in bot.sent[0] and "<code>9</code>" in bot.sent[1]
