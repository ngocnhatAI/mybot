"""Luật cứng quyết định tin nào báo ngay. Không gọi AI, không tốn phí."""

import re
import unicodedata

from .models import Incoming, RuleHit


def normalize(text: str) -> str:
    # NFC để "ấ" gõ kiểu tổ hợp và kiểu dựng sẵn vẫn khớp nhau
    return unicodedata.normalize("NFC", text).casefold()


def find_keyword(text: str, keywords: list[str]) -> str | None:
    norm = normalize(text)
    for kw in keywords:
        k = normalize(kw).strip()
        if k and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", norm):
            return kw
    return None


def match_rules(msg: Incoming, vip_ids: dict[str, str], keywords: list[str]) -> RuleHit | None:
    """vip_ids: {id dạng chuỗi: tên hiển thị} của người VIP. VIP chỉ áp dụng cho tin nhắn riêng."""
    key = str(msg.sender_id)
    if msg.chat_kind == "private" and key in vip_ids:
        return RuleHit("vip", key, f"VIP: {vip_ids[key]}")

    if msg.mentioned:
        return RuleHit("mention", "", "Bạn được nhắc tên hoặc được trả lời")

    kw = find_keyword(msg.text, keywords)
    if kw:
        return RuleHit("keyword", kw, f"Từ khóa: {kw}")
    return None
