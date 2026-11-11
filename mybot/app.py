import asyncio
import getpass
import logging

from telethon import TelegramClient

from .control.bot import Controller
from .core.config import Config
from .core.storage import Storage
from .skills import mail, screen
from .sources import telegram

log = logging.getLogger(__name__)


def user_client(cfg: Config) -> TelegramClient:
    return TelegramClient(str(cfg.data_dir / "user"), cfg.api_id, cfg.api_hash)


async def login(cfg: Config) -> None:
    """Đăng nhập tài khoản Telegram của bạn lần đầu. Bạn tự gõ số điện thoại và mã."""
    client = user_client(cfg)
    await client.start(
        phone=lambda: input("Số điện thoại Telegram (dạng +84...): "),
        code_callback=lambda: input("Mã xác nhận Telegram vừa gửi: "),
        password=lambda: getpass.getpass("Mật khẩu xác minh 2 bước (nếu có): "),
    )
    me = await client.get_me()
    print(f"Đăng nhập thành công: {me.first_name} (id {me.id}). Giờ có thể chạy bot.")
    await client.disconnect()


async def run(cfg: Config) -> None:
    store = Storage(cfg.data_dir / "mybot.db")
    store.seed_keywords(cfg.default_keywords)

    user = user_client(cfg)
    await user.connect()
    if not await user.is_user_authorized():
        raise SystemExit("Chưa đăng nhập Telegram. Chạy: docker compose run --rm bot python -m mybot login")

    bot = TelegramClient(str(cfg.data_dir / "bot"), cfg.api_id, cfg.api_hash)
    bot.parse_mode = "html"
    await bot.start(bot_token=cfg.bot_token)

    me = await user.get_me()
    bot_me = await bot.get_me()
    log.info("Tài khoản: %s (%s) · Bot: @%s", me.first_name, me.id, bot_me.username)

    controller = Controller(bot, me.id)
    telegram.setup(cfg, controller, user, store, skip_ids={bot_me.id})
    composer = mail.setup(cfg, controller)
    screen.setup(controller)
    controller.register()
    await controller.publish_menu()
    controller.set_quick_keyboard([
        [("VIP", "/vip"), ("Keyword", "/keyword"), ("Schedule", "/schedule")],
        [("Mail", "/mail"), ("Screen", "/screen"), ("Help", "/help")],
    ])

    parts = ["theo dõi Telegram"] + (["soạn email"] if composer else [])
    await controller.send(f"Bot đã chạy ({', '.join(parts)}) cho tài khoản <b>{me.first_name}</b>. "
                          "Gõ /help để xem lệnh.", keyboard=True)
    await asyncio.gather(
        user.run_until_disconnected(),
        bot.run_until_disconnected(),
    )

