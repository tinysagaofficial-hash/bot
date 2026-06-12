import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv(
    "BOT_TOKEN", "8522833323:AAGDy4cHVnugYF2_FPtnzeP1sYqSxtUdr4g")
API_ID: int = int(os.getenv("API_ID", "35514737"))
API_HASH: str = os.getenv("API_HASH", "86082d0492087b10ff85b2a443e7d26f")
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:////data/elon_bot.db")
ADMIN_IDS: list[int] = [
    int(x) for x in os.getenv("ADMIN_IDS", "8132072022,705457366").split(",") if x.strip()
]
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "@Halilulloh2525")
TRIAL_HOURS: int = int(os.getenv("TRIAL_HOURS", "24"))

# Delay between group sends (seconds) — keeps account safe from spam detection
SEND_DELAY: float = float(os.getenv("SEND_DELAY", "2.5"))

# Scheduler check interval (seconds)
SCHEDULER_INTERVAL: int = 30

# Payment info (shown in Obunalarim → Obunani uzaytirish)
PAYMENT_CARD: str = os.getenv("PAYMENT_CARD", "9860 0803 2665 3245")
CARD_OWNER: str = os.getenv("CARD_OWNER", "Ibrohimhalilullo Habibullayev")

# Admin web panel credentials
ADMIN_PANEL_USER: str = os.getenv("ADMIN_PANEL_USER", "admin")
ADMIN_PANEL_PASS: str = os.getenv("ADMIN_PANEL_PASS", "elon2025")
ADMIN_PANEL_PORT: int = int(os.getenv("PORT", os.getenv("ADMIN_PANEL_PORT", "8080")))
REDIS_URL: str = os.getenv("REDIS_URL", "")

# Tariff plans: key → (display_name, price_uzs, duration_days)
TARIFFS: dict = {
    "1_oy":  ("1 oy",  50_000,  30),
    "3_oy":  ("3 oy", 120_000,  90),
    "6_oy":  ("6 oy", 200_000, 180),
}
