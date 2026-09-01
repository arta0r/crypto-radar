"""دیتابیس SQLite: پروژه‌های دیده‌شده، چت‌های ثبت‌نام‌شده، فیدهای دلخواه، تنظیمات."""
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_projects (
    key TEXT PRIMARY KEY,
    name TEXT,
    url TEXT,
    source TEXT,
    score INTEGER,
    first_seen REAL,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS chat_ids (
    chat_id INTEGER PRIMARY KEY,
    registered_at REAL
);
CREATE TABLE IF NOT EXISTS watched_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    kind TEXT,
    url TEXT,
    label TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS scan_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    candidates INTEGER,
    projects INTEGER,
    duration_sec REAL
);
CREATE TABLE IF NOT EXISTS tracked_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    name TEXT,
    url TEXT,
    kind TEXT DEFAULT 'token',        -- token / nft / website / twitter
    coingecko_id TEXT,
    coin_type TEXT,                   -- 'coins' یا 'nfts'
    launch_detected INTEGER DEFAULT 0,
    launch_at REAL,
    listed INTEGER DEFAULT 0,         -- آیا توکن/کالکشن در کوین‌گکو لیست شده؟
    last_price REAL,
    first_price REAL,
    last_notified_price REAL,
    price_ts REAL,
    position_qty REAL,
    position_cost REAL,
    note TEXT,
    created_at REAL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with _lock, self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    # ---------- seen projects ----------
    def mark_seen(self, key: str, name: str, url: str, source: str, score: int):
        now = time.time()
        with _lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO seen_projects(key, name, url, source, score, first_seen, last_seen)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     name=excluded.name, url=excluded.url, source=excluded.source,
                     score=excluded.score, last_seen=excluded.last_seen""",
                (key, name, url, source, score, now, now),
            )
            conn.commit()

    def is_seen_recent(self, key: str, lookback_days: int) -> bool:
        cutoff = time.time() - lookback_days * 86400
        with _lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_projects WHERE key=? AND last_seen>=?", (key, cutoff)
            ).fetchone()
            return row is not None

    # ---------- chats ----------
    def add_chat(self, chat_id: int):
        with _lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO chat_ids(chat_id, registered_at) VALUES(?,?)",
                (chat_id, time.time()),
            )
            conn.commit()

    def remove_chat(self, chat_id: int):
        with _lock, self._connect() as conn:
            conn.execute("DELETE FROM chat_ids WHERE chat_id=?", (chat_id,))
            conn.commit()

    def all_chats(self) -> list[int]:
        with _lock, self._connect() as conn:
            rows = conn.execute("SELECT chat_id FROM chat_ids").fetchall()
            return [r["chat_id"] for r in rows]

    # ---------- watched feeds ----------
    def add_feed(self, chat_id: int, kind: str, url: str, label: str) -> int:
        with _lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO watched_feeds(chat_id, kind, url, label, created_at) VALUES(?,?,?,?,?)",
                (chat_id, kind, url, label, time.time()),
            )
            conn.commit()
            return cur.lastrowid

    def all_feeds(self) -> list[dict]:
        with _lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM watched_feeds ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def remove_feed(self, feed_id: int):
        with _lock, self._connect() as conn:
            conn.execute("DELETE FROM watched_feeds WHERE id=?", (feed_id,))
            conn.commit()

    # ---------- settings ----------
    def get_setting(self, key: str, default: str = "") -> str:
        with _lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with _lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()

    # ---------- scan stats ----------
    def add_scan_stats(self, candidates: int, projects: int, duration_sec: float):
        with _lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO scan_stats(ts, candidates, projects, duration_sec) VALUES(?,?,?,?)",
                (time.time(), candidates, projects, duration_sec),
            )
            conn.commit()

    def last_scan_stats(self) -> dict | None:
        with _lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scan_stats ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    # ---------- tracked projects (پیگیری پروژه) ----------
    def add_tracked(self, chat_id: int, name: str, url: str, kind: str,
                    coingecko_id: str = "", coin_type: str = "",
                    note: str = "", price: float = None) -> int:
        now = time.time()
        with _lock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO tracked_projects(chat_id, name, url, kind, coingecko_id, coin_type,
                   last_price, first_price, last_notified_price, price_ts, note, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (chat_id, name, url, kind, coingecko_id, coin_type,
                 price, price, price, now if price else None, note, now),
            )
            conn.commit()
            return cur.lastrowid

    def tracked_for_chat(self, chat_id: int) -> list[dict]:
        with _lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tracked_projects WHERE chat_id=? ORDER BY id", (chat_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def all_tracked(self) -> list[dict]:
        with _lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM tracked_projects ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_tracked(self, track_id: int) -> dict | None:
        with _lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tracked_projects WHERE id=?", (track_id,)
            ).fetchone()
            return dict(row) if row else None

    def remove_tracked(self, track_id: int):
        with _lock, self._connect() as conn:
            conn.execute("DELETE FROM tracked_projects WHERE id=?", (track_id,))
            conn.commit()

    def update_tracked(self, track_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with _lock, self._connect() as conn:
            conn.execute(
                f"UPDATE tracked_projects SET {cols} WHERE id=?",
                (*fields.values(), track_id),
            )
            conn.commit()
