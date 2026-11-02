"""Gửi email qua SMTP của Gmail và lưu nháp qua IMAP, dùng App Password."""

import imaplib
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from ...core.config import MailConfig

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
IMAP_HOST = "imap.gmail.com"


class MailError(Exception):
    pass


def build_message(cfg: MailConfig, to: list[str], cc: list[str], subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name, cfg.address)) if cfg.from_name else cfg.address
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=cfg.address.split("@")[-1])
    msg.set_content(body)
    return msg


def send(cfg: MailConfig, msg: EmailMessage) -> None:
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.login(cfg.address, cfg.app_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError("Gmail từ chối đăng nhập: kiểm tra GMAIL_ADDRESS và GMAIL_APP_PASSWORD trong .env") from e
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"Không gửi được: {e}") from e


def _drafts_mailbox(imap: imaplib.IMAP4_SSL) -> str:
    """Tên thư mục Nháp phụ thuộc ngôn ngữ Gmail, nên tìm theo cờ \\Drafts."""
    _, lines = imap.list()
    for raw in lines or []:
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        if "\\Drafts" in line:
            m = re.search(r'"([^"]+)"\s*$', line) or re.search(r"(\S+)\s*$", line)
            if m:
                return m[1]
    return "[Gmail]/Drafts"


def save_draft(cfg: MailConfig, msg: EmailMessage) -> None:
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
        try:
            imap.login(cfg.address, cfg.app_password)
            box = _drafts_mailbox(imap)
            typ, data = imap.append(f'"{box}"', "\\Draft", imaplib.Time2Internaldate(time.time()),
                                    msg.as_bytes())
            if typ != "OK":
                raise MailError(f"Gmail không nhận bản nháp: {data}")
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as e:
        raise MailError(f"Không lưu được nháp (kiểm tra App Password và IMAP đã bật): {e}") from e
    except OSError as e:
        raise MailError(f"Không kết nối được Gmail: {e}") from e
