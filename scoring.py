"""موتور اعتبارسنجی پروژه — امتیاز ۰ تا ۱۰۰.

هیچ سیستمی نمی‌تواند ۱۰۰٪ کلاهبرداری را تشخیص دهد؛ این موتور نشانه‌های معتبر بودن و
نشانه‌های هشدار را جمع می‌زند تا گزارش اولیهٔ قابل اعتمادی بدهد. همیشه DYOR کنید.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass, field

from filters import (
    tld_penalty,
    red_flags,
    detect_chain,
)

try:  # اختیاری
    import whois as _whois
    HAS_WHOIS = True
except Exception:
    HAS_WHOIS = False

WHEN = __import__("time")


@dataclass
class ScoreResult:
    score: int = 40
    why_good: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    red_flag_count: int = 0


# ---------- WHOIS (اختیاری و با تایم‌اوت) ----------
def _domain_age_days(domain: str) -> int | None:
    if not HAS_WHOIS or not domain or "." not in domain:
        return None
    if not re.match(r"^[a-z0-9\-\.]+\.[a-z]{2,}$", domain):
        return None

    def _lookup():
        try:
            w = _whois.whois(domain)
            if not w.creation_date:
                return None
            dates = w.creation_date
            if isinstance(dates, list):
                dates = dates[0]
            age = (WHEN.time() - dates.timestamp()) / 86400
            return max(age, 0)
        except Exception:
            return None

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_lookup)
            return fut.result(timeout=10)
    except (FutTimeout, Exception):
        return None


def _github_stars(candidate) -> int:
    return int(candidate.extra.get("stars", 0) or 0)


def score_candidate(candidate, mention_count: int = 1) -> ScoreResult:
    """امتیازدهی بر اساس اطلاعات موجود."""
    res = ScoreResult()
    score = 40

    desc = f"{candidate.title} {candidate.description} {candidate.extra.get('topics', '')}"
    domain = candidate.domain

    # 1) دامنه و TLD
    score += tld_penalty(domain)

    # 2) سن دامنه (فقط اگر python-whois نصب باشد)
    age_days = _domain_age_days(domain) if domain else None
    if age_days is not None:
        if age_days >= 180:
            score += 15
            res.why_good.append("دامنه بیش از ۶ ماه قدمت دارد (نشانهٔ خوب)")
        elif age_days >= 30:
            score += 8
            res.why_good.append("دامنه بیش از یک ماه قدمت دارد")
        else:
            score += 0
            res.cautions.append(f"دامنه تازه‌ثبت‌شده است (تنها {int(age_days)} روز)")

    # 3) گیت‌هاب
    stars = _github_stars(candidate)
    if candidate.github_url:
        if stars >= 50:
            score += 15
            res.why_good.append(f"گیت‌هاب فعال با {stars} ستاره")
        elif stars >= 10:
            score += 10
            res.why_good.append(f"گیت‌هاب موجود با {stars} ستاره")
        else:
            score += 5
            res.why_good.append("گیت‌هاب اوپن‌سورس موجود است")
    else:
        score += 0

    # 4) شبکه‌های اجتماعی ذکرشده
    n_socials = len(candidate.socials)
    if n_socials:
        bonus = min(n_socials, 2) * 5
        score += bonus
        res.why_good.append(f"لینک شبکه‌های اجتماعی در متن یافت شد ({n_socials} مورد)")

    # 5) دیده‌شدن در چند منبع مستقل
    if mention_count >= 2:
        score += 10
        res.why_good.append("در چند منبع مستقل دیده شده است")

    # 6) اشاره به مارکت‌پلیس/لانچ‌پد شناخته‌شده
    known_platforms = [
        "opensea", "magic eden", "magiceden", "coinbase", "binance", "uniswap",
        "raydium", "jup.ag", "jupiter", "gate.io", "okx", "bybit", "kucoin",
        "blur", "tensor", "solanart",
    ]
    mentions = [p for p in known_platforms if p in desc.lower()]
    if mentions:
        score += 5
        res.why_good.append(f"ذکر {', '.join(mentions)} (نشانهٔ زیرساخت واقعی)")

    # 7) پرچم‌های قرمز
    flags = red_flags(desc)
    res.red_flag_count = len(flags)
    if flags:
        score -= min(8 * len(flags), 30)
        for f in flags:
            res.cautions.append(f"عبارت هشدار: «{f}»")

    # 8) بدون وب‌سایت مشخص / فقط لینک شبکه اجتماعی
    if domain in ("reddit.com", "youtube.com", "x.com", "twitter.com", "github.com", ""):
        res.cautions.append("وب‌سایت رسمی مستقل دیده نشد — آدرس را از منابع رسمی بررسی کنید")

    # محدودسازی
    score = max(0, min(100, score))
    res.score = score
    return res


def verdict_for(score: int, red_flag_count: int) -> str:
    if red_flag_count and score < 60:
        return "⚠️ نیاز به بررسی جدی دارد"
    if score >= 70:
        return "✅ نسبتاً معتبر به نظر می‌رسد"
    if score >= 50:
        return "🔎 به‌نظر قابل بررسی است — DYOR کنید"
    return "⚠️ ریسک بالاست — با احتیاط برخورد کنید"
