import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("MYBOT_DATA_DIR", ROOT / "data"))


@dataclass
class AIConfig:
    model: str = "claude-haiku-5-5"
    effort: str = "low"
    max_chars_per_message: int = 600
    max_chars_per_request: int = 150_000
    price_input_per_mtok: float = 0.10
    price_output_per_mtok: float = 0.50


@dataclass
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    timezone: ZoneInfo
    batch_minutes: int = 15
    retention_days: int = 30
    about_me: str = ""
    default_keywords: list[str] = field(default_factory=list)
    ai: AIConfig = field(default_factory=AIConfig)

    @property
    def data_dir(self) -> Path:
        return DATA_DIR

    @property
    def lessons_path(self) -> Path:
        return DATA_DIR / "lessons.md"


def load_config(path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    path = path or Path(os.environ.get("MYBOT_CONFIG", ROOT / "config.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    missing = [k for k in ("TG_API_ID", "TG_API_HASH", "TG_BOT_TOKEN", "ANTHROPIC_API_KEY")
               if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Thiếu biến môi trường trong .env: {', '.join(missing)}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Config(
        api_id=int(os.environ["TG_API_ID"]),
        api_hash=os.environ["TG_API_HASH"],
        bot_token=os.environ["TG_BOT_TOKEN"],
        timezone=ZoneInfo(raw.get("timezone", "Asia/Ho_Chi_Minh")),
        batch_minutes=int(raw.get("batch_minutes", 15)),
        retention_days=int(raw.get("retention_days", 30)),
        about_me=(raw.get("about_me") or "").strip(),
        default_keywords=[str(k) for k in raw.get("default_keywords") or []],
        ai=AIConfig(**(raw.get("ai") or {})),
    )
