"""Shared storage, config and time helpers for all collectors.

Storage model: one row per post (`posts`) plus one row per time we looked at
its counts (`snapshots`). Repeated runs never overwrite counts; they add a
snapshot, so engagement can later be read at a fixed post age.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

UTC = dt.timezone.utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    platform   TEXT NOT NULL,
    post_id    TEXT NOT NULL,
    account    TEXT NOT NULL,          -- account key from accounts.toml
    created_at TEXT NOT NULL,          -- ISO 8601 UTC
    kind       TEXT NOT NULL,          -- post | reply | quote | video
    url        TEXT,
    text       TEXT,
    PRIMARY KEY (platform, post_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
    platform   TEXT NOT NULL,
    post_id    TEXT NOT NULL,
    scraped_at TEXT NOT NULL,          -- ISO 8601 UTC
    likes      INTEGER,                -- X likes, TG reactions, YT likes, TS favourites
    reposts    INTEGER,                -- X retweets, TG forwards, TS reblogs
    replies    INTEGER,                -- X replies, TG comments, YT comments, TS replies
    quotes     INTEGER,                -- X quotes
    views      INTEGER,                -- X impressions, TG views, YT views
    PRIMARY KEY (platform, post_id, scraped_at)
);
CREATE TABLE IF NOT EXISTS runs (
    started_at TEXT, platform TEXT, account TEXT, handle TEXT,
    posts INTEGER, note TEXT
);
"""


@dataclass
class Post:
    platform: str
    post_id: str
    account: str
    created_at: dt.datetime
    kind: str
    url: str | None = None
    text: str | None = None
    likes: int | None = None
    reposts: int | None = None
    replies: int | None = None
    quotes: int | None = None
    views: int | None = None


def now() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def day_start(d: str) -> dt.datetime:
    return dt.datetime.fromisoformat(d).replace(tzinfo=UTC)


def load_config(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_env(path: str | Path = ".env") -> None:
    """Minimal .env reader so there is no python-dotenv dependency."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    return con


def save(con: sqlite3.Connection, posts: list[Post], scraped_at: dt.datetime) -> None:
    ts = iso(scraped_at)
    con.executemany(
        "INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?)",
        [(p.platform, p.post_id, p.account, iso(p.created_at), p.kind, p.url,
          (p.text or "")[:500]) for p in posts],
    )
    con.executemany(
        "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
        [(p.platform, p.post_id, ts, p.likes, p.reposts, p.replies, p.quotes, p.views)
         for p in posts],
    )
    con.commit()


def log_run(con, started, platform, account, handle, n, note=""):
    con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                (iso(started), platform, account, handle, n, note))
    con.commit()
