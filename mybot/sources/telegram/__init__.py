"""Nguồn tin Telegram: đọc tin trên tài khoản của bạn, báo ngay tin khớp luật, còn lại bỏ qua."""

from .commands import TelegramCommands
from .listener import Listener
from ...control.bot import Controller
from ...core.config import Config
from ...core.storage import Storage


def setup(cfg: Config, controller: Controller, user, store: Storage, skip_ids: set[int]) -> None:
    TelegramCommands(cfg, controller, user, store).register()
    Listener(user, store, controller.send, cfg.timezone, skip_ids).register()
