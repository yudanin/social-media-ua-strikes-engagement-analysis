#!/usr/bin/env python3
"""Build a SYNTHETIC database to test the pipeline end to end.

  python scripts/fake_data.py --db data/fake.db --effect -30
  python analyze.py --db data/fake.db --out out/fake

--effect P applies a P% stepwise change to treatment accounts (a third at each
strike), so you can check that the analysis recovers it. Every run is marked
SYNTHETIC and the report shows a banner.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.common import Post, connect, day_start, load_config, log_run, save  # noqa: E402

PLATS = {"x": (6, 2000), "telegram": (4, 400), "youtube": (1, 900), "truthsocial": (5, 15000)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="accounts.toml")
    ap.add_argument("--db", default="data/fake.db")
    ap.add_argument("--effect", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    cfg = load_config(a.config)
    start, end = day_start(cfg["window"]["start"]), day_start(cfg["window"]["end"])
    strikes = sorted(day_start(s["date"]) for s in cfg["strikes"])
    scraped = end + dt.timedelta(days=1, hours=1)
    Path(a.db).unlink(missing_ok=True)
    con = connect(a.db)

    for acc in cfg["accounts"]:
        for plat, (rate, scale) in PLATS.items():
            if plat not in ("x", "truthsocial") and plat != "telegram":
                continue
            if not acc.get(plat) and not (plat == "telegram" and acc["key"] in ("afd", "weidel", "cdu", "zelensky")):
                continue
            base = scale * math.exp(rng.gauss(0, 1))
            posts = []
            d = start
            while d <= end:
                for _ in range(max(0, int(rng.gauss(rate, rate / 3)))):
                    t = d + dt.timedelta(seconds=rng.randrange(86400))
                    mult = 1.0
                    if acc["group"] == "treatment":
                        hit = sum(1 for s in strikes if t >= s)
                        mult = 1 + (a.effect / 100) * hit / len(strikes)
                    wk = 0.85 if t.weekday() >= 5 else 1.0
                    likes = int(base * mult * wk * math.exp(rng.gauss(0, 0.6)))
                    pid = f"fake-{plat}-{acc['key']}-{len(posts)}"
                    posts.append(Post(
                        platform=plat, post_id=pid, account=acc["key"], created_at=t,
                        kind="reply" if plat == "x" and rng.random() < 0.3 else "post",
                        likes=likes, reposts=likes // 8, replies=likes // 15,
                        quotes=likes // 40, views=likes * 40 if plat != "truthsocial" else None,
                    ))
                d += dt.timedelta(days=1)
            save(con, posts, scraped)
            log_run(con, scraped, plat, acc["key"], acc.get(plat) or "fake", len(posts),
                    f"SYNTHETIC effect={a.effect}")
    print(f"synthetic database written to {a.db}")


if __name__ == "__main__":
    main()
