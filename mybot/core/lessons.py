"""File bài học (lessons.md): bạn đọc, sửa, xóa trực tiếp được.

Mỗi dòng bắt đầu bằng "- " là một bài học. AI đọc lại file này mỗi lần tóm tắt,
nên sửa file là có hiệu lực ngay ở lần tóm tắt kế tiếp.
"""

from datetime import date
from pathlib import Path

HEADER = """# Bài học của bot

<!--
Mỗi dòng bắt đầu bằng "- " là một bài học AI dùng để gán nhãn quan trọng / không quan trọng.
Bạn có thể sửa hoặc xóa dòng bất kỳ. Thay đổi có hiệu lực từ lần tóm tắt kế tiếp.
-->

"""


class Lessons:
    def __init__(self, path: Path):
        self.path = path

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def list(self) -> list[str]:
        return [ln[2:].strip() for ln in self._read_lines() if ln.startswith("- ")]

    def add(self, text: str, today: date) -> None:
        text = " ".join(text.split())
        if not self.path.exists():
            self.path.write_text(HEADER, encoding="utf-8")
        content = self.path.read_text(encoding="utf-8")
        if content and not content.endswith("\n"):
            content += "\n"
        self.path.write_text(content + f"- [{today:%Y-%m-%d}] {text}\n", encoding="utf-8")

    def remove(self, number: int) -> str | None:
        """Xóa bài học thứ `number` (đánh số từ 1). Trả về nội dung đã xóa."""
        lines = self._read_lines()
        idx = [i for i, ln in enumerate(lines) if ln.startswith("- ")]
        if not 1 <= number <= len(idx):
            return None
        removed = lines.pop(idx[number - 1])
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return removed[2:].strip()
