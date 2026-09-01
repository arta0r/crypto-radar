"""CryptRadar — ربات پیدا کردن پروژه‌های رایگان کریپتو/NFT جدید و گزارش به تلگرام.

اجرا:
    python main.py                 → اسکن و ارسال گزارش به تلگرام (بدون ربات تعاملی)
    python main.py --bot           → همراه با ربات تلگرام (دستورها: /scan /status /watch ...)
    python main.py --once          → فقط یک اسکن انجام بده و تمام
    python main.py --stats         → آمار دیتابیس
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import signal
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import feedparser
import requests

from config import Config
from database import Database

import report as report_mod
from filters import (
    free_terms_found, detect_chain, project_key, is_free,
    is_crypto_related, is_tutorial, has_intent, extract_domain,
    extract_socials, extract_github, is_question, is_github_tool,
)
from registration import build_steps
from scoring import score_candidate, verdict_for
import tracker as tracker_mod

SCAN_LOCK = threading.Lock()


# ============================================================ Candidate
@dataclass
class Candidate:
    title: str
    description: str
    url: str
    source: str = "rss"
    domain: str = ""
    published: float = 0.0
    kind: str = "unknown"
    chain_hints: list[str] = field(default_factory=list)
    socials: list[str] = field(default_factory=list)
    github_url: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.domain:
            self.domain = extract_domain(self.url)


# ============================================================ گیت‌هاب
GITHUB_SEARCH_QUERIES = [
    ("topic:nft", 0),
    ("topic:airdrops", 0),
    ('"free mint" OR "airdrop"', 2),
    ('"whitelist" nft', 2),
]
REQUEST_DELAY = 8  # ثانیه بین کوئری‌ها (احترام به rate limit)


def _github_search(query: str, created_after: str, headers: dict, timeout: int) -> list[dict]:
    r = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": f"{query} created:>{created_after}", "sort": "updated", "order": "desc", "per_page": 30},
        headers=headers,
        timeout=timeout,
    )
    if r.status_code == 200:
        return r.json().get("items", [])
    if r.status_code in (403, 429):
        return []
    return []


def github_fetch(config) -> tuple[list, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": config.USER_AGENT}
    created_after = (datetime.utcnow() - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    candidates: list = []
    seen: set = set()
    ok_queries = 0
    for q, min_stars in GITHUB_SEARCH_QUERIES:
        try:
            items = _github_search(q, created_after, headers, config.REQUEST_TIMEOUT)
            ok_queries += 1
            for it in items:
                name = it.get("full_name", "")
                desc = it.get("description") or ""
                topics = " ".join(it.get("topics", []) or [])
                stars = it.get("stargazers_count", 0)
                repo_url = it.get("html_url", "")
                if repo_url in seen:
                    continue
                if stars < min_stars:
                    continue
                if not desc and stars < 5:
                    continue
                combined = f"{name} {desc} {topics}"
                if not is_crypto_related(combined):
                    continue
                if is_github_tool(name, desc):
                    continue
                if is_tutorial(f"{name} {desc}"):
                    continue
                seen.add(repo_url)
                candidates.append(Candidate(
                    title=name,
                    description=(desc or "منبع: گیت‌هاب").strip(),
                    url=repo_url,
                    source="github",
                    domain="github.com",
                    github_url=repo_url,
                    kind="nft" if "nft" in topics.lower() or "nft" in (desc or "").lower() else "unknown",
                    socials=extract_socials(f"{desc} {topics}"),
                    extra={"stars": stars, "topics": topics},
                ))
        except requests.RequestException:
            pass
        if ok_queries < len(GITHUB_SEARCH_QUERIES):
            time.sleep(REQUEST_DELAY)
    return candidates, f"✅ فعال — {len(candidates)} مخزن جدید بررسی شد"


# ============================================================ ردیت
SUBREDDITS = [
    ("CryptoAirdrops", "https://www.reddit.com/r/CryptoAirdrops/new/.rss"),
    ("airdrops", "https://www.reddit.com/r/airdrops/new/.rss"),
    ("NFT", "https://www.reddit.com/r/NFT/new/.rss"),
    ("CryptoCurrency", "https://www.reddit.com/r/CryptoCurrency/new/.rss"),
    ("opensea", "https://www.reddit.com/r/opensea/new/.rss"),
]
REDDIT_UA = "CryptoRadarBot/1.0 (personal research bot; not a scraper)"


def _reddit_entries(url: str, headers: dict, timeout: int) -> list[tuple[str, str, str]]:
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
        feed = feedparser.parse(r.content)
        return [(e.get("title", ""), e.get("summary", ""), e.get("link", "")) for e in feed.entries]
    except requests.RequestException:
        return []


def reddit_fetch(config) -> tuple[list, str]:
    headers = {"User-Agent": REDDIT_UA, "Accept": "application/rss+xml"}
    candidates: list = []
    total = 0
    for name, url in SUBREDDITS:
        for title, summary, link in _reddit_entries(url, headers, config.REQUEST_TIMEOUT):
            total += 1
            if is_question(title):
                continue
            candidates.append(Candidate(
                title=title.strip(),
                description=summary.strip() or title.strip(),
                url=link,
                source="reddit",
                domain="reddit.com",
                socials=extract_socials(summary),
                extra={"subreddit": f"r/{name}"},
            ))
        time.sleep(1)
    return candidates, f"✅ فعال — {total} پست از {len(SUBREDDITS)} سابردیت بررسی شد"


# ============================================================ خبرگزاری‌ها
NEWS_FEEDS = [
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Bitcoin.com News", "https://news.bitcoin.com/feed/"),
    ("Cointelegraph NFT", "https://cointelegraph.com/rss/tag/nft"),
    ("Cointelegraph Web3", "https://cointelegraph.com/rss/tag/web3"),
]


def _rss_parse(url: str, headers: dict, timeout: int) -> list[tuple[str, str, str]]:
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
        feed = feedparser.parse(r.content)
        return [(e.get("title", ""), e.get("summary", ""), e.get("link", "")) for e in feed.entries]
    except requests.RequestException:
        return []


def rss_fetch(config) -> tuple[list, str]:
    headers = {"User-Agent": config.USER_AGENT}
    candidates: list = []
    total = 0
    for name, url in NEWS_FEEDS:
        for title, summary, link in _rss_parse(url, headers, config.REQUEST_TIMEOUT):
            total += 1
            candidates.append(Candidate(
                title=title.strip(),
                description=summary.strip() or title.strip(),
                url=link,
                source="news",
                domain="",
                socials=extract_socials(summary),
                github_url=extract_github(summary),
                extra={"outlet": name},
            ))
    return candidates, f"✅ فعال — {total} خبر از {len(NEWS_FEEDS)} منبع بررسی شد"


# ============================================================ یوتیوب
YT_SEARCH_QUERIES = [
    "free nft mint new project",
    "crypto airdrop claim free",
    "new token launch whitelist",
]
SEARCH_MAX = 12


def _youtube_search(api_key: str, query: str, published_after: str, timeout: int) -> list[dict]:
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "date",
            "maxResults": SEARCH_MAX,
            "publishedAfter": published_after,
            "key": api_key,
        },
        timeout=timeout,
    )
    if r.status_code == 200:
        return r.json().get("items", [])
    return []


def youtube_fetch(config) -> tuple[list, str]:
    if not config.YOUTUBE_API_KEY:
        return [], "⛔ غیرفعال — YOUTUBE_API_KEY تنظیم نشده (اختیاری)"
    published_after = (datetime.utcnow() - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    candidates: list = []
    for q in YT_SEARCH_QUERIES:
        try:
            items = _youtube_search(config.YOUTUBE_API_KEY, q, published_after, config.REQUEST_TIMEOUT)
            for it in items:
                sn = it.get("snippet", {})
                title = sn.get("title", "")
                desc = sn.get("description", "")
                if is_tutorial(f"{title} {desc}"):
                    continue
                video_id = it.get("id", {}).get("videoId", "")
                if not video_id:
                    continue
                channel = sn.get("channelTitle", "")
                candidates.append(Candidate(
                    title=title.strip(),
                    description=(desc or "").strip() or title.strip(),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    source="youtube",
                    domain="youtube.com",
                    socials=extract_socials(desc),
                    extra={"channel": channel},
                ))
        except requests.RequestException:
            pass
        time.sleep(1)
    return candidates, f"✅ فعال — {len(candidates)} ویدیو با API یافت شد"


# ============================================================ توییتر/X
TWITTER_QUERY = '("free mint" OR "airdrop" OR "allowlist" OR "whitelist" OR "free claim") -is:retweet -is:reply lang:en'
WATCH_HANDLES = [
    ("coindesk", "CoinDesk"),
    ("Cointelegraph", "Cointelegraph"),
    ("decryptmedia", "Decrypt"),
]


def _twitter_v2(bearer: str, timeout: int) -> list[dict]:
    r = requests.get(
        "https://api.twitter.com/2/tweets/search/recent",
        params={
            "query": TWITTER_QUERY,
            "max_results": 30,
            "tweet.fields": "created_at,author_id,text",
            "expansions": "author_id",
            "user.fields": "username,name",
        },
        headers={"Authorization": f"Bearer {bearer}"},
        timeout=timeout,
    )
    if r.status_code != 200:
        return []
    data = r.json()
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    out = []
    for t in data.get("data", []):
        author = users.get(t.get("author_id"), {})
        username = author.get("username", "unknown")
        out.append({"text": t.get("text", ""), "author": username,
                    "id": t.get("id", ""), "created_at": t.get("created_at", "")})
    return out


def twitter_fetch(config) -> tuple[list, str]:
    candidates: list = []
    if config.TWITTER_BEARER_TOKEN:
        try:
            tweets = _twitter_v2(config.TWITTER_BEARER_TOKEN, config.REQUEST_TIMEOUT)
            for tw in tweets:
                candidates.append(Candidate(
                    title=f"@{tw['author']}",
                    description=tw["text"],
                    url=f"https://x.com/{tw['author']}/status/{tw['id']}",
                    source="twitter",
                    domain="x.com",
                    extra={"author": tw["author"]},
                ))
            return candidates, f"✅ فعال — {len(candidates)} توییت (API v2)"
        except requests.RequestException:
            pass
    for instance in config.RSSHUB_INSTANCES:
        ok = 0
        for handle, label in WATCH_HANDLES:
            url = f"{instance}/twitter/user/{handle}"
            try:
                r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=config.REQUEST_TIMEOUT)
                if r.status_code != 200:
                    continue
                feed = feedparser.parse(r.content)
                for e in feed.entries[:8]:
                    ok += 1
                    text = e.get("title", "")
                    link = e.get("link", "")
                    candidates.append(Candidate(
                        title=f"@{handle}",
                        description=text,
                        url=link,
                        source="twitter",
                        domain="x.com",
                        extra={"author": handle, "via": instance},
                    ))
            except Exception:
                continue
        if ok:
            return candidates, f"✅ فعال — {len(candidates)} توییت از RSSHub ({instance})"
        time.sleep(1)
    return [], "⚠️ غیرفعال — توکن توییتر یا RSSHub در دسترس نیست (اختیاری)"


# ============================================================ فیدهای دلخواه
def _feed_fetch(url: str, headers: dict, timeout: int) -> list[tuple[str, str, str]]:
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
        feed = feedparser.parse(r.content)
        return [(e.get("title", ""), e.get("summary", ""), e.get("link", "")) for e in feed.entries]
    except requests.RequestException:
        return []


def _youtube_channel_rss(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def watchlist_fetch(config, feeds: list[dict]) -> tuple[list, str]:
    candidates: list = []
    total = 0
    headers = {"User-Agent": config.USER_AGENT}
    for feed in feeds:
        kind = feed.get("kind", "rss")
        url = feed.get("url", "")
        label = feed.get("label") or feed.get("url", "")
        if not url:
            continue
        if kind == "youtube":
            url = _youtube_channel_rss(url)
            src = "youtube"
            urls = [url]
        elif kind == "twitter":
            src = "twitter"
            urls = [f"{inst}/twitter/user/{url}" for inst in config.RSSHUB_INSTANCES]
        else:
            src = "watch"
            urls = [url]
        for u in urls:
            entries = _feed_fetch(u, headers, config.REQUEST_TIMEOUT)
            if not entries:
                continue
            for title, summary, link in entries:
                total += 1
                candidates.append(Candidate(
                    title=f"{label} — {title}".strip(),
                    description=summary.strip() or title.strip(),
                    url=link or u,
                    source=src,
                    domain="",
                    socials=extract_socials(summary),
                    github_url=extract_github(summary),
                    extra={"feed": label},
                ))
            break
    return candidates, f"✅ فعال — {total} مورد از {len(feeds)} فید دلخواه"



# ============================================================ موتور اسکن
def _candidate_eligible(c: "Candidate") -> bool:
    """پیش‌فیلتر: باید کریپتو باشد، دعوت به اقدام (claim/mint/...) داشته باشد و رایگان باشد."""
    text = f"{c.title} {c.description}"
    if not is_crypto_related(text):
        return False
    if not has_intent(text):
        return False
    if not is_free(text):
        return False
    if is_tutorial(text) and c.source in ("youtube", "news"):
        return False
    return True


def scan_pipeline(config: Config, db: Database) -> tuple[list[dict], dict]:
    t0 = time.time()
    sources = {
        "گیت‌هاب": github_fetch,
        "ردیت": reddit_fetch,
        "خبرگزاری‌ها": rss_fetch,
        "یوتیوب": youtube_fetch,
        "توییتر/X": twitter_fetch,
    }
    source_statuses: dict[str, str] = {}
    module_keys: dict[str, set] = {}        # هر منبع -> کلیدهای پروژه‌های دیده‌شده
    mentions: Counter = Counter()           # کلید پروژه -> تعداد «منابع مستقل» که دیده‌اند
    all_candidates = []

    def _count_module(module: str, cands):
        keys = {project_key(c.title, c.url, c.domain, c.github_url) for c in cands}
        module_keys[module] = set(k for k in keys if k)
        for k in module_keys[module]:
            mentions[k] += 1

    for name, fetcher in sources.items():
        try:
            cands, status = fetcher(config)
            source_statuses[name] = status
            all_candidates.extend(cands)
            _count_module(name, cands)
        except Exception as e:  # یک منبع خراب، بقیه را خراب نکند
            source_statuses[name] = f"❌ خطا: {e}"

    # فیدهای دلخواه کاربر
    feeds = db.all_feeds()
    if feeds:
        try:
            cands, status = watchlist_fetch(config, feeds)
            source_statuses["فیدهای دلخواه"] = status
            all_candidates.extend(cands)
            _count_module("فیدهای دلخواه", cands)
        except Exception as e:
            source_statuses["فیدهای دلخواه"] = f"❌ خطا: {e}"

    # --- امتیازدهی و انتخاب ---
    now = time.time()
    projects: list[dict] = []
    accepted_keys: set[str] = set()   # جلوگیری از تکراری در یک اسکن

    for c in all_candidates:
        if not _candidate_eligible(c):
            continue
        key = project_key(c.title, c.url, c.domain, c.github_url)
        if not key or key in accepted_keys:
            continue
        if db.is_seen_recent(key, config.LOOKBACK_DAYS):
            continue

        sr = score_candidate(c, mention_count=mentions.get(key, 1))
        free_terms = free_terms_found(f"{c.title} {c.description}")
        chains = detect_chain(f"{c.title} {c.description} {c.extra.get('topics', '')}")

        p = {
            "title": c.title,
            "url": c.url,
            "domain": c.domain,
            "source": c.source,
            "score": sr.score,
            "verdict": verdict_for(sr.score, sr.red_flag_count),
            "why_good": sr.why_good,
            "cautions": sr.cautions,
            "free": free_terms,
            "chain_hints": chains,
            "socials": c.socials[:4],
            "github_url": c.github_url,
            "key": key,
            "steps": build_steps(chains, free_terms),
        }
        accepted_keys.add(key)
        projects.append(p)

    # فیلتر آستانه امتیاز + مرتب‌سازی + سقف تعداد
    projects = [p for p in projects if p["score"] >= config.MIN_SCORE]
    projects.sort(key=lambda p: (p["score"], p.get("published", 0)), reverse=True)
    projects = projects[: config.MAX_PROJECTS_PER_REPORT]

    # ثبت در دیتابیس و آمار
    for p in projects:
        db.mark_seen(p["key"], p["title"], p["url"], p["source"], p["score"])

    duration = time.time() - t0
    db.add_scan_stats(len(all_candidates), len(projects), duration)
    db.set_setting("last_statuses", json.dumps(source_statuses, ensure_ascii=False))
    db.set_setting("last_scan_ts", str(time.time()))
    status_line = "; ".join(source_statuses.values())
    stats = {
        "statuses": source_statuses,
        "status_line": status_line,
        "duration": duration,
        "candidates_total": len(all_candidates),
    }
    return projects, stats


def run_once(config: Config, db: Database, notify: bool, send_fn) -> None:
    with SCAN_LOCK:
        print(f"[{time.strftime('%H:%M:%S')}] اسکن شروع شد...")
        tracker_mod.ensure_tracked_from_env(config, db)
        projects, stats = scan_pipeline(config, db)
        print(f"[{time.strftime('%H:%M:%S')}] {len(projects)} پروژهٔ جدید بالای آستانه.")

        # مخاطبان: چت‌های ثبت‌نام‌شده؛ اگر هیچ نبود و CHAT_ID تنظیم بود، همان
        targets = db.all_chats()
        if config.ADMIN_CHAT_ID:
            try:
                admin = int(config.ADMIN_CHAT_ID)
                db.add_chat(admin)  # ثبت تا در اجراهای بعد هم بماند
                if admin not in targets:
                    targets.append(admin)
            except ValueError:
                print("⚠️ CHAT_ID عددی نیست — نادیده گرفته شد.")

        if notify and projects:
            msg = report_mod.build_report(projects, stats, time.time())
            chunks = report_mod.split_message(msg)
            for chat_id in targets:
                for i, chunk in enumerate(chunks):
                    try:
                        send_fn(chat_id, chunk)
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"[تلگرام] ارسال به {chat_id} ناموفق: {e}")
            print(f"[{time.strftime('%H:%M:%S')}] گزارش به {len(targets)} چت ارسال شد.")

        # دور پیگیری (حتی اگر پروژه‌ی جدیدی نبود)
        try:
            for u in tracker_mod.tracker_pass(config, db):
                try:
                    send_fn(u["chat_id"], u["text"])
                except Exception as e:
                    print(f"[پیگیری] ارسال ناموفق: {e}")
        except Exception as e:
            print(f"[پیگیری] خطا: {e}")


# ============================================================ ربات تلگرام
def run_telegram(config: Config, db: Database, send_fn):
    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, ContextTypes, MessageHandler, filters,
    )

    async def _send(chat_id: int, text: str):
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML",
                                   disable_web_page_preview=True)

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        db.add_chat(chat.id)
        await _send(chat.id, report_mod.build_help_text(time.time()))

    async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        db.remove_chat(chat.id)
        await _send(chat.id, "خروج از فهرست گزارش‌ها انجام شد. برای بازگشت: /start")

    async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        await _send(chat.id, f"🆔 آیدی چت شما:\n<code>{chat.id}</code>\n\n(این عدد را برای گزارش‌ها یادداشت کنید)")

    async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        try:
            statuses = json.loads(db.get_setting("last_statuses", "{}"))
        except Exception:
            statuses = {}
        last = db.last_scan_stats()
        last_ts = db.get_setting("last_scan_ts")
        try:
            next_ts = float(last_ts) + config.SCAN_HOURS * 3600 if last_ts else _next_scan_ts(config)
        except Exception:
            next_ts = _next_scan_ts(config)
        if not statuses:
            statuses = {"—": "هنوز اسکنی اجرا نشده. با /scan شروع کنید."}
        await _send(chat.id, report_mod.build_status_text(statuses, last, next_ts))

    async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        if not SCAN_LOCK.acquire(blocking=False):
            await _send(chat.id, "اسکن دیگری در حال اجراست؛ کمی بعد دوباره تلاش کنید.")
            return
        try:
            await _send(chat.id, "🔎 اسکن شروع شد...")
            projects, stats = await asyncio.to_thread(scan_pipeline, config, db)
            msg = report_mod.build_report(projects, stats, time.time())
            chunks = report_mod.split_message(msg)
            for chunk in chunks:
                await _send(chat.id, chunk)
                await asyncio.sleep(0.5)
            await _run_tracker_and_notify()
        finally:
            SCAN_LOCK.release()

    async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        args = ctx.args or []
        if not args or args[0] not in ("add", "remove"):
            await _send(chat.id, "کاربرد:\n/watch add rss <آدرس> <برچسب>\n/watch add youtube <ChannelID> <برچسب>\n/watch add twitter <username> <برچسب>\n/watch remove <شماره>")
            return
        sub = args[0]
        if sub == "remove":
            if len(args) < 2:
                await _send(chat.id, "شمارهٔ فید را بدهید (با /feeds ببینید).")
                return
            try:
                db.remove_feed(int(args[1]))
                await _send(chat.id, "فید حذف شد.")
            except Exception:
                await _send(chat.id, "شماره نامعتبر است.")
            return
        # add
        if len(args) < 3:
            await _send(chat.id, "فرمت: /watch add <نوع> <آدرس> <برچسب>")
            return
        kind = args[1].lower()
        url = args[2]
        label = " ".join(args[3:]) or url
        if kind not in ("rss", "youtube", "twitter"):
            await _send(chat.id, "نوع باید rss یا youtube یا twitter باشد.")
            return
        if kind == "rss" and not url.startswith(("http://", "https://")):
            await _send(chat.id, "آدرس RSS باید با http شروع شود.")
            return
        db.add_feed(chat.id, kind, url, label)
        await _send(chat.id, f"✅ فید اضافه شد:\n{kind}: {url}\nبرچسب: {label}")

    async def cmd_feeds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        feeds = db.all_feeds()
        if not feeds:
            await _send(chat.id, "هنوز فیدی اضافه نکرده‌اید. با /watch add ... اضافه کنید.")
            return
        lines = ["📑 <b>فیدهای دلخواه:</b>", ""]
        for f in feeds:
            lines.append(f"{f['id']}. [{f['kind']}] {html.escape(f['url'])} — {html.escape(f['label'])}")
        lines.append("")
        lines.append("حذف با: /watch remove <شماره>")
        await _send(chat.id, "\n".join(lines))

    # ============ پیگیری پروژه (Tracking) ============
    async def cmd_track(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        args = ctx.args or []
        if not args or args[0] not in ("add", "list", "remove"):
            await _send(chat.id, "کاربرد:\n/track add <نام یا آدرس> [آدرس سایت]\n/track list\n/track remove <شماره>")
            return
        sub = args[0]
        if sub == "list":
            rows = db.tracked_for_chat(chat.id)
            if not rows:
                await _send(chat.id, "هنوز چیزی پیگیری نمی‌کنید. با /track add <نام> شروع کنید.")
                return
            lines = ["👁 <b>پروژه‌های زیر نظر:</b>", ""]
            for r in rows:
                lines.extend(tracker_mod.tracked_list_lines(r))
            lines.append("")
            lines.append("ثبت موقعیت برای محاسبهٔ سود: /position <شماره> <تعداد> <هزینه_دلار>")
            await _send(chat.id, "\n".join(lines))
            return
        if sub == "remove":
            if len(args) < 2:
                await _send(chat.id, "شمارهٔ پروژه را بدهید (با /track list ببینید).")
                return
            try:
                row = db.get_tracked(int(args[1]))
                if not row or row["chat_id"] != chat.id:
                    await _send(chat.id, "چنین پروژه‌ای برای شما نیست.")
                    return
                db.remove_tracked(int(args[1]))
                await _send(chat.id, "حذف شد.")
            except Exception:
                await _send(chat.id, "شماره نامعتبر است.")
            return
        # add
        target = args[1]
        name = " ".join(args[2:]) or ""
        if target.startswith("http"):
            # پیگیری یک وب‌سایت/توییتر
            kind = "twitter" if ("twitter.com" in target or "x.com" in target) else "website"
            url = target
            if not name:
                name = url.split("//")[-1].rstrip("/").split("/")[0]
            tid = db.add_tracked(chat.id, name, url, kind,
                                 note="رصد لانچ از صفحهٔ پروژه")
            await _send(chat.id, f"👁 <b>{name}</b> اضافه شد (id={tid}). هر اسکن صفحه را برای کلیدواژه‌های لانچ/مینت باز چک می‌کنم.")
            return
        # پیگیری یک توکن/NFT به نام
        found = await asyncio.to_thread(tracker_mod.resolve_asset, target)
        if found and found.get("id"):
            tid = db.add_tracked(chat.id, name or found["name"], "",
                                 "nft" if found["coin_type"] == "nfts" else "token",
                                 coingecko_id=found["id"], coin_type=found["coin_type"],
                                 price=found.get("price"))
            p = f" — قیمت فعلی: <b>${found['price']:,.4f}</b>" if found.get("price") else ""
            await _send(chat.id, f"📊 <b>{found['name']}</b> پیدا شد و پیگیری شروع شد (id={tid}).{p}\n\nهر {config.SCAN_HOURS} ساعت قیمت چک می‌شود و اگر بیش از {config.TRACK_NOTIFY_PCT}٪ تغییر کند خبر می‌دهم.\nبرای محاسبهٔ سود: /position {tid} <تعداد> <هزینه>")
        else:
            tid = db.add_tracked(chat.id, name or target, "", "token",
                                 note="در انتظار لیست شدن در CoinGecko")
            await _send(chat.id, f"⏳ <b>{name or target}</b> هنوز در CoinGecko لیست نشده (id={tid}).\nتا وقتی لیست شود در اسکن‌ها دنبالش می‌گردم و به محض لیست شدن خبر می‌دهم. 🚀")

    async def cmd_position(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return
        args = ctx.args or []
        if not args:
            await _send(chat.id, "کاربرد:\n/position <شماره‌پروژه> <تعداد> <هزینه‌ی کل به دلار>\n/position clear <شماره>")
            return
        if args[0] == "clear":
            if len(args) < 2:
                await _send(chat.id, "شماره بدهید.")
                return
            try:
                row = db.get_tracked(int(args[1]))
                if not row or row["chat_id"] != chat.id:
                    await _send(chat.id, "چنین پروژه‌ای برای شما نیست.")
                    return
                db.update_tracked(int(args[1]), position_qty=None, position_cost=None)
                await _send(chat.id, "موقعیت پاک شد.")
            except Exception:
                await _send(chat.id, "شماره نامعتبر است.")
            return
        if len(args) < 3:
            await _send(chat.id, "فرمت: /position <شماره> <تعداد> <هزینه به دلار>")
            return
        try:
            tid, qty, cost = int(args[0]), float(args[1]), float(args[2])
        except ValueError:
            await _send(chat.id, "اعداد را درست بنویسید (مثلاً /position 2 1000 0).")
            return
        row = db.get_tracked(tid)
        if not row or row["chat_id"] != chat.id:
            await _send(chat.id, "چنین پروژه‌ای برای شما نیست.")
            return
        db.update_tracked(tid, position_qty=qty, position_cost=cost)
        note = "هزینه ۰ = رایگان (ایردراپ) — سود خالص حساب می‌شود." if cost == 0 else ""
        await _send(chat.id, f"✅ موقعیت ثبت شد: {qty} واحد با {cost:,.2f}$ هزینه.\n{note}\nاز این به بعد سود/زیان در گزارش‌های پیگیری نمایش داده می‌شود.")

    async def _run_tracker_and_notify():
        """یک دور پیگیری و ارسال پیام‌های به‌روزرسانی."""
        try:
            updates = await asyncio.to_thread(tracker_mod.tracker_pass, config, db)
            for u in updates:
                try:
                    await _send(u["chat_id"], u["text"])
                except Exception as e:
                    print(f"[پیگیری] ارسال ناموفق: {e}")
        except Exception as e:
            print(f"[پیگیری] خطا: {e}")

    # --- اسکن دوره‌ای (در پس‌زمینه، بدون مسدود کردن ربات) ---
    async def scheduled_scan(ctx: ContextTypes.DEFAULT_TYPE):
        if not SCAN_LOCK.acquire(blocking=False):
            return
        try:
            def _do():
                return scan_pipeline(config, db)
            projects, stats = await asyncio.to_thread(_do)
            if not projects:
                return
            msg = report_mod.build_report(projects, stats, time.time())
            chunks = report_mod.split_message(msg)
            for chat_id in db.all_chats():
                for chunk in chunks:
                    try:
                        await _send(chat_id, chunk)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"[تلگرام] ارسال به {chat_id} ناموفق: {e}")
            print(f"[اسکن دوره‌ای] {len(projects)} پروژه به {len(db.all_chats())} چت ارسال شد.")
            await _run_tracker_and_notify()
        finally:
            SCAN_LOCK.release()

    # --- ثبت هندلرها ---
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.job_queue.run_repeating(scheduled_scan, interval=config.SCAN_HOURS * 3600, first=60)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("feeds", cmd_feeds))
    app.add_handler(CommandHandler("track", cmd_track))
    app.add_handler(CommandHandler("position", cmd_position))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   lambda u, c: _send(u.effective_chat.id, "برای راهنما: /help")))

    print("[ربات] شروع پولینگ تلگرام...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

    return app


# ============================================================ اسکجولر
def _next_scan_ts(config: Config) -> float:
    return time.time() + config.SCAN_HOURS * 3600


def scheduler_loop(config: Config, db: Database, send_fn, stop_event: threading.Event):
    while not stop_event.is_set():
        try:
            run_once(config, db, notify=True, send_fn=send_fn)
        except Exception as e:
            print(f"[اسکجولر] خطا: {e}")
        stop_event.wait(config.SCAN_HOURS * 3600)


def run_scheduler_forever(config: Config, db: Database, send_fn):
    stop_event = threading.Event()
    def _sig(*_a):
        print("خروج...")
        stop_event.set()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    thread = threading.Thread(target=scheduler_loop, args=(config, db, send_fn, stop_event), daemon=True)
    thread.start()
    print(f"اسکجولر فعال شد (هر {config.SCAN_HOURS} ساعت). برای خروج Ctrl+C.")
    while not stop_event.is_set():
        stop_event.wait(1)


# ============================================================ CLI
def main():
    parser = argparse.ArgumentParser(description="CryptRadar Bot")
    parser.add_argument("--bot", action="store_true", help="اجرای ربات تلگرام + اسکجولر")
    parser.add_argument("--once", action="store_true", help="فقط یک اسکن")
    parser.add_argument("--stats", action="store_true", help="نمایش آمار")
    args = parser.parse_args()

    config = Config()
    db = Database(config.DB_PATH)

    if args.stats:
        last = db.last_scan_stats()
        print("چت‌های ثبت‌نام‌شده:", len(db.all_chats()))
        print("فیدهای دلخواه:", len(db.all_feeds()))
        print("آخرین اسکن:", last)
        return

    # ارسال‌کنندهٔ تلگرام (همگام و مطمئن — بدون وابستگی به async؛ مخصوص --once و اسکجولر)
    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN تنظیم نشده است.")
        print("فایل .env را از روی .env.example بسازید و توکن را بگذارید.")
        return

    import requests as _req

    def _tg_call(method: str, payload: dict) -> dict:
        r = _req.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
            json=payload, timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"تلگرام {r.status_code}: {r.text[:200]}")
        return r.json()

    try:
        me = _tg_call("getMe", {})
    except Exception as e:
        print(f"❌ اتصال به تلگرام ناموفق (توکن اشتباه است یا اینترنت قطع است): {e}")
        sys.exit(1)
    print(f"✅ متصل به ربات: @{me.get('result', {}).get('username', '?')}")

    def send_plain(chat_id: int, text: str):
        _tg_call("sendMessage", {
            "chat_id": chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        })

    if args.once:
        run_once(config, db, notify=True, send_fn=send_plain)
        return

    if args.bot:
        run_telegram(config, db, send_plain)   # بلوک می‌شود (پولینگ)
        return

    run_scheduler_forever(config, db, send_plain)


if __name__ == "__main__":
    main()
