import asyncio

from mybot.control.bot import Controller
from mybot.skills import screen


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, to, text, **kw):
        self.sent.append(text)


def make(monkeypatch, result):
    bot = FakeBot()
    c = Controller(bot, owner_id=1)
    calls = []
    monkeypatch.setattr(screen, "_call", lambda url, token, action: calls.append((url, token, action)) or result)
    assert screen.setup(c, url="http://x:1/", token="t")
    return bot, c, calls


class Event:
    def __init__(self, text):
        self.sender_id, self.raw_text = 1, text


def test_screen_off_calls_agent(monkeypatch):
    bot, c, calls = make(monkeypatch, "ok")
    asyncio.run(c._on_message(Event("/screen off")))
    assert calls == [("http://x:1", "t", "off")]
    assert "tắt" in bot.sent[0]


def test_screen_alone_shows_buttons_and_status_button_works(monkeypatch):
    bot, c, calls = make(monkeypatch, "off")
    asyncio.run(c._on_message(Event("/screen")))
    assert calls == [] and "/screen" in bot.sent[0]
    asyncio.run(c._on_option("/screen:0"))  # nút Xem
    asyncio.run(c._on_message(Event("/screen status")))
    assert calls == [("http://x:1", "t", "status")] * 2
    assert bot.sent[1:] == ["Màn hình đang tắt."] * 2


def test_screen_bad_arg_shows_help_and_failure_reported(monkeypatch):
    bot, c, calls = make(monkeypatch, "HTTP 401")
    asyncio.run(c._on_message(Event("/screen xyz")))
    asyncio.run(c._on_message(Event("/screen on")))
    assert calls == [("http://x:1", "t", "on")]
    assert "/screen off" in bot.sent[0] and "HTTP 401" in bot.sent[1]


def test_disabled_without_token():
    assert not screen.setup(Controller(FakeBot(), 1), token="")


def test_status_reports_lock(monkeypatch):
    bot, c, calls = make(monkeypatch, "off locked")
    asyncio.run(c._on_message(Event("/screen status")))
    assert bot.sent == ["Màn hình đang tắt." + screen.LOCKED_TEXT]
