#!/usr/bin/env python3
"""Prompt 1 - Logic: how each asset moves.

Uses the study tickers and the training window only (2022-01-03 to 2024-12-31).
Nothing after the training window gets read. Data before the window only
warms up the indicators.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import data as D
import labels as L

TRAIN = (pd.Timestamp(D.TRAIN_WINDOW[0]), pd.Timestamp(D.TRAIN_WINDOW[1]))
W0, W1 = TRAIN
LINE = D.LINE_LENGTH
BARS_PER_YEAR = L.BARS_PER_YEAR  # 252 for daily bars
MARKET = D.MARKET_TICKER
CASH = D.CASH_TICKER

GROUPS = {
    "Stock indices": ["SPY", "QQQ", "IWM", "DIA"],
    "Sectors": [
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
        "XLC",
        "XLRE",
    ],
    "Bonds": ["TLT", "IEF", "SHY"],
    "Cash": ["SGOV"],
    "Metals": ["GLD", "SLV"],
    "Commodities": ["USO", "DBC"],
    "Leveraged ETFs": ["TQQQ", "SQQQ"],
    "Crypto": ["BTC-USD"],
}


def _in_window(idx, w0, w1) -> np.ndarray:
    a = np.asarray(idx, dtype="datetime64[ns]")
    return (a >= np.datetime64(pd.Timestamp(w0))) & (
        a <= np.datetime64(pd.Timestamp(w1))
    )


def ann_ret(close: pd.Series, mask: np.ndarray | pd.Series) -> float | None:
    """Annualized return of a set of days: mean close-to-close return times bars per year."""
    ret = close.pct_change().to_numpy()
    r = np.where(np.isfinite(ret), ret, np.nan)
    m = mask.to_numpy() if isinstance(mask, pd.Series) else np.asarray(mask)
    if not np.isfinite(r[m]).any():
        return None
    return float(np.nanmean(r[m]) * BARS_PER_YEAR)


def market_downtrend_days(market: pd.Series) -> set:
    down = ~L.uptrend_days(market, LINE).fillna(False)
    return set(market.index[down.to_numpy()])


def ann_on_market_down(close: pd.Series, down_set: set) -> float | None:
    # down_set comes from the market ticker's bars, so bars outside the
    # market calendar (e.g. BTC-USD weekends) are excluded by construction.
    in_w = (close.index >= W0) & (close.index <= W1)
    m = pd.Series([d in down_set for d in close.index], index=close.index) & in_w
    return ann_ret(close, m)


def main() -> None:
    closes = D.load_all(
        D.STUDY_TICKERS
    )  # prints rows / first / last / missing per ticker
    market = closes[MARKET]
    cash = closes[CASH]
    mkt_down = market_downtrend_days(market)
    cash_ret_on_mkt_down = ann_on_market_down(cash, mkt_down)

    rows = []
    for t in D.STUDY_TICKERS:
        c = closes[t]
        in_w = (c.index >= W0) & (c.index <= W1)

        ret = c.pct_change().fillna(0.0)
        sub = c[in_w]
        n_bars = int(in_w.sum())
        ann_return = L.annualized(float(sub.iloc[-1] / sub.iloc[0]), max(n_bars - 1, 1))
        vol = float(ret[in_w].std(ddof=1) * np.sqrt(BARS_PER_YEAR))
        mdd = L.max_drawdown(sub)

        up = L.uptrend_days(c, LINE).fillna(False)
        share_up = float((up & in_w).sum() / n_bars)
        ann_up = ann_ret(c, in_w & up)
        ann_down = ann_ret(c, in_w & ~up)
        trend_gap = (
            (ann_up - ann_down)
            if (ann_up is not None and ann_down is not None)
            else None
        )

        a = c.index.intersection(market.index)
        a = pd.Index([d for d in a if W0 <= d <= W1])
        corr = float(
            c.loc[a].pct_change().dropna().corr(market.loc[a].pct_change().dropna())
        )

        wild = L.wild_days(c, 20, 252).fillna(False)
        ar = c.pct_change().abs()
        calm_m = in_w & (~wild)
        wild_m = in_w & wild
        avg_calm = float(ar[calm_m].mean()) if int(calm_m.sum()) else None
        avg_wild = float(ar[wild_m].mean()) if int(wild_m.sum()) else None

        kg = L.keeps_going(c, LINE, TRAIN)
        sb = L.snaps_back(c, LINE, TRAIN, side="above")
        sb_below = L.snaps_back(c, LINE, TRAIN, side="below")
        hu = L.holds_up(c, market, cash, LINE, TRAIN)

        label_list = [
            n
            for n, h in (
                ("keeps going", kg.label),
                ("snaps back", sb.label),
                ("holds up", hu.label),
            )
            if h
        ]

        # one plain-English line
        bits = []
        bits.append(
            "keeps going after new highs"
            if kg.label
            else "doesn't keep going after new highs"
        )
        bits.append(
            "bounces after quick drops"
            if sb.label
            else "doesn't bounce after quick drops"
        )
        if hu.label:
            bits.append("holds up when the market falls")
        elif hu.return_on_downtrend_days is not None:
            bits.append("doesn't hold up when the market falls")
        if corr is not None:
            if corr >= 0.8:
                bits.append("moves almost one-for-one with the market")
            elif corr >= 0.5:
                bits.append("moves strongly with the market")
            elif abs(corr) < 0.3:
                bits.append("barely moves with the market")
            else:
                bits.append("moves with the market")
        if mdd is not None and vol is not None:
            if mdd >= 0.4 and vol >= 0.30:
                bits.append("rough ride")
            elif mdd <= 0.15 and vol <= 0.20:
                bits.append("smooth ride")
        plain = f"{t}: " + ", ".join(bits) + "."

        rows.append(
            {
                "ticker": t,
                "group": next(g for g, vs in GROUPS.items() if t in vs),
                "labels": " | ".join(label_list) if label_list else "(none)",
                "ann_return": ann_return,
                "volatility": vol,
                "max_drawdown": mdd,
                "share_uptrend_days": share_up,
                "trend_gap": trend_gap,
                "keeps_going": kg.label,
                "keeps_going_excess": kg.excess,
                "keeps_going_events": kg.events,
                "snaps_back": sb.label,
                "snaps_back_excess": sb.excess,
                "snaps_back_events": sb.events,
                "snaps_back_below_line": sb_below.label,
                "snaps_back_below_line_excess": sb_below.excess,
                "snaps_back_below_line_events": sb_below.events,
                "holds_up": hu.label,
                "corr_with_market": corr,
                "ann_return_when_market_falls": ann_on_market_down(c, mkt_down),
                "cash_ann_return_when_market_falls": cash_ret_on_mkt_down,
                "avg_abs_move_calm_days": avg_calm,
                "avg_abs_move_wild_days": avg_wild,
                "n_calm_days": int(calm_m.sum()),
                "n_wild_days": int(wild_m.sum()),
                "plain": plain,
            }
        )

    df = pd.DataFrame(rows)

    out = ROOT / "results"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "asset_profiles.csv", index=False)

    full_corr = pd.DataFrame(
        {t: closes[t].pct_change().loc[W0:W1] for t in D.STUDY_TICKERS}
    ).corr()
    full_corr.to_csv(out / "correlations.csv")

    # daily SPY series for the dashboard "SPY and its 200-day line" section:
    # display only — shows the full series so the training-window shading reads
    # in context (the 200-day line needs warm-up bars before the window too);
    # each row is flagged `in_training` and no measure is computed from
    # post-training data. Uptrend day = previous close above previous day's
    # line (L.uptrend_days, the shared definition).
    spy = market
    spy_line = spy.rolling(LINE, min_periods=LINE).mean()
    up_mask = L.uptrend_days(spy, LINE).fillna(False)
    valid = spy_line.notna()
    in_train_mask = pd.Series((spy.index >= W0) & (spy.index <= W1), index=spy.index)
    dates = [d.strftime("%Y-%m-%d") for d in spy.index[valid]]
    spy_plot = {
        "dates": dates,
        "close": [round(float(v), 2) for v in spy[valid].to_list()],
        "line": [round(float(v), 2) for v in spy_line[valid].to_list()],
        "uptrend": [bool(b) for b in up_mask[valid].to_list()],
        "in_training": [bool(b) for b in in_train_mask[valid].to_list()],
        "training_window": [str(W0.date()), str(W1.date())],
        "bars_in_training": int(in_train_mask.sum()),
        "downtrend_days_in_training": int(
            (in_train_mask & ~up_mask.fillna(False)).sum()
        ),
    }
    (out / "spy_line.json").write_text(json.dumps(spy_plot, indent=1), encoding="utf-8")

    # calm vs wild daily move sizes (stock indices, bonds, metals) -> bar chart
    cw_groups = ("Stock indices", "Bonds", "Metals", "Cash")
    calm_wild = {
        "training_window": [str(W0.date()), str(W1.date())],
        "rows": [
            {
                "ticker": r["ticker"],
                "group": r["group"],
                "calm_pct": (
                    None
                    if r["avg_abs_move_calm_days"] is None
                    else round(r["avg_abs_move_calm_days"] * 100, 3)
                ),
                "wild_pct": (
                    None
                    if r["avg_abs_move_wild_days"] is None
                    else round(r["avg_abs_move_wild_days"] * 100, 3)
                ),
                "n_calm": r["n_calm_days"],
                "n_wild": r["n_wild_days"],
            }
            for r in rows
            if r["group"] in cw_groups
        ],
    }
    (out / "calm_wild.json").write_text(
        json.dumps(calm_wild, indent=1), encoding="utf-8"
    )

    # same dip, different line: RSI(2) below 10 on a training day -> average
    # next-5-bar return minus the window's average, above vs below the line.
    sd_groups = {"Stock indices", "Bonds", "Metals", "Cash"}

    def same_dip_row(r):
        t = r["ticker"]
        c = closes[t].dropna()
        line = L.sma(c, LINE)
        rsi2 = L.wilder_rsi2(c)
        fwd5 = c.pct_change(5).shift(-5)  # 5-bar move starting at day t

        # window's average daily return, scaled to the same 5-bar horizon
        r_all = c.pct_change().to_numpy()
        m_win = _in_window(c.index, W0, W1)
        base5 = (
            float(np.nanmean(r_all[m_win])) * 5
            if np.isfinite(r_all[m_win]).any()
            else 0.0
        )

        above_vals, below_vals = [], []
        n_events = 0
        last_hit = -99
        for i in range(len(c)):
            if not (W0 <= c.index[i] <= W1):
                continue
            if not (np.isfinite(rsi2.iloc[i]) and rsi2.iloc[i] < 10):
                continue
            if not (np.isfinite(line.iloc[i]) and np.isfinite(fwd5.iloc[i])):
                continue
            # count each dip episode once: only the first day of a run of
            # consecutive RSI(2) < 10 days (a dip spans several days; don't
            # double-count them)
            if i - last_hit > 1:
                n_events += 1
                (above_vals if c.iloc[i] > line.iloc[i] else below_vals).append(
                    float(fwd5.iloc[i]) - base5
                )
            last_hit = i

        row = {"ticker": t, "group": r["group"], "n_events": n_events}
        for name, vals in (("above", above_vals), ("below", below_vals)):
            row[name + "_pct"] = round(float(np.mean(vals)) * 100, 3) if vals else None
            row[name + "_n"] = len(vals)
        return row

    same_dip = {
        "training_window": [str(W0.date()), str(W1.date())],
        "rule": "RSI(2) dip episode (first day of a run of RSI(2) below 10): average next-5-bar return minus the window's average, above vs below the 200-day line",
        "rows": [same_dip_row(r) for r in rows if r["group"] in sd_groups],
    }
    (out / "same_dip.json").write_text(json.dumps(same_dip, indent=1), encoding="utf-8")

    # report: plain lines grouped by label
    def grouped(key):
        out = [f"- {r['plain']}" for r in rows if key(r)]
        return out or ["- (none)"]

    none_key = lambda r: not (r["keeps_going"] or r["snaps_back"] or r["holds_up"])
    md = (
        [
            "# Asset study",
            "",
            f"Training window only: {W0.date()} to {W1.date()}. Nothing after the window was read.",
            "",
            "Note: `trend_gap` is null where it is not measurable (e.g. SGOV, which has no trend).",
            "",
            "## Keeps going",
            "",
        ]
        + grouped(lambda r: r["keeps_going"])
        + ["", "## Snaps back", ""]
        + grouped(lambda r: r["snaps_back"])
        + ["", "## Holds up", ""]
        + grouped(lambda r: r["holds_up"])
        + ["", "## No label", ""]
        + grouped(none_key)
        + [""]
    )
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "asset_study.md").write_text("\n".join(md), encoding="utf-8")

    print(
        f"\nwrote {out / 'asset_profiles.csv'}, {out / 'correlations.csv'}, {ROOT / 'reports' / 'asset_study.md'}"
    )
    for r in rows:
        print(f"  {r['ticker']:>7}: {r['labels']:<40} {r['plain']}")


if __name__ == "__main__":
    main()
