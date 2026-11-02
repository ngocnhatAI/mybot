import asyncio
import logging
import sys

from . import app
from .config import load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    cfg = load_config()
    if command == "login":
        asyncio.run(app.login(cfg))
    elif command == "run":
        asyncio.run(app.run(cfg))
    else:
        raise SystemExit("Dùng: python -m mybot [run|login]")


if __name__ == "__main__":
    main()
