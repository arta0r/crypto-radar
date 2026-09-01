"""تنظیمات ربات — از فایل .env خوانده می‌شود."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)


class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    ADMIN_CHAT_ID: str = os.getenv("CHAT_ID", "").strip()

    # --- API keys (اختیاری) ---
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "").strip()
    TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    RSSHUB_INSTANCES: list[str] = [
        x.strip()
        for x in os.getenv("RSSHUB_INSTANCES", "https://rsshub.app").split(",")
        if x.strip()
    ]

    # --- رفتار اسکن ---
    SCAN_HOURS: int = int(os.getenv("SCAN_HOURS", "6") or "6")
    MIN_SCORE: int = int(os.getenv("MIN_SCORE", "50") or "50")
    LOOKBACK_DAYS: int = int(os.getenv("LOOKBACK_DAYS", "14") or "14")
    MAX_PROJECTS_PER_REPORT: int = int(
        os.getenv("MAX_PROJECTS_PER_REPORT", "8") or "8"
    )

    # پیگیری: حداقل درصد تغییر قیمت برای اعلام گزارش جدید
    TRACK_NOTIFY_PCT: int = int(os.getenv("TRACK_NOTIFY_PCT", "10") or "10")

    # پیگیری خودکار از روی تنظیمات (برای GitHub Actions و حالت‌های بدون ربات تعاملی):
    # نام توکن‌ها/NFTها با کاما جدا — مثل: grass, somecoin
    TRACK_COINS: str = os.getenv("TRACK_COINS", "").strip()

    # --- فنی ---
    DB_PATH: Path = DB_DIR / "bot.db"
    USER_AGENT: str = "CryptoRadarBot/1.0 (+personal research bot)"
    REQUEST_TIMEOUT: int = 15
