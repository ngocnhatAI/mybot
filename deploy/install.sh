#!/usr/bin/env bash
# Cài (hoặc cài lại) mybot trên VPS Ubuntu, ví dụ Oracle ARM. Chạy lại nhiều lần không sao.
#   cd ~/mybot && bash deploy/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="$(id -un)"
cd "$APP_DIR"

sudo apt-get update -q
sudo apt-get install -y -q python3-venv python3-pip curl

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || { echo "Cần Python >= 3.10 (Ubuntu 22.04 trở lên)."; exit 1; }

if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@APP_USER@|$APP_USER|g" deploy/mybot.service \
  | sudo tee /etc/systemd/system/mybot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable mybot >/dev/null

missing=0
[ -f .env ] || { echo "Thiếu .env: chép từ máy cũ lên $APP_DIR/.env"; missing=1; }
[ -f data/user.session ] || { echo "Thiếu data/user.session: chép thư mục data/ từ máy cũ lên, hoặc chạy .venv/bin/python -m mybot login"; missing=1; }
if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale chưa đăng nhập: chạy 'sudo tailscale up' (cần cho /screen và /ultraview)."
fi

if [ "$missing" = 0 ]; then
  sudo systemctl restart mybot
  echo "Đã chạy mybot. Xem log: journalctl -u mybot -f"
else
  echo "Bổ sung các file trên rồi chạy: sudo systemctl restart mybot"
fi
