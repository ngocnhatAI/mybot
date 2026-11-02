"""Template email: mỗi file .md trong data/templates/ là một template.

Định dạng:
    ---
    to: khach@abc.com, nguoikhac@abc.com
    cc: sep@gmail.com
    subject: Báo giá dự án {Tên dự án}
    ---
    Kính gửi {Tên khách}, ...

Chỗ cần điền viết trong ngoặc nhọn {...}. Để trống `to:` thì bot sẽ hỏi người nhận.
Ô kiểu ngày viết {Tên:ngày}: bot hỏi ngày bắt đầu và ngày kết thúc (xem dates.py).
Cùng một tên xuất hiện nhiều chỗ (tiêu đề và nội dung) thì chỉ hỏi một lần.
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = re.compile(r"\{([^{}\n]{1,60})\}")
EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
TO_FIELD = "Gửi tới (email)"
EXAMPLES_DIR = Path(__file__).parent / "examples"


class TemplateError(ValueError):
    pass


@dataclass
class Template:
    key: str
    to: list[str]
    cc: list[str]
    subject: str
    body: str

    @property
    def placeholders(self) -> list[str]:
        """Các chỗ cần điền, theo thứ tự xuất hiện (tiêu đề trước), không trùng."""
        seen: list[str] = []
        for name in PLACEHOLDER.findall(self.subject + "\n" + self.body):
            name = name.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def fields(self) -> list[str]:
        """Những gì bot cần hỏi: người nhận (nếu template để trống) rồi tới các chỗ trống."""
        return ([] if self.to else [TO_FIELD]) + self.placeholders


def parse_addresses(text: str) -> list[str]:
    addrs = [a.strip() for a in re.split(r"[,;\s]+", text or "") if a.strip()]
    bad = [a for a in addrs if not EMAIL.match(a)]
    if bad:
        raise TemplateError(f"Địa chỉ email không hợp lệ: {', '.join(bad)}")
    return addrs


def parse_template(key: str, text: str) -> Template:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise TemplateError("thiếu phần đầu --- to / cc / subject ---")
    header: dict[str, str] = {}
    for line in m[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            header[k.strip().lower()] = v.strip()
    subject = header.get("subject", "")
    if not subject:
        raise TemplateError("thiếu dòng subject:")
    body = m[2].strip("\n")
    if not body.strip():
        raise TemplateError("nội dung email đang trống")
    return Template(key, parse_addresses(header.get("to", "")), parse_addresses(header.get("cc", "")),
                    subject, body)


def load_templates(directory: Path) -> tuple[list[Template], list[str]]:
    """Trả về (các template hợp lệ, các lỗi để báo cho bạn)."""
    templates, errors = [], []
    for path in sorted(directory.glob("*.md")):
        try:
            templates.append(parse_template(path.stem, path.read_text(encoding="utf-8")))
        except (TemplateError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: {e}")
    return templates, errors


def ensure_examples(directory: Path) -> None:
    """Lần đầu chạy: tạo thư mục template và chép template mẫu vào."""
    if directory.exists():
        return
    directory.mkdir(parents=True)
    for f in EXAMPLES_DIR.glob("*.md"):
        shutil.copy(f, directory / f.name)


def render(text: str, values: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: values.get(m[1].strip(), m[0]), text)
