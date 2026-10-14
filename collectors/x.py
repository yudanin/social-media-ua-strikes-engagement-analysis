"""X collector — official API v2, pay-per-use.

Needs X_BEARER_TOKEN. Reads each account's own timeline between start and end
with public_metrics. Retweets are always excluded (their counts belong to the
original post); replies are included and tagged kind="reply" so analysis can
keep or drop them.

Cost: X bills per post returned (~$0.005 each as of 2026). The script prints a
running estimate. The user-timeline endpoint only reaches back ~3,200 posts per
account; a warning is printed if the window start was not reached.
"""
from __future__ import annotations

import os
import time

import requests

from .common import Post, iso, parse_iso

API = "https://api.x.com/2"
PRICE_PER_POST = 0.005


class XClient:
    def __init__(self, token: str | None = None):
        token = token or os.environ.get("X_BEARER_TOKEN")
        if not token:
            raise SystemExit("X_BEARER_TOKEN is not set (see .env.example)")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.posts_read = 0

    def _get(self, path: str, params: dict | None = None) -> dict:
        while True:
            r = self.s.get(API + path, params=params, timeout=30)
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
                wait = max(5, reset - int(time.time()) + 2)
                print(f"    rate limited; sleeping {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"X API {r.status_code}: {r.text[:300]}")
            return r.json()

    def user_id(self, handle: str) -> str:
        return self._get(f"/users/by/username/{handle}")["data"]["id"]

    def timeline(self, account: str, handle: str, start, end) -> tuple[list[Post], str]:
        uid = self.user_id(handle)
        params = {
            "start_time": iso(start),
            "end_time": iso(end),
            "max_results": 100,
            "exclude": "retweets",
            "tweet.fields": "created_at,public_metrics,referenced_tweets",
        }
        out: list[Post] = []
        while True:
            data = self._get(f"/users/{uid}/tweets", params)
            for t in data.get("data", []):
                refs = {r["type"] for r in t.get("referenced_tweets", [])}
                kind = "reply" if "replied_to" in refs else "quote" if "quoted" in refs else "post"
                m = t.get("public_metrics", {})
                out.append(Post(
                    platform="x", post_id=t["id"], account=account,
                    created_at=parse_iso(t["created_at"]), kind=kind,
                    url=f"https://x.com/{handle}/status/{t['id']}", text=t.get("text"),
                    likes=m.get("like_count"), reposts=m.get("retweet_count"),
                    replies=m.get("reply_count"), quotes=m.get("quote_count"),
                    views=m.get("impression_count"),
                ))
            self.posts_read += len(data.get("data", []))
            nxt = data.get("meta", {}).get("next_token")
            if not nxt:
                break
            params["pagination_token"] = nxt
        note = ""
        if len(out) >= 3000:
            oldest = min(p.created_at for p in out)
            if (oldest - start).total_seconds() > 86400:
                note = f"WARNING: timeline cap likely hit; oldest post is {iso(oldest)}"
                print("    " + note)
        print(f"    ~${self.posts_read * PRICE_PER_POST:.2f} spent so far on X reads")
        return out, note
