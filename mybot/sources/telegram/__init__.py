"""Nguồn tin Telegram: đọc tin trên tài khoản của bạn, báo ngay theo luật, tóm tắt định kỳ."""

from .commands import TelegramCommands
from .digest import Digester
from .feedback import Feedback
from .listener import Listener
from ...control.bot import Controller
from ...core.ai import AI
from ...core.config import Config
from ...core.lessons import Lessons
from ...core.storage import Storage


def setup(cfg: Config, controller: Controller, user, store: Storage, lessons: Lessons,
          skip_ids: set[int]) -> Digester:
    """Gắn phần Telegram vào bot. Trả về Digester để vòng định kỳ gọi tick()."""
    ai = AI(cfg.ai, store)
    feedback = Feedback(cfg, store, ai, lessons, controller.send)
    TelegramCommands(cfg, controller, user, store, lessons, feedback).register()
    controller.add_text_handler(feedback.on_text)
    Listener(user, store, controller.send, cfg.timezone, skip_ids).register()
    return Digester(cfg, store, ai, lessons, controller.send)
