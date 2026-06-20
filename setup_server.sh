#!/bin/bash
set -e

echo "======================================"
echo "  Elon Bot - Server Setup Script"
echo "======================================"

# ── 1. System update ──────────────────────
echo "[1/7] Updating system..."
apt update -y && apt upgrade -y

# ── 2. Install Python 3.11 ───────────────
echo "[2/7] Installing Python 3.11..."
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip git curl

# ── 3. Install PostgreSQL ────────────────
echo "[3/7] Installing PostgreSQL..."
apt install -y postgresql postgresql-contrib
systemctl start postgresql
systemctl enable postgresql

# Create database and user
sudo -u postgres psql <<SQL
CREATE USER elonbot WITH PASSWORD 'elonbot2025';
CREATE DATABASE elonbot OWNER elonbot;
GRANT ALL PRIVILEGES ON DATABASE elonbot TO elonbot;
SQL

echo "✅ PostgreSQL ready — database: elonbot, user: elonbot, pass: elonbot2025"

# ── 4. Install Redis ─────────────────────
echo "[4/7] Installing Redis..."
apt install -y redis-server
systemctl start redis-server
systemctl enable redis-server
echo "✅ Redis ready"

# ── 5. Clone bot ────────────────────────
echo "[5/7] Cloning bot..."
cd /root
if [ -d "bot" ]; then
    cd bot && git pull
else
    git clone https://github.com/tinysagaofficial-hash/bot.git bot
    cd bot
fi

# ── 6. Install Python deps ───────────────
echo "[6/7] Installing Python dependencies..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ── 7. Create .env ───────────────────────
echo "[7/7] Creating .env file..."
cat > .env <<EOF
BOT_TOKEN=8522833323:AAGDy4cHVnugYF2_FPtnzeP1sYqSxtUdr4g
API_ID=35514737
API_HASH=86082d0492087b10ff85b2a443e7d26f
DATABASE_URL=postgresql+asyncpg://elonbot:elonbot2025@localhost/elonbot
REDIS_URL=redis://localhost:6379/0
ADMIN_IDS=8132072022,705457366
TRIAL_HOURS=24
PAYMENT_CARD=9860 0803 2665 3245
CARD_OWNER=Ibrohimhalilullo Habibullayev
ADMIN_PANEL_PORT=8080
EOF

# ── 8. Create systemd service ────────────
echo "Creating systemd service..."
cat > /etc/systemd/system/elonbot.service <<EOF
[Unit]
Description=Elon Bot
After=network.target postgresql.service redis-server.service

[Service]
WorkingDirectory=/root/bot
ExecStart=/root/bot/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable elonbot
systemctl start elonbot

echo ""
echo "======================================"
echo "  ✅ SETUP COMPLETE!"
echo "======================================"
echo ""
echo "Bot status:  systemctl status elonbot"
echo "Bot logs:    journalctl -u elonbot -f"
echo "Admin panel: http://$(curl -s ifconfig.me):8080"
echo "Admin login: admin / elon2025"
echo ""
