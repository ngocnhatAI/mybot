"""Giờ nghỉ cố định hằng ngày, có thể vắt qua nửa đêm (ví dụ 17:30 -> 08:00)."""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

MODES = ("notify", "hold")


@dataclass
class RestSchedule:
    start: time
    end: time
    mode: str = "notify"  # notify: tin hợp luật vẫn báo ngay; hold: giữ tới cuối giờ nghỉ

    def label(self) -> str:
        return f"{self.start:%H:%M} → {self.end:%H:%M}"

    def to_dict(self) -> dict:
        return {"start": f"{self.start:%H:%M}", "end": f"{self.end:%H:%M}", "mode": self.mode}

    @classmethod
    def from_dict(cls, d: dict) -> "RestSchedule":
        return cls(parse_hhmm(d["start"]), parse_hhmm(d["end"]), d.get("mode", "notify"))

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

    def last_end(self, now: datetime) -> tuple[datetime, datetime] | None:
        """Khung nghỉ gần nhất đã kết thúc trước hoặc đúng `now`."""
        best = None
        for offset in (2, 1, 0):
            day = now.date() - timedelta(days=offset)
            start = datetime.combine(day, self.start, now.tzinfo)
            end = datetime.combine(day, self.end, now.tzinfo)
            if end <= start:
                end += timedelta(days=1)
            if end <= now:
                best = (start, end)
        return best


def parse_hhmm(s: str) -> time:
    m = re.fullmatch(r"(\d{1,2})[:hH](\d{2})", s.strip())
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ValueError(f"Giờ không hợp lệ: {s} (đúng dạng: 17:30)")
    return time(int(m[1]), int(m[2]))
