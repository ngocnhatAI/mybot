"""Ô kiểu ngày trong template: {Tên:ngày}. Bot hỏi ngày bắt đầu và (tùy chọn) ngày kết thúc.

Cách ghi:
    1 ngày                  24/10/2026
    nhiều ngày cùng tháng   24,25,26,27/10/2026
    qua tháng / qua năm     30/10 - 02/11/2026 · 30/12/2026 - 02/01/2027
"""

import re
from datetime import date, timedelta

DATE_SUFFIXES = (":ngày", ":ngay", ":date")
SKIP_WORDS = {"", "-", "0", "không", "khong", "ko", "k", "no"}
MAX_DAYS = 60
# Ngày đã qua quá lâu thì hiểu là năm sau (ví dụ tháng 12 gõ 05/01)
PAST_GRACE = timedelta(days=60)


class DateInputError(ValueError):
    pass


def is_date_field(name: str) -> bool:
    return name.lower().endswith(DATE_SUFFIXES)


def label(name: str) -> str:
    """Tên hiển thị khi hỏi: bỏ hậu tố :ngày."""
    low = name.lower()
    for s in DATE_SUFFIXES:
        if low.endswith(s):
            return name[: -len(s)].strip()
    return name


def parse_day(text: str, today: date, not_before: date | None = None) -> date:
    m = re.fullmatch(r"\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})(?:\s*[/.\-]\s*(\d{2}|\d{4}))?\s*", text)
    if not m:
        raise DateInputError("Ngày chưa đúng dạng, gõ kiểu 24/10")
    day, month = int(m[1]), int(m[2])
    if m[3]:
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return _make(year, month, day)
    if not_before:  # ngày kết thúc: cùng năm với ngày bắt đầu; chỉ sang năm sau khi nghỉ qua Tết dương
        d = _make(not_before.year, month, day)
        if d >= not_before:
            return d
        d = _make(not_before.year + 1, month, day)
        if (d - not_before).days >= MAX_DAYS:
            raise DateInputError("Ngày kết thúc phải sau ngày bắt đầu")
        return d
    d = _make(today.year, month, day)
    return d if d >= today - PAST_GRACE else _make(today.year + 1, month, day)


def _make(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise DateInputError(f"Không có ngày {day:02d}/{month:02d}/{year}") from None


def format_range(start: date, end: date) -> str:
    if end < start:
        raise DateInputError("Ngày kết thúc phải sau ngày bắt đầu")
    if (end - start).days >= MAX_DAYS:
        raise DateInputError(f"Khoảng nghỉ dài quá {MAX_DAYS} ngày, kiểm tra lại")
    if start == end:
        return f"{start:%d/%m/%Y}"
    if (start.year, start.month) == (end.year, end.month):
        days = ",".join(f"{start.day + i:02d}" for i in range((end - start).days + 1))
        return f"{days}/{start:%m/%Y}"
    left = f"{start:%d/%m}" if start.year == end.year else f"{start:%d/%m/%Y}"
    return f"{left} - {end:%d/%m/%Y}"


def is_skip(text: str) -> bool:
    return text.strip().lower() in SKIP_WORDS
