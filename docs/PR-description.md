# PR: Prompt 1 — Logic: Asset Behavior Study + Dashboard

Branch: `prompt1` → `main` (PR #2)

## What this PR does

Implements **Prompt 1 (Logic)** of the trading system: a study of how each asset
moves under three conditions, and a self-contained HTML dashboard that presents
the results. It is a research/measurement layer only — it makes **no trading
decisions** and writes **no** `config/system.yaml`.

Per the house rules:
- **All measures use the training window only** (2022-01-03 → 2024-12-31).
  Data before the window only warms up the indicators; nothing after the
  training window is read.
- The three labels and their windows/thresholds live in one place
  (`src/labels.py`), parametrized, and are reused everywhere.

## The three labels (`src/labels.py`)

For every study ticker (SPY QQQ IWM DIA XLK XLF XLE XLV XLI XLY XLP XLU XLB
XLC XLRE TLT IEF SHY SGOV GLD SLV USO DBC TQQQ SQQQ BTC-USD):

- **KEEPS GOING** — after a 20-day close-high (above its 200-day line), the
  average of the next 5 days is positive, with at least 12 qualifying events.
- **SNAPS BACK** — take every close with RSI(2) < 10 while *above* its line,
  skipping any within 5 days of the last kept event and only counting events
  whose next 5 days end inside the window. Average the next-5-day return
  minus the average of every 5-day return inside the window; positive with
  ≥ 12 events = snaps back.
- **HOLDS UP** — on the days the market (SPY) is below its line, the ticker's
  average close-to-close return beats the cash ticker's (SGOV) on those same
  days, with at least 20 market-down days.

All labels return `(verdict, evidence)` with human-readable counts so the
report and CSV are self-explanatory.

## New modules

- **`src/labels.py`** — shared indicators (SMA, Wilder RSI(2), uptrend days,
  realized vol, wild days, forward returns, drawdown) plus the three labels.
  This is the single source of truth; nothing in the dashboard recomputes
  signal logic.
- **`src/data.py`** — downloads/updates `data/prices.parquet` via yfinance,
  adjusted for splits/dividends. Reports rows / first / last / missing days per
  ticker.
- **`asset_study.py`** — runs the study, writes all `results/` artifacts.

## Outputs

- `results/asset_profiles.csv` — one row per ticker: all three label verdicts,
  annualized returns, calm/wild days, correlation with the market, plain-English
  line.
- `results/correlations.csv` — pairwise daily-return correlations, training
  window.
- `results/asset_study.json` — full structured results + correlations +
  plain-English lines.
- `results/spy_line.json` — SPY close, its 200-day line, uptrend/downtrend flag
  per day, training window, downtrend-day count.
- `results/calm_wild.json` — for indices/bonds/cash/metals: average daily move
  on calm days vs wild days + day counts.
- `results/same_dip.json` — for indices/bonds/cash/metals: RSI(2) dip-episode
  next-5-bar return, minus window average, above vs below the 200-day line.
- `reports/asset_study.md` — plain-English lines grouped by label.

## The dashboard (`dashboard/`)

A single self-contained `dashboard/index.html` (double-click / `file://`, no
server, Plotly inlined). Five sections, in this order:

1. **Trading System** — what the study is and its verdicts.
2. **Assets** — every ticker grouped by type, with labels as tags and key
   numbers. Percentages shown as percentages; short column headers with hover
   definitions; ticker names with hover tooltips explaining the fund.
3. **Which assets moves together** — correlation heat map of daily returns,
   fills the section width.
4. **SPY and its 200-day line** — close + line + downtrend dots, training
   window shaded, HTML legend close to the x-axis.
5. **Same Dip** — grouped bar chart: RSI(2) dip episodes, next-5-day return
   minus window average, above vs below the line.
6. **Calm vs Wild** — grouped bar chart: average daily move on calm vs wild
   days.

Shared dashboard behaviors:
- Pure-CSS tooltips (work on `file://`); dark navy tooltips on the table.
- Plotly hover pop-ups: white background, thin black border, page font — applied
  to every chart.
- Plotly mode bar (`displayModeBar: 'hover'`) on all charts: pan/zoom +
  download as PNG/JSON.
- Dividers between groups are drawn as Plotly `shapes` (dotted lines), not
  axis labels — so no stray tick labels appear.
- A build timestamp in the footer; `docs/dashboard-fixes.md` documents the
  browser-cache gotcha and how to measure chart whitespace in headless
  chromium.

## Notable implementation decisions

1. **Single source of truth for signals.** `src/labels.py` is imported by both
   the study and (future) backtest/bot. No signal logic is duplicated in the
   dashboard.
2. **Dashboard is data-injected.** `dashboard/build.py` reads the `results/*.json`
   files and injects them into `{{PLACEHOLDER}}` tokens in each section's HTML.
   Sections are static HTML; only the JSON is swapped. This keeps the sections
   reviewable and the build deterministic.
3. **Episode dedup in Same Dip.** A "dip" is counted once per *run* of
   consecutive RSI(2) < 10 days (the first day of the run), not once per day.
   This matches the reference finding (QQQ rebounds above the line, keeps
   falling below it) and avoids double-counting a multi-day crash.
4. **Calm/Wild + Same Dip include SGOV (cash)** as its own group, with its own
   divider, so it is not visually lumped with metals.
5. **Percent formatting.** Y-axis ticks use `tickformat`/`ticksuffix` so values
   read `0.6%`, not `0.6`. Table cells show percentages, not bare decimals.
6. **House rules copied verbatim** into `CLAUDE.md` / `AGENTS.md`; a pointer to
   `docs/dashboard-fixes.md` was added to both.

## Files to review (priority order)

- `src/labels.py` — the three labels + indicators. Check window boundaries,
  event de-dup, and that `HOLDS UP` uses market-down days vs SGOV.
- `asset_study.py` — the study driver. Check that every measure is restricted
  to the training window and that `same_dip_row`/`calm_wild` group membership
  is correct.
- `dashboard/build.py` — the builder. Check placeholder injection, Plotly
  inlining, and that `build()` accepts an optional output path (CI passes
  `ci-dashboard.html`).
- `dashboard/sections/*.html` — the five sections. Check the injected JSON
  keys, hover text, and divider `shapes`.
- `src/data.py` — the downloader. Check split/dividend adjustment and the
  "report rows/first/last/missing" requirement.

## What is NOT in this PR

- No `config/system.yaml` changes, no backtester, no bot, no engine rules.
- No `.env` or keys. Paper trading only (not relevant here — no live trading).
- `data/prices.parquet` is generated by `src/data.py`, not committed.

## Test plan for a reviewer

```bash
make study        # runs asset_study.py, writes results/
make dashboard    # builds dashboard/index.html
# double-click dashboard/index.html (or open in a browser, hard-refresh)
```

CI runs: `ruff check .`, `ruff format --check .`, and a dashboard build to
`ci-dashboard.html` (must be non-empty).

## Fingerprint

tickers=26, keeps_going=13, snaps_back=19, holds_up=8


## Known deviations from the reference video (deliberate, not bugs)

The reference material shows specific Same Dip numbers for QQQ (above the line
**+0.66%** with 23 events, below the line **−0.83%** with 17 events). Our
Same Dip chart produces **different magnitudes and event counts** for the same
ticker. This is intentional and follows the house rules; the *finding* matches
the video, the exact values do not.

| | Above the line | Below the line |
|---|---|---|
| Reference video (QQQ) | +0.66% (23 events) | −0.83% (17 events) |
| This PR (QQQ) | +0.77% (25 events) | −0.34% (16 events) |

The **sign** is the same in both (rebound above the line, keep falling below
it). The magnitudes differ because we pin every measure to the house rules:

1. **Training window only** (2022-01-03 → 2024-12-31). The reference may have
   used full available history, which shifts both the averages and the event
   counts.
2. **Wilder-smoothed RSI(2)** (the standard Connors-style definition). If the
   reference used a simple-average RSI(2), the event set differs.
3. **Episode dedup**: a dip is counted once per *run* of consecutive RSI(2) < 10
   days (first day of the run), not once per day. This is what makes the
   below-the-line value negative rather than being dominated by the worst days
   of a multi-day crash.
4. **Minus the window's average** next-5-bar return (the "excess" over a random
   5-day stretch), not the raw forward return.

We chose to follow the house rules (training window, Wilder RSI, documented
dedup, baseline-subtracted) so the numbers are reproducible and consistent with
every other measure in the project. If a reviewer wants the numbers to match the
video byte-for-byte, that is a data-range/definition choice to make explicitly,
not a defect in this implementation. The reference numbers should be treated as
a sanity check on the *direction* of the effect, not a target to reproduce.
