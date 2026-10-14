# Strike engagement study

Did engagement on AfD, Trump, Musk, Reform UK and similar accounts change after
Ukraine's 7–11 Oct 2026 strikes on Yandex datacentres, relative to control
accounts? This repo collects posts and engagement counts, then builds a
self-contained dashboard (`out/report.html`).

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate     # Python 3.11+
pip install -r requirements.txt
cp .env.example .env                               # fill in the keys you have
```

Then open `accounts.toml`: X handles are filled in; Telegram channels and
YouTube handles are blank (verify them before collecting). Empty = skipped.

## Collect

```bash
python collect.py --platform x            # ~$0.005 per post read; prints spend
python collect.py --platform telegram     # asks for phone + code on first run
python collect.py --platform youtube
python collect.py --platform truthsocial
```

**Run X first, today.** The timeline endpoint only reaches back ~3,200 posts,
and Musk's volume may push 15 Sep out of reach within days. The collector
warns if it hit the cap.

Everything lands in `data/engagement.db`. Each run adds a new snapshot of
counts; nothing is overwritten.

### Forward polling (recommended from now on)

Counts scraped after the fact are cumulative. To read engagement at a fixed
post age for new posts, poll every 6 hours:

```cron
0 */6 * * * cd /path/to/strike-engagement && .venv/bin/python collect.py --since-hours 96
```

Then `python analyze.py --at-age 24` reads each post's counts at ≥ 24h.

## Analyse

```bash
python analyze.py                     # → out/dashboard.json, out/report.html
python analyze.py --include-replies   # keep replies (off by default)
```

Open `out/report.html` in a browser; no server needed.

Method: unit = one account on one platform; daily value = median per-post
metric; index = daily ÷ baseline median × 100; change = geometric mean after
S1 vs. before; difference-in-differences with a bootstrap CI over units. The
"step pattern" table splits the post period at each strike.

## Test without real data

```bash
python scripts/fake_data.py --db data/fake.db --effect -30
python analyze.py --db data/fake.db --out out/fake
```

The report shows a "Synthetic data" banner.

## Limits worth knowing before reading any result

- With ~5 control units the bootstrap CI is too optimistic: on null synthetic
  data it excluded zero in 1 of 7 seeds. Add controls before trusting a CI.
- Posts from ~5–7 Oct have engagement windows that straddle the strikes.
- A drop alone says nothing about bots. The "who engages" analysis (account
  age of engagers) needs per-post liker reads on X and is not built yet.
