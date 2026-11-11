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


def test_publish_menu_lists_commands_with_description():
    class MenuBot(FakeBot):
        async def __call__(self, request):
            self.request = request

        def add_event_handler(self, *a):
            pass

    bot = MenuBot()
    c = Controller(bot, owner_id=1)
    c.add_command(["/vip"], None, menu="Danh sách VIP")
    c.add_command(["/kw"], None)  # không có mô tả: không lên menu
    c.register()
    asyncio.run(c.publish_menu())
    assert [(x.command, x.description) for x in bot.request.commands] == [
        ("vip", "Danh sách VIP"), ("help", "Danh sách lệnh")]


def test_command_alone_shows_options_and_ask_flow():
    class ButtonBot(FakeBot):
        async def send_message(self, to, text, buttons=None, **kw):
            self.sent.append((to, text, buttons))

    from mybot.control.bot import Option
    bot = ButtonBot()
    c = Controller(bot, owner_id=1)
    calls = []

    async def vip(args):
        calls.append(args)

    c.add_command(["/vip"], vip, menu="VIP", options=[
        Option("List", "list"), Option("Add", "add", ask="Nhập tên:"),
        Option("Remove", "remove", ask="Nhập số:", before="list")])

    asyncio.run(c._on_message(Event(1, "/vip")))  # chỉ hiện nút, chưa chạy lệnh
    assert calls == [] and len(bot.sent[-1][2][0]) == 3

    asyncio.run(c._on_option("/vip:0"))
    assert calls[-1] == ["list"]

    asyncio.run(c._on_option("/vip:1"))
    assert "Nhập tên" in bot.sent[-1][1]
    asyncio.run(c._on_message(Event(1, "Anh Ba")))
    assert calls[-1] == ["add", "Anh Ba"]

    asyncio.run(c._on_option("/vip:2"))  # xem danh sách trước rồi hỏi
    assert calls[-1] == ["list"]
    asyncio.run(c._on_message(Event(1, "/vip add Chị Tư")))  # gõ thẳng vẫn được, bỏ câu hỏi đang chờ
    assert calls[-1] == ["add", "Chị Tư"]
    asyncio.run(c._on_message(Event(1, "linh tinh")))
    assert calls[-1] == ["add", "Chị Tư"]  # không còn chờ nên không chạy remove
