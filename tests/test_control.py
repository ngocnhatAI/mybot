import asyncio

from mybot.control.bot import Controller


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, to, text, **kw):
        self.sent.append((to, text))


class Event:
    def __init__(self, sender_id, text):
        self.sender_id, self.raw_text = sender_id, text


def test_routes_commands_text_and_ignores_strangers():
    bot = FakeBot()
    c = Controller(bot, owner_id=1)
    calls = []

    async def cmd(args):
        calls.append(("cmd", args))

    async def text(t):
        calls.append(("text", t))
        return t == "trả lời"

    c.add_command(["/mail"], cmd)
    c.add_text_handler(text)
    c.add_help("<b>Mail</b>")

    asyncio.run(c._on_message(Event(1, "/mail@my_bot a b c")))
    asyncio.run(c._on_message(Event(1, "trả lời")))
    asyncio.run(c._on_message(Event(2, "/mail")))  # người lạ: bỏ qua
    asyncio.run(c._on_message(Event(1, "/khongco")))
    asyncio.run(c._on_message(Event(1, "linh tinh")))

    assert calls == [("cmd", ["a", "b c"]), ("text", "trả lời"), ("text", "linh tinh")]
    assert "Không có lệnh này" in bot.sent[0][1]
    assert "/help" in bot.sent[1][1]
    assert all(to == 1 for to, _ in bot.sent)
