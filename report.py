"""ساخت گزارش تلگرام (دوزبانه) و تقسیم پیام‌ها به باتچ‌های امن تلگرام."""
from __future__ import annotations

import datetime
import html
from collections import Counter

import jdatetime

TELEGRAM_MAX = 4000  # پیام تا ۴۰۹۶ کاراکتر


def esc(t: str) -> str:
    return html.escape(t or "", quote=False)


def _jd(t: float) -> str:
    try:
        return jdatetime.date.fromgregorian(date=datetime.date.fromtimestamp(t)).strftime("%Y/%m/%d")
    except Exception:
        return datetime.date.fromtimestamp(t).strftime("%Y-%m-%d")


def fmt_time(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def _score_emoji(score: int) -> str:
    if score >= 70:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🔴"


def project_block(p, now_ts: float) -> str:
    verdict = p.get("verdict", "")
    s = p.get("score", 0)
    chain = "، ".join(p.get("chain_hints", [])) or "نامشخص"
    domain = (p.get("domain") or "").strip() or "نامشخص"

    lines = [
        f"<b>{esc(p['title'][:140])}</b>",
        f"{_score_emoji(s)} <b>امتیاز اعتبار: {s}/100</b> — {esc(verdict)}",
        f"🔗 {esc(p['url'])}",
        f"🕸 دامنه: <code>{esc(domain)}</code> • ⛓ زنجیره: {esc(chain)}",
    ]
    why = p.get("why_good", [])
    if why:
        lines.append("✅ " + " • ".join(esc(w) for w in why[:3]))
    cautions = p.get("cautions", [])
    if cautions:
        lines.append("❗ " + " • ".join(esc(c) for c in cautions[:3]))
    gh = p.get("github_url")
    if gh:
        lines.append(f"🐙 {esc(gh)}")
    socials = p.get("socials", [])
    if socials:
        lines.append("📣 " + " • ".join(esc(x) for x in socials[:4]))
    if p.get("free"):
        lines.append("🎁 <b>رایگان:</b> " + "، ".join(esc(f) for f in p.get("free")[:5]))

    lines.append("")  # راهنمای ثبت‌نام
    lines.append("📋 <b>راهنمای ثبت‌نام (قدم‌به‌قدم):</b>")
    for i, step in enumerate(p.get("steps", []), 1):
        lines.append(f"  {i}. {esc(step)}")
    lines.append("")
    return "\n".join(lines)


def build_report(projects: list[dict], run_stats: dict, now_ts: float) -> str:
    header = [
        "📡 <b>رادار پروژه‌های رایگان کریپتو و NFT</b>",
        f"🗓 {_jd(now_ts)} — {fmt_time(now_ts)}",
        f"🔎 {len(projects)} پروژهٔ جدید پیدا شد (فقط موارد بالای آستانهٔ اعتبار)",
        "",
        "<i>⚠️ هیچ سیستمی کلاهبرداری را ۱۰۰٪ تشخیص نمی‌دهد؛ این گزارش «پیش‌پالایش» است و همیشه قبل از ثبت‌نام، خودتان تحقیق کنید (DYOR).</i>",
        "",
    ]

    blocks = [project_block(p, now_ts) for p in projects]
    footer = [
        "",
        "—",
        f"<b>خلاصه اسکن:</b> {esc(run_stats.get('status_line', ''))}",
        f"⏱ زمان اجرا: {run_stats.get('duration', 0):.1f} ثانیه",
        "",
        "برای کنترل: /status | /watch | /feeds | /start",
    ]

    full = "\n".join(header + blocks + footer)
    return full


def split_message(text: str) -> list[str]:
    """تقسیم پیام به باتچ‌های ≤ TELEGRAM_MAX بدون شکستن تگ HTML."""
    if len(text) <= TELEGRAM_MAX:
        return [text]
    chunks: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        candidate = block if not cur else cur + "\n\n" + block
        if len(candidate) <= TELEGRAM_MAX:
            cur = candidate
            continue
        # بلوک فعلی تنها از حد مجاز بیشتر است: در مرز خطوط بشکن
        if cur:
            chunks.append(cur)
            cur = ""
        lines = block.split("\n")
        tmp = ""
        for ln in lines:
            cand = ln if not tmp else tmp + "\n" + ln
            if len(cand) <= TELEGRAM_MAX:
                tmp = cand
            else:
                if tmp:
                    chunks.append(tmp)
                tmp = ln
        if tmp:
            cur = tmp
    if cur:
        chunks.append(cur)
    return chunks


def build_help_text(now_ts: float) -> str:
    return (
        "🤖 <b>رادار پروژه‌های رایگان کریپتو و NFT</b>\n"
        "\n"
        "این ربات به‌صورت دوره‌ای این سورس‌ها را می‌گردد:\n"
        "• گیت‌هاب (مخازن جدید کریپتو/NFT)\n"
        "• ردیت (CryptoAirdrops, airdrops, NFT, ...)\n"
        "• خبرگزاری‌ها (Cointelegraph، CoinDesk، Decrypt، ...)\n"
        "• یوتیوب (در صورت تنظیم API key)\n"
        "• توییتر/X (در صورت تنظیم توکن یا دسترسی RSSHub)\n"
        "• فیدهای دلخواه شما (/watch)\n"
        "\n"
        "پروژه‌های «رایگان» (free mint / free claim / airdrop) که تازه اعلام شده‌اند را با امتیاز اعتبارسنجی و راهنمای ثبت‌نام به شما گزارش می‌دهد.\n"
        "\n"
        "<b>دستورها:</b>\n"
        "/start — ثبت‌نام برای دریافت گزارش\n"
        "/stop — لغو دریافت گزارش\n"
        "/status — وضعیت سورس‌ها و آخرین اسکن\n"
        "/watch add rss <i>آدرس</i> <i>برچسب</i> — افزودن فید RSS\n"
        "/watch add youtube <i>ChannelID</i> <i>برچسب</i> — کانال یوتیوب\n"
        "/watch add twitter <i>username</i> <i>برچسب</i> — حساب توییتر (از طریق RSSHub)\n"
        "/watch remove <i>شماره</i> — حذف فید (شماره را با /feeds ببینید)\n"
        "/feeds — لیست فیدهای دلخواه شما\n"
        "/scan — اسکن فوری همین حالا\n"
        "\n"
        "<b>👁 پیگیری پروژه (تا لانچ و بعد از آن):</b>\n"
        "/track add <i>نام توکن</i> — زیر نظر گرفتن یک توکن/NFT (تا لیست شدن)\n"
        "/track add <i>آدرس سایت یا توییتر</i> — رصد صفحه برای اعلام لانچ/مینت\n"
        "/track list — وضعیت پروژه‌های زیر نظر\n"
        "/track remove <i>شماره</i> — حذف از پیگیری\n"
        "/position <i>شماره</i> <i>تعداد</i> <i>هزینه</i> — ثبت موقعیت برای محاسبهٔ سود (هزینهٔ ۰ = ایردراپ رایگان)\n"
        "/position clear <i>شماره</i> — پاک کردن موقعیت\n"
        "\n"
        "/help — این راهنما\n"
        "\n"
        "⚠️ <b>نکتهٔ امنیتی:</b> برای هر پروژه یک کیف پول جدید و جدا بسازید. هیچ‌وقت عبارت بازیابی (Seed Phrase) را جایی وارد نکنید."
    )


def build_status_text(source_statuses: dict[str, str], last_stats, next_scan_ts: float | None) -> str:
    lines = [
        "📊 <b>وضعیت رادار</b>",
        "",
        "<b>منابع:</b>",
    ]
    for src, st in source_statuses.items():
        emoji = "✅" if st.startswith("✅") else ("⚠️" if st.startswith("⚠") else "⛔")
        lines.append(f"{emoji} {src}: {esc(st)}")

    if last_stats:
        lines.append("")
        lines.append(f"<b>آخرین اسکن:</b> {fmt_time(last_stats['ts'])}")
        lines.append(f"  نامزدها: {last_stats['candidates']} | پروژهٔ گزارش‌شده: {last_stats['projects']} | مدت: {last_stats['duration_sec']:.1f}s")
    if next_scan_ts:
        lines.append(f"⏭ اسکن بعدی: <b>{fmt_time(next_scan_ts)}</b>")
    lines.append("")
    lines.append("برای اسکن فوری: /scan")
    return "\n".join(lines)
