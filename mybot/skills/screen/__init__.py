"""Kỹ năng bật/tắt màn hình máy Windows chạy bot, qua host/screen_agent.py chạy ngoài Docker."""

import asyncio
import logging
import os
import urllib.error
import urllib.request

from ...control.bot import Controller, Option

log = logging.getLogger(__name__)

HELP = """<b>Màn hình máy tính</b>
/screen off  — tắt màn hình và khóa chuột, bàn phím
/screen on  — mở khóa và bật màn hình
/screen status  — xem màn hình đang bật hay tắt, có đang khóa không
Ngồi tại máy: Ctrl+Shift+N để mở khóa."""

DEFAULT_URL = "http://host.docker.internal:8765"

STATUS_TEXT = {"on": "Màn hình đang bật.", "off": "Màn hình đang tắt.", "dimmed": "Màn hình đang được làm mờ.",
               "unknown": "Chưa rõ trạng thái màn hình (chưa có thay đổi nào từ khi script khởi động)."}
LOCKED_TEXT = " Chuột và bàn phím đang khóa (mở bằng Ctrl+Shift+N hoặc /screen on)."


def _call(url: str, token: str, action: str) -> str:
    """Trả về "ok" (hoặc trạng thái nếu action == "status"), hay chuỗi mô tả lỗi."""
    is_status = action == "status"
    req = urllib.request.Request(f"{url}/screen/{action}", method="GET" if is_status else "POST",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status != 200:
                return f"HTTP {r.status}"
            return r.read().decode().strip() if is_status else "ok"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return f"không kết nối được ({e})"


def setup(controller: Controller, url: str | None = None, token: str | None = None) -> bool:
    token = token if token is not None else os.environ.get("SCREEN_TOKEN", "")
    url = (url or os.environ.get("SCREEN_AGENT_URL") or DEFAULT_URL).rstrip("/")
    if not token:
        log.info("Chưa có SCREEN_TOKEN trong .env, tắt lệnh /screen")
        return False

    async def cmd_screen(args: list[str]) -> None:
        action = args[0].lower() if args else "status"
        if action not in ("on", "off", "status"):
            await controller.send(HELP)
            return
        result = await asyncio.to_thread(_call, url, token, action)
        state, _, flag = result.partition(" ")
        if action == "status" and state in STATUS_TEXT:
            await controller.send(STATUS_TEXT[state] + (LOCKED_TEXT if flag == "locked" else ""))
        elif result == "ok":
            await controller.send("Đã tắt màn hình." + LOCKED_TEXT if action == "off"
                                  else "Đã mở khóa và bật màn hình.")
        else:
            await controller.send(f"Không điều khiển được màn hình: {result}. "
                                  "Kiểm tra script host/screen_agent.py đã chạy trên Windows chưa.")

    controller.add_command(["/screen"], cmd_screen, menu="Màn hình máy tính: xem / on / off",
                           options=[Option("Status", "status"), Option("On", "on"), Option("Off", "off")])
    controller.add_help(HELP)
    return True
