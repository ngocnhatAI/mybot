"""Kỹ năng soạn email theo template và gửi bằng Gmail."""

import logging
from datetime import datetime

from .composer import MailComposer
from .templates import ensure_examples
from ...control.bot import Controller
from ...core.config import Config

log = logging.getLogger(__name__)


def setup(cfg: Config, controller: Controller) -> MailComposer | None:
    if not cfg.mail.enabled:
        log.info("Chưa có GMAIL_ADDRESS / GMAIL_APP_PASSWORD trong .env, tắt phần soạn email")
        return None
    ensure_examples(cfg.templates_dir)
    composer = MailComposer(cfg.mail, cfg.templates_dir, controller.send,
                            today=lambda: datetime.now(cfg.timezone).date())
    composer.register(controller)
    return composer
