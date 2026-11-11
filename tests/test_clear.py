import asyncio
from types import SimpleNamespace

from mybot.control.bot import Controller
from mybot.skills import clear


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, to, text, **kw):
        self.sent.append(text)


class FakeUser:
    def __init__(self):
        self.requests = []
        self.offsets = [100, 0]  # lần đầu còn sót, lần sau xong

    async def get_input_entity(self, peer):
        return f"peer:{peer}"

    async def __call__(self, req):
        self.requests.append(req)
        return SimpleNamespace(offset=self.offsets.pop(0))


class Event:
    def __init__(self, text):
        self.sender_id, self.raw_text = 1, text


def test_clear_needs_confirmation_and_deletes_both_sides():
    bot, user = FakeBot(), FakeUser()
    c = Controller(bot, owner_id=1)
    clear.setup(c, user, bot_id=99)

    asyncio.run(c._on_message(Event("/clear")))  # chỉ hiện nút
    asyncio.run(c._on_option("/clear:1"))  # Cancel
    assert user.requests == [] and "hủy" in bot.sent[-1]

    asyncio.run(c._on_option("/clear:0"))  # Clear all
    assert len(user.requests) == 2  # lặp tới khi offset = 0
    r = user.requests[0]
    assert r.peer == "peer:99" and r.revoke and r.just_clear
    assert bot.sent[-1] == "Đã xóa lịch sử chat."
