"""YouTube collector — Data API v3 with an API key (YT_API_KEY).

Resolves the channel by handle, walks its uploads playlist newest-first until
the window start, then fetches statistics in batches of 50. A full run for a
dozen channels costs a few hundred quota units of the 10,000/day default.
"""
from __future__ import annotations

import os

import requests

from .common import Post, parse_iso

API = "https://www.googleapis.com/youtube/v3"


def _get(path: str, **params) -> dict:
    params["key"] = os.environ["YT_API_KEY"]
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube API {r.status_code}: {r.text[:300]}")
    return r.json()


def collect(account: str, handle: str, start, end) -> list[Post]:
    if not os.environ.get("YT_API_KEY"):
        raise SystemExit("YT_API_KEY is not set (see .env.example)")
    handle = handle if handle.startswith("@") else "@" + handle
    ch = _get("channels", part="contentDetails", forHandle=handle)
    if not ch.get("items"):
        raise RuntimeError(f"no YouTube channel for {handle}")
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    vids: dict[str, object] = {}
    token = None
    done = False
    while not done:
        page = _get("playlistItems", part="contentDetails", playlistId=uploads,
                    maxResults=50, **({"pageToken": token} if token else {}))
        for it in page.get("items", []):
            published = parse_iso(it["contentDetails"]["videoPublishedAt"])
            if published < start:
                done = True
                break
            if published <= end:
                vids[it["contentDetails"]["videoId"]] = published
        token = page.get("nextPageToken")
        if not token:
            break

    out: list[Post] = []
    ids = list(vids)
    for i in range(0, len(ids), 50):
        stats = _get("videos", part="statistics", id=",".join(ids[i:i + 50]))
        for v in stats.get("items", []):
            s = v.get("statistics", {})
            out.append(Post(
                platform="youtube", post_id=v["id"], account=account,
                created_at=vids[v["id"]], kind="video",
                url=f"https://www.youtube.com/watch?v={v['id']}",
                likes=_int(s.get("likeCount")), replies=_int(s.get("commentCount")),
                views=_int(s.get("viewCount")),
            ))
    return out


def _int(x):
    return int(x) if x is not None else None
