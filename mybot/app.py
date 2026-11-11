import asyncio
import getpass
import logging
from datetime import datetime

from telethon import TelegramClient

from .control.bot import Controller
from .core.config import Config
from .core.lessons import Lessons
from .core.storage import Storage
from .skills import mail, screen
from .sources import telegram
from .sources.telegram.digest import Digester

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
    lessons = Lessons(cfg.lessons_path)

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
    digester = telegram.setup(cfg, controller, user, store, lessons, skip_ids={bot_me.id})
    composer = mail.setup(cfg, controller)
    screen.setup(controller)
    controller.register()
    await controller.publish_menu()

    parts = ["theo dõi Telegram"] + (["soạn email"] if composer else [])
    await controller.send(f"Bot đã chạy ({', '.join(parts)}) cho tài khoản <b>{me.first_name}</b>. "
                          "Gõ /help để xem lệnh.")
    await asyncio.gather(
        user.run_until_disconnected(),
        bot.run_until_disconnected(),
        periodic(cfg, store, digester),
    )


async def periodic(cfg: Config, store: Storage, digester: Digester) -> None:
    last_purge = None
    while True:
        now = datetime.now(cfg.timezone)
        try:
            await digester.tick(now)
            if last_purge != now.date():
                store.purge_older_than(cfg.retention_days)
                last_purge = now.date()
        except Exception:
            log.exception("Lỗi trong vòng tóm tắt định kỳ")
        await asyncio.sleep(60)
