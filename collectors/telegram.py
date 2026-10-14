"""Telegram collector — Telethon, your own user account.

Needs TG_API_ID and TG_API_HASH from https://my.telegram.org. The first run
asks for your phone number and a login code, then keeps a local session file.

Per message: views, forwards, comment count (if the channel has a discussion
group) and total reactions. Album parts share a grouped_id; only the first part
is kept so one album counts as one post.
"""
from __future__ import annotations

import os

from .common import UTC, Post


def collect(account: str, channel: str, start, end, session: str = "data/tg") -> list[Post]:
    from telethon.sync import TelegramClient  # imported lazily

    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("TG_API_ID / TG_API_HASH are not set (see .env.example)")

    out: list[Post] = []
    seen_groups: set[int] = set()
    with TelegramClient(session, int(api_id), api_hash) as client:
        # iter_messages walks newest -> oldest, starting before offset_date
        for m in client.iter_messages(channel, offset_date=end):
            created = m.date.astimezone(UTC)
            if created < start:
                break
            if m.grouped_id:
                if m.grouped_id in seen_groups:
                    continue
                seen_groups.add(m.grouped_id)
            reactions = None
            if m.reactions and m.reactions.results:
                reactions = sum(r.count for r in m.reactions.results)
            out.append(Post(
                platform="telegram", post_id=str(m.id), account=account,
                created_at=created, kind="post",
                url=f"https://t.me/{channel}/{m.id}", text=m.message,
                likes=reactions, reposts=m.forwards,
                replies=m.replies.replies if m.replies else None,
                views=m.views,
            ))
    return out
