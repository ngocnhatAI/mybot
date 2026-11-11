"""/ultraview: mở UltraViewer trên máy Windows (nếu chưa chạy) và gửi lại ID, mật khẩu.

Dùng chung script host/screen_agent.py (cùng SCREEN_TOKEN) với lệnh /screen.
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from html import escape

from ..control.bot import Controller
from .screen import DEFAULT_URL

log = logging.getLogger(__name__)

HELP = """<b>UltraViewer</b>
/ultraview — mở UltraViewer nếu chưa chạy, gửi ID và mật khẩu"""


def _fetch(url: str, token: str) -> dict:
    req = urllib.request.Request(f"{url}/ultraviewer", headers={"Authorization": f"Bearer {token}"})
    try:
        # mở UltraViewer và chờ có ID có thể mất tới ~45 giây
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"error": f"không kết nối được ({e}). Kiểm tra script host/screen_agent.py đã chạy chưa"}


def format_reply(data: dict) -> str:
    if "error" in data:
        return f"Không lấy được thông tin UltraViewer: {escape(data['error'])}."
    note = "\n<i>Vừa mở UltraViewer.</i>" if data.get("started") else ""
    return (f"<b>UltraViewer</b>\nID: <code>{escape(data['id'])}</code>\n"
            f"Mật khẩu: <code>{escape(data['password'])}</code>{note}")


def setup(controller: Controller, url: str | None = None, token: str | None = None) -> bool:
    token = token if token is not None else os.environ.get("SCREEN_TOKEN", "")
    url = (url or os.environ.get("SCREEN_AGENT_URL") or DEFAULT_URL).rstrip("/")
    if not token:
        log.info("Chưa có SCREEN_TOKEN trong .env, tắt lệnh /ultraview")
        return False

    async def cmd_ultraview(_args) -> None:
        await controller.send("Đang lấy ID UltraViewer...")
        await controller.send(format_reply(await asyncio.to_thread(_fetch, url, token)))

    controller.add_command(["/ultraview", "/uv"], cmd_ultraview, menu="UltraViewer: ID và mật khẩu")
    controller.add_help(HELP)
    return True
