# The ALPHA framework — the trading-bot system (AI Pathways course)

> Source: [How To Actually Build an AI Trading Bot With Claude (3 Hour Course) — AI Pathways](https://www.youtube.com/watch?v=gJLKVsIqiTE)
> A distilled reference for future agents working in this repo. Captures **what** the course builds and **why** — the reasoning, the funnel, the gotchas — so we test the same way as the course. The transcript (`transcript.txt`, 2121 lines) is the ground truth; this file is our working summary. **Not financial advice** — the video is explicit it "guarantees no profits" and is "simply the operational steps to get to a working trading bot."

## The one-liner

A **local, Claude-built, no-code-required** trading *system* (not a single bot) that studies how each asset moves, tests strategies that fit with a strict out-of-sample funnel, and then runs the winning rules on a broker paper account automatically, sending updates to your phone.

Everything is **files in one folder** — no cloud, no server, no database. Your computer only needs to be on and awake at the two daily run windows (evening + morning). A small **ticker script** wakes the run based on the New York clock; Claude is in the loop for *building and iterating* the system, but the run itself is a simple Python script that does not need the chat open.

## THE FRAMEWORK — ALPHA (five letters, in order)

The course is the acronym **ALPHA**: **a**rchitecture → **l**ogic → **p**roof → **h**arness → **a**dapt. Do them in order; each letter unlocks the next.

### A — Architecture
- Set up in a Claude desktop app (or an equivalent coding agent). Pick the right model.
- Learn the distinction the course keeps returning to: **Prompt** (one instruction) vs. **Skill** (a repeatable capability Claude keeps using) vs. **Schedule** (a job that runs without you asking). Most of the later "harness" magic is just *skill + schedule* built in the architecture phase.
- Lay out the project and freeze the settings. **This is prompt 0 in this repo** — `CLAUDE.md` + `AGENTS.md` + `.env.example` + the folder layout + the dashboard shell.
- Delineate **core** vs. **sleeve** (see below). Architecture is where the difference between "a trading bot" and "a trading *system*" is decided.

### L — Logic
- Pick the **bar size** / time frame to trade (daily in this repo; intraday changes data cost and needs a live feed).
- Pick the **assets** into the settings block ("My settings" in `CLAUDE.md`).
- **Study how each asset moves**, then build **regimes** on top: **uptrend vs. downtrend** (tracked on the market ticker, SPY stands in for the whole market) + **calm vs. volatile.**
- **Match a strategy to each asset** it actually fits (not a blanket rule for every symbol).
- **Write exact rules** — this is the core discipline. An idea like "buy the dip" is not a rule. A rule is a fixed set of numbers you can code and test:
  - **Dip-buy**: e.g. RSI < 15, sell above the 3- or 10-day average (vs. holding above the 5-day).
  - **Breakout**: e.g. 20-day or 100-day high (vs. the 50-day).
  - These are *examples*; the exact numbers live in the study and are per-asset.

Regime is **not a strategy** — it's **the layer every strategy reads**, sitting in the middle. It also drives **position sizing**: full size on calm days, **half size on volatile days** (a big move on a wild day is the same exposure as full size on a calm day — halving caps the tail). Regime shifts over years (calm stretches → crashes → chop → rate cycles), which is exactly why sleeves must keep **rotating** to beat **strategy decay**.

### P — Proof
- **Validate the back tester** — run it on fake known prices first, confirm it reproduces the seeded result. Then trust it with a real strategy. **This is a mandatory step the course hammers on** (#5 common mistake: "trusting a back test you never checked").
- **Core strategy search.** In the course, a **QQQ ↔ gold** rotation between the trend engine and the safe asset. On top of it, an **optional market filter**: when VIX jumps above its middle (fear) while breadth is still > 50% uptrend, hold gold for the next five trading days, then back to normal.
- **Sleeve funnel** — the 44-idea → 7-survivor gate below.
- **Build the combined account** (core + sleeves) and test how sleeves get *picked / rotated into* a slot.
- Optional add-ons — **market filter** (VIX + breadth), **stock screener** (each historical date needs *that date's* constituent list, e.g. Nike was in the 2022 S&P 500), **AI layer** (Claude reads Fed statements / earnings / news a rule can't express) — all pass the same funnel before they earn a slot.

### H — Harness
- Build the **live bot** on Alpaca (paper account) in this repo's `src/`.
- **Same code path back-test ↔ live** — the regime, data-reading, risk module, and order placement are identical; only the "send to broker vs. log to file" step differs. The course calls this out repeatedly, and its prompt requires a check that live signals match the back-test's over the last 60 days — a requirement a later prompt in this repo is expected to implement.
- **Two scheduled runs** via a small ticker script:
  - **Evening** (after 7:00 p.m. NY on a trading day, before midnight): download the day's prices, compute orders, send them to Alpaca via the API keys in `.env`; broker holds until the open; message the phone (Telegram).
  - **Morning** (a little after the open): check every open position still has its **stop order** in place (re-issue any that the exchange dropped — Alpaca's API drops stops when the position goes flat and stops only become placeable once the position is *owned*), and message the phone.
- **Telegram bot** for phone notifications (set up via BotFather).
- **Risk module** — a code-side cap so a single day's drawdown can't exceed X (a **kill line** in the course's language).
- **Three test modes**: **dry run** (does everything except sending files or orders — also how you replay on a weekend), **paper** (real API, no real money), **live** (real account).
- **Fed check** schedule: Claude reads the next day's Fed statement (or earnings / newsletter / Substack a rule can't) on the schedule and stores the output to `calls/fed/`. Bot will skip a trade the call warns against if the AI layer is on; if it's off, the call is just logged and does not change anything.

### A — Adapt
- **Compare paper trades ↔ back test** — they should line up. If the paper version is worse, something is wrong (usually slippage/cost or an unmodeled rule).
- **The bench** — a candidate sleeve that fails the *current window* but might fit the *next* market stays on a bench and gets re-tested when the regime shifts.
- **Scheduled Claude review**: e.g. weekly, Claude looks at last week's trades side-by-side with the back test and explains any divergence.
- **Iterate** — this is what makes it a **system**, not a one-off bot. Add-ons you can bolt on top of the base, in any order, each still through the *same* out-of-sample gate:
  1. Run it on a different market (change the settings block, re-run).
  2. Add your own ideas as exact rules.
  3. Shorter bars (hourly / 1-min) — needs a live feed, more data cost, a machine that doesn't sleep, and the bot has extra "if the feed drops, don't keep trading" safety hooks.
  4. VIX / volatility dial instead of a single regime.
  5. Options (wheel strategy, etc.) on top of the sleeve signals.
  6. More AI layers — earnings reads, news, X/Twitter feeds, etc.
  7. Two parallel systems (different markets, different setups) — but each on its own account / paper account so the risk module's math stays per-account.

## Core vs. Sleeve (the account structure)

| | Core | Sleeve |
|---|---|---|
| Share | ~70% (can drop to 50% for higher risk) | ~30% (can grow) |
| Horizon | Long, "better than cash", barely trades | Short, trades often, **rotates** |
| Role | Capital growth across the year | Setups that catch regime shifts the core misses |
| Example (course) | QQQ ↔ gold rotation on the 200-day line, with an optional VIX / breadth market filter on top | Dip-buy / breakout per asset |
| Rebalance | Rare (only on regime reversal) | Constant — this is the anti-decay part |

**Order matters**: each asset's *sleeves* are chosen based on the current regime so that when a sleeve trades, it does so *with* the market's direction that day, not against. This is what makes the bot "dynamic and adapted to how the market actually looks for the day" (course's words).

## The sleeve funnel (44 → 7 in the course's run)

| # | Gate | What it checks |
|---|---|---|
| 0 | **Idea** | the rules are *exact* (numbers, not "buy the dip") |
| 1 | **Fit the asset** | the rules fit the specific ticker they're being applied to |
| 2 | **Pass training** | profitable *after the 0.05% round-trip cost is charged* on the training window (2022 → 2024) |
| 3 | **Enough trades** | statistically meaningful count (dip-buy ≥ 15 · breakout ≥ 6) |
| 4 | **Profit factor ≥ 1.3** | winners' $ out-earning losers' $ by 30%+ |
| 5 | **Neighbors** | the *nearby parameter values* also profit (a **hill**, not a **spike**) |
| 6 | **Locked test (once)** | still profitable on 2025 → present, data it has never seen — **run exactly once, no re-running after tweaks** |

The 7 survivors in the course's run: **QQQ dip-buy, QQQ breakout, XLK dip-buy, XLK breakout, XLF breakout, XLY dip-buy, GLD dip-buy.**

The two gates that most people skip and the two most expensive:
- **Neighbors** — if the strategy works only at *exactly* RSI-15 and not RSI-14 or 16, it's a curve-fit spike. It must survive a whole band.
- **Locked test** — the moment you use the test window to pick the rule, it stops being out-of-sample. Run it once; if it fails, go back to your *ideas*, do **not** tweak-and-rerun.

## The 10 most common mistakes (test this way, not that)

1. **Tuning a rule until the back test looks perfect** (200→190→210→187…). A real rule looks like a **hill** (neighbors do well too); a lucky one is a **spike** (one value, big peak).
2. **Using the locked test to pick, then re-running after tweaks.** The moment the test helps you choose, it's no longer out-of-sample.
3. **Look-ahead** — deciding to buy off *today's close* and then buying at *that same close* is a price nobody could actually get. Decide at the close, **buy at the next day's open**.
4. **Forgetting the 0.05% cost per fill.** A rule that trades daily pays ~25% a year in costs *before* it has made anything.
5. **Trusting a back test you never checked.** Claude will write good-looking code but the bugs that matter are the ones that make results look *better* than they are. Test the engine on fake known data first.
6. **Trusting a rule with only a couple of trades.** 55% win rate over 10 trades could really be anywhere from 25% to 85%.
7. **Testing a screener with today's list against past years.** The 2022 S&P 500 had, e.g., Nike in it — Nike isn't in it now. You need **each historical date's own constituent list**.
8. **Letting AI make the actual trades.** Claude can't *back-test* itself (non-deterministic), and the moment it "knows" the past, its "predictions" are hindsight dressed up. Let **testable rules** trade; keep AI as a **small, limited extra layer**. (A hybrid — strict rules + data in + Claude as final analytic layer — is acceptable, but it's inherently not back-testable, so don't let it *own* the position.)
9. **Going too big too soon.** Paper account first → prove the paper version and the back test agree → then (and only then) real money, small.
10. **Quitting after a single bad week.** Every system has losing weeks. If the account is down *inside* the worst draw the back test already showed, that's the system doing what it always does — don't switch strategies. If the account breaks *past* the worst back-tested draw, that's a real signal.

## Brokers — what actually changes when you switch

Everything up to the "place the order" step is broker-agnostic: rules, tests, risk, data. The *final step* — send order / place stop / read holdings back — is broker-specific. The course's guidance:

- **Alpaca (start here):** paper account, simplest API, holds the login, no weekly manual re-auth. No futures. Crypto on the lowest tier is ~**0.25% per immediate-fill order** (about 5× the 0.05% cost we use for stocks).
- **IBKR:** paper account, has **futures**, needs its **IB Gateway program running** and a **weekly manual login**; the API token expires every 7 days.
- **Schwab:** apply through their developer site, no futures, 7-day API token, weekly login.
- **Crypto exchanges** (Kraken, Coinbase, etc.): each has its own API key with two switches — **trading ON, withdrawals OFF**. Fees are a percentage of every trade, higher than stocks.

When you switch, **run the new broker alongside the current one** — one line in the rules file picks which is active — so you can flip back if something's off. Run it in **paper mode** first, on the new account, until it lines up with the back test.

## House rules — the repo's "My settings" block

These live in `CLAUDE.md` (mirrored to `AGENTS.md` for Codex), and are the frozen knobs every prompt reads:

- **Bar size:** daily
- **Data:** 2020-07-01 → 2026-10-23 · `yfinance` · split- & dividend-adjusted · frozen in `data/prices.parquet`
- **Training window:** 2022-01-03 → 2024-12-31
- **Locked test window (once):** 2025-01-02 → 2026-10-23
- **Engine candidates:** SPY QQQ IWM DIA · **Safe candidates:** SGOV SHY IEF TLT GLD · **Cash:** SGOV
- **Market ticker:** SPY (its uptrend / downtrend days stand in for the whole market)
- **Studied, never traded:** BTC-USD
- **Cost:** 0.05% of traded value per fill · **Starting capital:** $100,000

## Where this repo is now

| | | |
|---|---|---|
| ✅ **A** — Architecture | done | prompt 0: folders, house rules, `.env.example`, dashboard shell |
| ⏳ **L** — Logic | next | asset study, regime gauges, per-asset sleeve rules |
| ⏳ **P** — Proof | then | back-tester validation, core search, sleeve funnel, combined account |
| ⏳ **H** — Harness | then | Alpaca bot, evening/morning runs, Telegram, risk module, tests |
| ⏳ **A** — Adapt | last | paper↔backtest alignment, bench, scheduled reviews, iteration |

> **Rule of thumb for any new prompt / file:** if it's in a letter we haven't reached yet, it goes in a `TODO` under the right letter; don't build ahead of the funnel.
