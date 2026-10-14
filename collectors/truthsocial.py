"""Truth Social collector — via truthbrush (Stanford Internet Observatory).

Needs TRUTHSOCIAL_USERNAME and TRUTHSOCIAL_PASSWORD for a regular account.
truthbrush talks to Truth Social's Mastodon-style API; if it breaks after a
site change, check its GitHub issues first.
"""
from __future__ import annotations

import os
import re

from .common import Post, parse_iso


def collect(account: str, handle: str, start, end) -> list[Post]:
    from truthbrush.api import Api  # imported lazily

    if not os.environ.get("TRUTHSOCIAL_USERNAME"):
        raise SystemExit("TRUTHSOCIAL_USERNAME / TRUTHSOCIAL_PASSWORD are not set")
    api = Api()
    out: list[Post] = []
    for st in api.pull_statuses(handle, replies=False, created_after=start):
        created = parse_iso(st["created_at"])
        if created < start or created > end:
            continue
        if st.get("reblog"):           # a ReTruth: counts belong to the original
            continue
        out.append(Post(
            platform="truthsocial", post_id=str(st["id"]), account=account,
            created_at=created, kind="reply" if st.get("in_reply_to_id") else "post",
            url=st.get("url"), text=re.sub(r"<[^>]+>", " ", st.get("content") or ""),
            likes=st.get("favourites_count"), reposts=st.get("reblogs_count"),
            replies=st.get("replies_count"),
        ))
    return out
