"""موتور پیگیری پروژه (Tracking).

- قیمت توکن/NFT را از CoinGecko (رایگان، بدون کلید) دنبال می‌کند.
- تا وقتی پروژه «لیست نشده» باشد هر اسکن دوباره جست‌وجو می‌کند → تشخیص لانچ.
- اگر وب‌سایت/توییتر پروژه داده شده باشد، متن آن را برای کلیدواژه‌های «لانچ/مینت باز» می‌گردد.
- اگر کاربر موقعیت (position) ثبت کرده باشد، سود/زیان (P&L) محاسبه می‌شود.
"""
from __future__ import annotations

import re
import time

import requests

LAUNCH_KEYWORDS = [
    "mint is live", "mint live", "public mint", "mint open", "open for minting",
    "sale is live", "sale live", "on sale now", "claim now", "claim is live",
    "claim open", "claim live", "goes live", "went live", "is live now",
    "live now", "launched", "launch is live", "listing live", "now trading",
    "presale live", "whitelist is live", "minting now",
]

COINGECKO = "https://api.coingecko.com/api/v3"
UA = "CryptoRadarBot/1.0 (personal research bot)"


# ---------------------------------------------------------------- CoinGecko
def _cg_get(path: str, params: dict, timeout: int = 12) -> dict | list | None:
    try:
        r = requests.get(f"{COINGECKO}{path}", params=params, headers={"User-Agent": UA, "accept": "application/json"}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return None


def resolve_asset(name: str) -> dict | None:
    """جست‌وجوی نام در CoinGecko. برمی‌گرداند: {coin_type, id, name, price} یا None."""
    data = _cg_get("/search", {"query": name})
    if not data:
        return None
    coins = data.get("coins") or []
    if coins:
        c = coins[0]
        cid, cname = c.get("id"), c.get("name")
        price = fetch_price("coins", cid)
        return {"coin_type": "coins", "id": cid, "name": cname, "price": price}
    nfts = data.get("nfts") or []
    if nfts:
        n = nfts[0]
        nid, nname = n.get("id"), n.get("name")
        price = fetch_price("nfts", nid)
        return {"coin_type": "nfts", "id": nid, "name": nname, "price": price}
    return None


def fetch_price(coin_type: str, coin_id: str) -> float | None:
    if not coin_id:
        return None
    if coin_type == "nfts":
        data = _cg_get(f"/nfts/{coin_id}", {})
        if data:
            floor = (data.get("floor_price") or {}).get("usd")
            return float(floor) if floor else None
        return None
    data = _cg_get("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
    if data and isinstance(data, dict) and coin_id in data:
        v = data[coin_id].get("usd")
        return float(v) if v is not None else None
    return None


# ---------------------------------------------------------------- تشخیص لانچ
def _text_of(url: str, timeout: int) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code != 200:
            return ""
        return r.text
    except requests.RequestException:
        return ""


def _contains_launch(text: str) -> bool:
    t = re.sub(r"<[^>]+>", " ", (text or "")).lower()
    t = re.sub(r"\s+", " ", t)
    return any(kw in t for kw in LAUNCH_KEYWORDS)


def check_website_launch(url: str, timeout: int = 12) -> bool:
    if not url:
        return False
    return _contains_launch(_text_of(url, timeout))


def check_twitter_launch(instances: list[str], handle: str, timeout: int = 10) -> bool:
    """از طریق RSSHub آخرین توییت‌ها را می‌گردد (به‌صورت تلاش)."""
    import feedparser
    for inst in instances:
        try:
            r = requests.get(f"{inst}/twitter/user/{handle}",
                             headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code != 200:
                continue
            feed = feedparser.parse(r.content)
            texts = [e.get("title", "") for e in feed.entries[:10]]
            if any(_contains_launch(t) for t in texts):
                return True
            return False  # اینستنس جواب داد ولی خبری نبود
        except Exception:
            continue
    return False


# ---------------------------------------------------------------- پیگیری
def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return (a - b) / b * 100.0


def tracker_pass(config, db) -> list[dict]:
    """یک دور پیگیری انجام می‌دهد. خروجی: لیست پیام‌های به‌روزرسانی {chat_id, text}."""
    updates: list[dict] = []
    for row in db.all_tracked():
        tid = row["id"]
        kind = row.get("kind", "token")
        name = row.get("name", f"پروژه #{tid}")
        price = row.get("last_price")
        first_price = row.get("first_price")
        cg_id = row.get("coingecko_id") or ""
        coin_type = row.get("coin_type") or "coins"
        changed: dict = {}
        flags: list[str] = []

        # ۱) اگر هنوز لیست نشده → دوباره جست‌وجو (تشخیص لانچ لیستینگ)
        if kind in ("token", "nft") and not cg_id:
            found = resolve_asset(name.split("(")[0].strip())
            if found and found["price"] is not None:
                cg_id = found["id"]
                coin_type = found["coin_type"]
                price = found["price"]
                changed.update(coingecko_id=cg_id, coin_type=coin_type,
                               listed=1, last_price=price, first_price=price,
                               last_notified_price=price, price_ts=time.time())
                flags.append(f"🚀 <b>{name}</b> لیست شد! اولین قیمت: ${price:,.4f}")
            elif found:
                changed.update(coingecko_id=found["id"], coin_type=found["coin_type"],
                               listed=1)
            else:
                continue  # هنوز خبری نیست؛ صبر

        # ۲) به‌روزرسانی قیمت
        elif cg_id:
            new_price = fetch_price(coin_type, cg_id)
            if new_price is not None:
                price = new_price
                changed.update(last_price=price, price_ts=time.time())
                if first_price is None:
                    changed["first_price"] = price
                    first_price = price

        # ۳) تشخیص لانچ از وب‌سایت/توییتر
        url = row.get("url") or ""
        if not row.get("launch_detected") and url:
            launched = False
            if "twitter.com" in url or "x.com" in url:
                handle = url.rstrip("/").split("/")[-1]
                launched = check_twitter_launch(config.RSSHUB_INSTANCES, handle)
            elif url.startswith("http"):
                launched = check_website_launch(url)
            if launched:
                changed.update(launch_detected=1, launch_at=time.time())
                flags.append(f"🔥 <b>{name}</b>: به‌نظر می‌رسد لانچ شد! (صفحهٔ پروژه را چک کنید)")

        # ۴) ساخت پیام تغییر قیمت
        if price is not None:
            last_notified = row.get("last_notified_price")
            since_first = _pct(price, first_price)
            move = _pct(price, last_notified) if last_notified else None
            if move is not None and abs(move) >= config.TRACK_NOTIFY_PCT:
                changed["last_notified_price"] = price
                flags.append(_price_line(name, price, since_first, move, row))

        if changed:
            db.update_tracked(tid, **changed)
        if flags:
            updates.append({"chat_id": row["chat_id"], "text": "\n\n".join(flags)})
    return updates


def _price_line(name, price, since_first, move, row) -> str:
    parts = [f"📊 <b>{name}</b>: قیمت فعلی <b>${price:,.6f}</b>"]
    if since_first is not None:
        emoji = "🟢" if since_first >= 0 else "🔴"
        parts.append(f"{emoji} از شروع پیگیری: {since_first:+.1f}٪")
    if move is not None:
        parts.append(f"تغییر از آخرین گزارش: {move:+.1f}٪")
    # سود/زیان اگر موقعیت ثبت شده باشد
    qty, cost = row.get("position_qty"), row.get("position_cost")
    if qty and cost is not None:
        pnl = qty * price - cost
        if cost:
            pnl_pct = pnl / cost * 100
            emoji = "💰" if pnl >= 0 else "🩸"
            parts.append(f"{emoji} سود/زیان شما: <b>${pnl:+,.2f}</b> ({pnl_pct:+.1f}٪ از {cost:,.2f}$ سرمایه)")
        else:
            emoji = "🎁" if pnl >= 0 else "🩸"
            parts.append(f"{emoji} سود شما (ایردراپ رایگان): <b>${pnl:+,.2f}</b>")
    return "  •  ".join(parts)


# ---------------------------------------------------------------- نمایش لیست
def tracked_list_lines(row: dict) -> list[str]:
    name = row.get("name", "—")
    kind = row.get("kind", "token")
    price = row.get("last_price")
    first = row.get("first_price")
    lines = []
    if row.get("launch_detected"):
        lines.append(f"🔥 <b>{name}</b> — لانچ‌شده (id={row['id']})")
    elif row.get("listed"):
        lines.append(f"📊 <b>{name}</b> — لیست‌شده (id={row['id']})")
    elif row.get("coingecko_id"):
        lines.append(f"🔍 <b>{name}</b> — در انتظار لانچ لیستینگ (id={row['id']})")
    else:
        lines.append(f"⏳ <b>{name}</b> — در حال رصد (id={row['id']})")
    meta = []
    if kind == "website":
        meta.append("وب‌سایت")
    elif kind == "twitter":
        meta.append("توییتر")
    elif kind == "nft":
        meta.append("NFT")
    if price is not None:
        pct = _pct(price, first) if first else None
        pct_s = f" ({pct:+.1f}٪ از شروع)" if pct is not None else ""
        meta.append(f"قیمت: ${price:,.4f}{pct_s}")
    if row.get("coingecko_id"):
        meta.append(f"CG: {row['coingecko_id']}")
    qty, cost = row.get("position_qty"), row.get("position_cost")
    if qty and cost is not None and price:
        pnl = qty * price - cost
        meta.append(f"سود شما: ${pnl:+,.2f}")
    if row.get("url"):
        meta.append(row["url"])
    if meta:
        lines.append("   " + " | ".join(meta))
    return lines


# ---------------------------------------------------------------- از روی تنظیمات
def ensure_tracked_from_env(config, db) -> None:
    """پروژه‌های پیگیری را از متغیر محیطی TRACK_COINS (با کاما جدا) برای ادمین اضافه می‌کند.

    مفید برای GitHub Actions و حالت‌های بدون ربات تعاملی:
    با این کار می‌توانید بدون دستور /track هم پروژه را زیر نظر بگیرید.
    """
    raw = (config.TRACK_COINS or "").strip()
    if not raw:
        return
    names = [n.strip() for n in raw.split(",") if n.strip()]
    if not names:
        return

    if config.ADMIN_CHAT_ID:
        try:
            chat = int(config.ADMIN_CHAT_ID)
        except ValueError:
            chat = None
    else:
        chat = None
    if chat is None:
        print("⚠️ TRACK_COINS تنظیم شده ولی CHAT_ID معتبر نیست — پیگیری خودکار فعال نشد.")
        return

    existing = {r["name"].strip().lower() for r in db.tracked_for_chat(chat)}
    for name in names:
        if name.lower() in existing:
            continue
        try:
            found = resolve_asset(name)
        except Exception:
            found = None
        if found and found.get("id"):
            tid = db.add_tracked(
                chat, name, "", "nft" if found["coin_type"] == "nfts" else "token",
                coingecko_id=found["id"], coin_type=found["coin_type"],
                price=found.get("price"),
            )
            p = f" (قیمت ${found['price']:,.4f})" if found.get("price") else ""
            print(f"👁 پیگیری خودکار شروع شد: {name} (id={tid}){p}")
        else:
            tid = db.add_tracked(chat, name, "", "token", note="در انتظار لیست")
            print(f"⏳ {name} هنوز در CoinGecko نیست — پیگیری آغاز شد و هر اسکن جست‌وجو می‌شود (id={tid}).")
