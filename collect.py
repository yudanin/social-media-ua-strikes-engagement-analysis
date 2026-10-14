#!/usr/bin/env python3
"""Collect posts and engagement counts into data/engagement.db.

Examples
  python collect.py --platform x                       # full study window
  python collect.py --platform telegram --account afd  # one account
  python collect.py --platform all --since-hours 96    # forward polling (run every 6h)

Every run adds a snapshot of counts with its own timestamp; nothing is
overwritten, so repeated runs let analysis read engagement at a fixed post age.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from collectors.common import connect, day_start, load_config, load_env, log_run, now, save

PLATFORMS = ["x", "telegram", "youtube", "truthsocial"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", choices=PLATFORMS + ["all"], default="all")
    ap.add_argument("--account", action="append", help="account key(s) from accounts.toml")
    ap.add_argument("--config", default="accounts.toml")
    ap.add_argument("--db", default="data/engagement.db")
    ap.add_argument("--since-hours", type=float,
                    help="collect posts from the last N hours instead of the study window")
    args = ap.parse_args()

    load_env()
    cfg = load_config(args.config)
    started = now()
    if args.since_hours:
        start, end = started - dt.timedelta(hours=args.since_hours), started
    else:
        start = day_start(cfg["window"]["start"])
        end = min(day_start(cfg["window"]["end"]) + dt.timedelta(days=1), started)

    platforms = PLATFORMS if args.platform == "all" else [args.platform]
    accounts = [a for a in cfg["accounts"] if not args.account or a["key"] in args.account]
    con = connect(args.db)
    xclient = None
    failures = 0

    for plat in platforms:
        for acc in accounts:
            handle = acc.get(plat, "")
            if not handle:
                continue
            print(f"[{plat}] {acc['name']} ({handle}) {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC")
            note = ""
            try:
                if plat == "x":
                    from collectors.x import XClient
                    xclient = xclient or XClient()
                    posts, note = xclient.timeline(acc["key"], handle, start, end)
                elif plat == "telegram":
                    from collectors import telegram
                    posts = telegram.collect(acc["key"], handle, start, end)
                elif plat == "youtube":
                    from collectors import youtube
                    posts = youtube.collect(acc["key"], handle, start, end)
                else:
                    from collectors import truthsocial
                    posts = truthsocial.collect(acc["key"], handle, start, end)
            except SystemExit:
                raise
            except Exception as e:  # keep going with the other accounts
                failures += 1
                print(f"    FAILED: {e}")
                log_run(con, started, plat, acc["key"], handle, 0, f"error: {e}")
                continue
            save(con, posts, now())
            log_run(con, started, plat, acc["key"], handle, len(posts), note)
            print(f"    {len(posts)} posts saved")

    con.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
