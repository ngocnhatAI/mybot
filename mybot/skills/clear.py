"""/clear: xóa toàn bộ lịch sử chat giữa bạn và bot, ở cả hai phía.

Bot không tự xóa được tin cũ hơn 48 giờ, nên việc xóa do tài khoản Telegram của bạn
(phiên đăng nhập của bot) làm, giống như bạn bấm "Clear history" và chọn xóa cho cả bot.
"""

import logging

from telethon import functions

from ..control.bot import Controller, Option

log = logging.getLogger(__name__)


async def clear_history(user, bot_id: int) -> None:
    peer = await user.get_input_entity(bot_id)
    while True:  # Telegram xóa theo từng đợt, trả về offset > 0 nếu còn
        res = await user(functions.messages.DeleteHistoryRequest(peer, max_id=0, just_clear=True, revoke=True))
        if not res.offset:
            break


def setup(controller: Controller, user, bot_id: int) -> None:
    async def cmd_clear(args: list[str]) -> None:
        action = args[0].lower() if args else ""
        if action == "cancel":
            await controller.send("Đã hủy, không xóa gì.")
            return
        if action != "confirm":
            await controller.send("Gõ /clear để chọn, hoặc /clear confirm để xóa ngay.")
            return
        try:
            await clear_history(user, bot_id)
        except Exception:
            log.exception("Không xóa được lịch sử chat")
            await controller.send("Không xóa được lịch sử chat, xem log của bot.")
            return
        # tin đầu tiên của cuộc chat mới, kèm lại bàn phím nút nhanh
        await controller.send("Đã xóa lịch sử chat.", keyboard=True)

    controller.add_command(["/clear"], cmd_clear, menu="Xóa lịch sử chat với bot", options=[
        Option("Clear all", "confirm"), Option("Cancel", "cancel")])
    controller.add_help("<b>Lịch sử chat</b>\n/clear — xóa toàn bộ tin nhắn với bot (cả hai phía, không khôi phục được)")
