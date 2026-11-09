# AI Trading System

A **local, file-based trading system** built step-by-step with Claude — no cloud, no server, and (for the first several hours of the course) no coding. This repo builds out the system the AI Pathways master course describes, one Claude prompt at a time.

> 🎥 **Video reference:** [How To Actually Build an AI Trading Bot With Claude (3 Hour Course) — AI Pathways](https://www.youtube.com/watch?v=gJLKVsIqiTE)
> 📜 Full transcript: [`docs/transcript.txt`](docs/transcript.txt) · 📚 **Framework deep-dive:** [`docs/alpha-framework.md`](docs/alpha-framework.md)

**Not financial advice** — it's the operational path to a working, maintainable bot. The bot studies how each asset moves, tests strategies that fit it with rigorous out-of-sample gates, and then runs on its own every trading day on a broker paper account, messaging your phone via Telegram after each run.

## The framework: **ALPHA**

The course is organized as the acronym **ALPHA**. We build in this order, testing each stage before the next.

| Letter | Stage | What we do |
|---|---|---|
| **A** | **Architecture** | Environment, model choice, prompt vs *skill* vs *schedule*, project layout, house rules, core/sleeve account design |
| **L** | **Logic** | Pick time frame, assets; study how they move; build **regimes**; match a strategy to each asset; write **exact, testable rules** |
| **P** | **Proof** | Validate the back tester on known data → search a **core** holding → run **sleeve** ideas through the funnel → build the combined account |
| **H** | **Harness** | Build the live bot (Alpaca) on your own computer; evening + morning runs; Telegram alerts; safety checks & risk limits |
| **A** | **Adapt** | Compare paper↔back test, keep a sleeve "bench", put Claude reviews on a schedule, **and keep iterating** on top |

Full detail, the core-vs-sleeve design, the funnel, the 10 most common mistakes, and the broker comparison live in [`docs/alpha-framework.md`](docs/alpha-framework.md).

## Status

| ALPHA stage | Status |
|---|---|
| **A** — Architecture (project, house rules, dashboard shell) | ✅ done — this is "prompt 0" |
| **L** — Logic (asset study, regimes, exact sleeve rules) | ⏳ next |
| **P** — Proof (validated back tester, core search, sleeve funnel, account) | ⏳ |
| **H** — Harness (Alpaca live bot, Telegram, risk limits) | ⏳ |
| **A** — Adapt (paper↔backtest, bench, scheduled reviews, iteration) | ⏳ |

## House rules (the single source of truth)

All settings live in one place — [`CLAUDE.md`](CLAUDE.md), mirrored to [`AGENTS.md`](AGENTS.md) so the project also works in ChatGPT's Codex. Every prompt/script reads from there. This is the course's "My settings" block:

- **Bar size:** daily (a "day" = one bar)
- **Data:** 2020-07-01 → 2026-10-23 · `yfinance` · split- & dividend-adjusted · frozen in `data/prices.parquet`
- **Training window:** 2022-01-03 → 2024-12-31
- **Locked test window:** 2025-01-02 → 2026-10-23 — **runs once**, only after the choice is made; never re-tuned on its results
- **Engine candidates:** SPY QQQ IWM DIA · **Safe candidates:** SGOV SHY IEF TLT GLD · **Cash:** SGOV · **Market:** SPY
- **Studied, never traded:** BTC-USD
- **Cost:** 0.05% of traded value per buy and per sell · **Starting money:** $100,000

## The funnel (how a sleeve earns its place)

| # | Gate | Question |
|---|---|---|
| 0 | Ideas | exact, testable rules defined in the prompt |
| 1 | Fit the asset | does it fit the ticker it's on? |
| 2 | Training | makes money **after costs** on the training window? |
| 3 | Enough trades | statistically meaningful count? (dip-buy ≥ 15 · breakout ≥ 6) |
| 4 | Profit factor | winners out-earn losers by **≥ 1.3×**? |
| 5 | **Neighbors** | do *nearby parameter values* also profit (a hill, not a lucky spike)? |
| 6 | **Locked test** | still works on data it never saw (2025 → present)? (**runs once**) |

In the course's run, **44 ideas → 7 survivors** (QQQ dip-buy, QQQ breakout, XLK dip-buy, XLK breakout, XLF breakout, XLY dip-buy, GLD dip-buy).

## Core vs. Sleeve (the account)

- **Core (~70%):** the main holding — "better than cash," long horizon, barely trades. Course example: a **QQQ ↔ gold** rotation driven by regime.
- **Sleeve (~30%):** short-term setups (dip-buy, breakout, …) that **rotate** to beat strategy decay as regimes shift.

**Regime** is a layer every strategy reads — *uptrend/downtrend* + *calm/volatile* — and it drives **position sizing: full size on calm days, half size on volatile days.**

## Project layout

```
├── CLAUDE.md, AGENTS.md    House rules — settings, data, windows, backtest conventions (the "A")
├── .env.example            Environment template (broker keys land in the "H")
├── requirements.txt        Python dependencies
├── data/                   prices.parquet (research, frozen) · live_prices.parquet (live bot only)
├── src/                    bot, morning check, ticker script, core/sleeve code (grows stage by stage)
├── config/                 Named strategy & run configurations
├── results/                Machine-readable backtest output (the "P")
├── reports/                Human-readable strategy reports
├── logs/                   Run logs + state.json (what the bot thinks it owns)
├── calls/
│   ├── fed/                Scheduled Fed-day AI check (the "H")
│   └── practice/           Paper / practice trade log (the "A")
├── dashboard/              Built, self-contained HTML dashboard  (dashboard/build.py)
└── docs/
    ├── alpha-framework.md  The course framework, distilled (read this first)
    ├── transcript.txt      Full video transcript (reference)
    ├── prompt-0-architecture.md
    └── images/
```

## Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Dashboard (single self-contained HTML file — opens by double-click, no server needed)
python dashboard/build.py
open dashboard/index.html
```

## Conventions

- **Same code path back test ↔ live bot** — the regime, data-reading, risk, and orders are identical.
- **No look-ahead:** decide at the close, **execute at the next open.**
- **Charge the 0.05% cost on every fill** before judging any strategy.
- **Neighbors must profit** or it's a curve-fit artifact.
- **Locked test runs exactly once** — never re-run after tweaking.
- **Research data is frozen** in `data/prices.parquet`; the live bot writes only `data/live_prices.parquet`.
- **AI is a small, limited layer on top of testable rules** — the trades themselves come from rules you can back test.
- **Broker key: trading ON, withdrawals always OFF** (esp. crypto exchanges).

## Disclaimer

For research and educational purposes. Nothing in this repo is financial advice. Paper trading first, always — and only go to real money once paper and back test line up.
