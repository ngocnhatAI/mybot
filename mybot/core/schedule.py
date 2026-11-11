"""Giờ nghỉ cố định hằng ngày, có thể vắt qua nửa đêm (ví dụ 17:30 -> 08:00).

Trong giờ nghỉ bot im lặng hoàn toàn: tin đến bị bỏ qua hẳn, hết giờ nghỉ cũng không gửi bù."""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

@dataclass
class RestSchedule:
    start: time
    end: time

    def label(self) -> str:
        return f"{self.start:%H:%M} → {self.end:%H:%M}"

    def to_dict(self) -> dict:
        return {"start": f"{self.start:%H:%M}", "end": f"{self.end:%H:%M}"}

    @classmethod
    def from_dict(cls, d: dict) -> "RestSchedule":
        return cls(parse_hhmm(d["start"]), parse_hhmm(d["end"]))

    def window_containing(self, now: datetime) -> tuple[datetime, datetime] | None:
        """Khung nghỉ đang chứa `now`, hoặc None nếu đang trong giờ làm."""
        for day in (now.date() - timedelta(days=1), now.date()):
            start = datetime.combine(day, self.start, now.tzinfo)
            end = datetime.combine(day, self.end, now.tzinfo)
            if end <= start:
                end += timedelta(days=1)
            if start <= now < end:
                return start, end
        return None

    def is_resting(self, now: datetime) -> bool:
        return self.window_containing(now) is not None



def parse_hhmm(s: str) -> time:
    m = re.fullmatch(r"(\d{1,2})[:hH](\d{2})", s.strip())
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ValueError(f"Giờ không hợp lệ: {s} (đúng dạng: 17:30)")
    return time(int(m[1]), int(m[2]))


def get_schedule(store) -> RestSchedule | None:
    """Giờ nghỉ đã đặt bằng /schedule (lưu trong settings), hoặc None."""
    d = store.get_setting("schedule")
    return RestSchedule.from_dict(d) if d else None
