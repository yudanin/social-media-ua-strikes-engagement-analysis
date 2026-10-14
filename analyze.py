#!/usr/bin/env python3
"""Turn data/engagement.db into out/dashboard.json and out/report.html.

Method (defaults; all switchable):
  * Unit of analysis = one account on one platform.
  * Each post's counts come from its latest snapshot, and only if the post was
    at least --min-age-hours old at that snapshot (incomplete counts otherwise).
    With --at-age H, the earliest snapshot taken at age >= H is used instead.
  * Replies are dropped unless --include-replies (they have very different
    engagement from top-level posts and Musk posts thousands of them).
  * Daily value = median per-post metric that day (UTC). Baseline = median of
    daily values from window start to baseline_end (>= 5 days required).
  * Index = 100 * daily / baseline.
  * Unit effect = mean log(index) after S1 minus mean log(index) before S1.
    Group effect = mean of unit effects; difference-in-differences = treatment
    minus control. Reported as % change (exp(x) - 1). 95% CI by bootstrapping
    units within each group.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

from collectors.common import connect, day_start, iso, load_config, now, parse_iso

METRICS = ["likes", "views", "replies", "reposts"]
PLATFORMS = ["x", "telegram", "youtube", "truthsocial"]
PLATFORM_LABEL = {"all": "All", "x": "X", "telegram": "Telegram",
                  "youtube": "YouTube", "truthsocial": "Truth Social"}
METRIC_LABEL = {"likes": "Likes / reactions", "views": "Views",
                "replies": "Replies / comments", "reposts": "Reposts / forwards"}
MIN_BASELINE_DAYS = 5


def pick_snapshots(con, min_age_h: float, at_age_h: float | None, include_replies: bool):
    """Return list of dicts: one per usable post, plus counts of exclusions."""
    rows = con.execute("""
        SELECT p.platform, p.post_id, p.account, p.created_at, p.kind,
               s.scraped_at, s.likes, s.views, s.replies, s.reposts
        FROM posts p JOIN snapshots s USING (platform, post_id)
        ORDER BY p.platform, p.post_id, s.scraped_at""").fetchall()
    by_post = defaultdict(list)
    for r in rows:
        by_post[(r[0], r[1])].append(r)

    used, too_young, replies_dropped = [], defaultdict(int), defaultdict(int)
    for (plat, _), snaps in by_post.items():
        created = parse_iso(snaps[0][3])
        kind = snaps[0][4]
        if kind == "reply" and not include_replies:
            replies_dropped[plat] += 1
            continue
        aged = [(parse_iso(s[5]) - created).total_seconds() / 3600 for s in snaps]
        chosen = None
        if at_age_h is not None:
            for s, a in zip(snaps, aged):
                if a >= at_age_h:
                    chosen = (s, a)
                    break
        elif aged[-1] >= min_age_h:
            chosen = (snaps[-1], aged[-1])
        if not chosen:
            too_young[plat] += 1
            continue
        s, age = chosen
        used.append({
            "platform": plat, "account": s[2], "created": created, "age_h": age,
            "scraped_at": s[5],
            "likes": s[6], "views": s[7], "replies": s[8], "reposts": s[9],
        })
    return used, too_young, replies_dropped


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct(x):
    return None if x is None else round((math.exp(x) - 1) * 100, 2)


def bootstrap_did(t_eff, c_eff, n=2000, seed=7):
    if len(t_eff) < 2 or len(c_eff) < 2:
        return None, None
    rng = random.Random(seed)
    draws = []
    for _ in range(n):
        t = [rng.choice(t_eff) for _ in t_eff]
        c = [rng.choice(c_eff) for _ in c_eff]
        draws.append(sum(t) / len(t) - sum(c) / len(c))
    draws.sort()
    return draws[int(0.025 * n)], draws[int(0.975 * n) - 1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="accounts.toml")
    ap.add_argument("--db", default="data/engagement.db")
    ap.add_argument("--out", default="out")
    ap.add_argument("--min-age-hours", type=float, default=48)
    ap.add_argument("--at-age", type=float, default=None,
                    help="read counts at this post age (needs forward polling snapshots)")
    ap.add_argument("--include-replies", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    w = cfg["window"]
    start, end, base_end = day_start(w["start"]), day_start(w["end"]), day_start(w["baseline_end"])
    dates = []
    d = start
    while d <= end:
        dates.append(d.date().isoformat())
        d += dt.timedelta(days=1)
    di = {x: i for i, x in enumerate(dates)}
    n_base = di[base_end.date().isoformat()] + 1
    strikes = sorted(cfg["strikes"], key=lambda s: s["date"])
    for s in strikes:
        s["i"] = di.get(s["date"])
    s1 = strikes[0]["i"]
    seg_bounds = [("Baseline", 0, s1)]
    for k, s in enumerate(strikes):
        stop = strikes[k + 1]["i"] if k + 1 < len(strikes) else len(dates)
        nxt = strikes[k + 1]["label"] if k + 1 < len(strikes) else "end"
        seg_bounds.append((f"{s['label']} → {nxt}", s["i"], stop))

    accounts = {a["key"]: a for a in cfg["accounts"]}
    con = connect(args.db)
    used, too_young, replies_dropped = pick_snapshots(
        con, args.min_age_hours, args.at_age, args.include_replies)
    synthetic = con.execute("SELECT COUNT(*) FROM runs WHERE note LIKE 'SYNTHETIC%'").fetchone()[0] > 0
    last_run = dict(con.execute("SELECT platform, MAX(started_at) FROM runs GROUP BY platform").fetchall())

    # posts per unit per day
    per_day = defaultdict(lambda: defaultdict(list))   # (acct, plat) -> day -> [post]
    for p in used:
        day = p["created"].date().isoformat()
        if day in di and p["account"] in accounts:
            per_day[(p["account"], p["platform"])][day].append(p)

    units = []
    for (acct, plat), days in sorted(per_day.items()):
        a = accounts[acct]
        u = {"account": acct, "name": a["name"], "group": a["group"], "platform": plat,
             "posts": sum(len(v) for v in days.values()), "baseline": {}, "idx": {},
             "effect": {}, "delta": {}, "segments": {}}
        for m in METRICS:
            daily = [None] * len(dates)
            for day, posts in days.items():
                vals = [p[m] for p in posts if p[m] is not None]
                if vals:
                    daily[di[day]] = st.median(vals)
            base_vals = [v for v in daily[:n_base] if v is not None]
            if len(base_vals) < MIN_BASELINE_DAYS:
                continue
            b = st.median(base_vals)
            if not b or b <= 0:
                continue
            idx = [None if v is None else round(100 * v / b, 2) for v in daily]
            logs = [None if v is None else math.log(max(v, 1) / 100) for v in idx]
            pre, post = mean(logs[:s1]), mean(logs[s1:])
            if pre is None or post is None:
                continue
            u["baseline"][m] = b
            u["idx"][m] = idx
            u["effect"][m] = post - pre
            u["delta"][m] = pct(post - pre)
            u["segments"][m] = [mean(logs[a0:a1]) for _, a0, a1 in seg_bounds]
        if u["idx"]:
            units.append(u)

    views = {}
    for plat in ["all"] + PLATFORMS:
        for m in METRICS:
            us = [u for u in units if m in u["idx"] and (plat == "all" or u["platform"] == plat)]
            if not us:
                continue
            T = [u for u in us if u["group"] == "treatment"]
            C = [u for u in us if u["group"] == "control"]

            def series(group):
                out, n = [], []
                for i in range(len(dates)):
                    vals = [u["idx"][m][i] for u in group if u["idx"][m][i] is not None]
                    out.append(round(st.median(vals), 2) if vals else None)
                    n.append(len(vals))
                return out, n

            t_s, t_n = series(T)
            c_s, c_n = series(C)
            t_eff = [u["effect"][m] for u in T]
            c_eff = [u["effect"][m] for u in C]
            t_mean, c_mean = mean(t_eff), mean(c_eff)
            did = None if t_mean is None or c_mean is None else t_mean - c_mean
            lo, hi = bootstrap_did(t_eff, c_eff)
            segs = []
            for k, (label, _, _) in enumerate(seg_bounds):
                segs.append({
                    "label": label,
                    "treat": pct(mean([u["segments"][m][k] for u in T])),
                    "ctrl": pct(mean([u["segments"][m][k] for u in C])),
                })
            views[f"{plat}|{m}"] = {
                "treat": t_s, "ctrl": c_s, "nT": t_n, "nC": c_n,
                "tiles": {"treat": pct(t_mean), "ctrl": pct(c_mean), "did": pct(did),
                          "ci_lo": pct(lo), "ci_hi": pct(hi),
                          "unitsT": len(T), "unitsC": len(C),
                          "posts": sum(u["posts"] for u in us)},
                "segments": segs,
            }

    coverage = []
    for plat in PLATFORMS:
        configured = [a for a in cfg["accounts"] if a.get(plat)]
        if not configured:
            continue
        pu = [u for u in units if u["platform"] == plat]
        coverage.append({
            "platform": PLATFORM_LABEL[plat], "key": plat,
            "configured": len(configured), "with_data": len(pu),
            "posts": sum(u["posts"] for u in pu),
            "too_young": too_young.get(plat, 0),
            "replies_dropped": replies_dropped.get(plat, 0),
            "last_run": last_run.get(plat),
        })

    for u in units:
        u.pop("effect")
        u.pop("segments")

    payload = {
        "meta": {
            "start": w["start"], "end": w["end"], "baseline_end": w["baseline_end"],
            "dates": dates, "strikes": strikes, "generated_at": iso(now()),
            "synthetic": synthetic,
            "settings": {"min_age_hours": args.min_age_hours, "at_age": args.at_age,
                         "include_replies": args.include_replies},
            "platform_labels": PLATFORM_LABEL, "metric_labels": METRIC_LABEL,
        },
        "views": views, "units": units, "coverage": coverage,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.json").write_text(json.dumps(payload, indent=1))
    template = (Path(__file__).parent / "report_template.html").read_text()
    blob = json.dumps(payload).replace("</", "<\\/")
    (out / "report.html").write_text(template.replace("/*__DATA__*/null", blob))

    k = views.get("all|likes", {}).get("tiles", {})
    print(f"{len(used)} posts usable, {len(units)} account×platform units")
    print(f"likes, all platforms: treatment {k.get('treat')}%, control {k.get('ctrl')}%, "
          f"DiD {k.get('did')}% [{k.get('ci_lo')}, {k.get('ci_hi')}]")
    print(f"wrote {out/'dashboard.json'} and {out/'report.html'}")


if __name__ == "__main__":
    main()
