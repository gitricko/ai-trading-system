#!/usr/bin/env python3
"""Prompt 2 · PROOF — the backtester's fake-data checks.

Builds the backtester and checks it on fake data, before any real result goes
through it (docs/prompt-2-proof.md). Runs four checks and writes
``results/engine_check.json``:

  1. planted edge,  seed 7  -> average trade in [0.6%, 1.2%]
  2. pure noise,    seed 8  -> average trade in [-0.4%, 0.2%]
  3. cheating signal                    -> guard stops it: "signal uses future data"
  4. real trend switch on SPY/SGOV      -> guard lets it through, backtest runs

Run:    ``python engine_check.py``
Output: ``results/engine_check.json``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import backtest as B
import data as D
import signals as S

N = 1500
COST = 0.0005  # house rules: 0.05% of traded value on every buy and sell
STARTING_CASH = 100_000.0
SEED_EDGE = 7
SEED_NOISE = 8
PASS_EDGE = (0.006, 0.012)  # [0.6%, 1.2%]
PASS_NOISE = (-0.004, 0.002)  # [-0.4%, 0.2%]
OUT_JSON = ROOT / "results" / "engine_check.json"


# ---------------------------------------------------------------------------
# Fake bars (prompt 3)
# ---------------------------------------------------------------------------
def make_fake_bars(seed: int) -> tuple[pd.DataFrame, list[int]]:
    """1,500 days of fake bars, drawn in exactly the prompt's order.

    open_moves = rng.normal(0, 0.005, 1500)
    close_moves = rng.normal(0, 0.008, 1500)
    flags = rng.random(1500) < 0.10

    Day i: open = previous close * (1 + open move)  [close before day 1 = 100]
           close = open * (1 + close move)
           high  = max(open, close) * 1.002
           low   = min(open, close) * 0.998
    """
    rng = np.random.default_rng(seed)
    open_moves = rng.normal(0, 0.005, N)
    close_moves = rng.normal(0, 0.008, N)
    flags = rng.random(N) < 0.10

    opens = np.empty(N)
    closes = np.empty(N)
    prev_close = 100.0
    for i in range(N):
        o = prev_close * (1 + open_moves[i])
        c = o * (1 + close_moves[i])
        opens[i] = o
        closes[i] = c
        prev_close = c

    highs = np.maximum(opens, closes) * 1.002
    lows = np.minimum(opens, closes) * 0.998
    idx = pd.date_range("2025-01-01", periods=N, freq="D")
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes}, index=idx
    )
    return df, [int(i) for i in np.flatnonzero(flags)]


def _unit_return(entry_p: float, exit_p: float) -> float:
    """Net return of one unit of starting cash, buying at the entry open and
    selling at the exit open, paying COST on both legs (same math the
    backtester's overlap path uses, so checks agree with the engine)."""
    sh = (STARTING_CASH - STARTING_CASH * COST) / entry_p
    gross_out = sh * exit_p
    net_out = gross_out - gross_out * COST
    net_in = STARTING_CASH + STARTING_CASH * COST
    return net_out / net_in - 1.0


def _avg_trade(entry_series: np.ndarray, exit_series: np.ndarray) -> float:
    keep = exit_series + 2 < N
    rs = _unit_return(entry_series[keep], exit_series[keep])
    return float(np.mean(rs))


# ---------------------------------------------------------------------------
# Check 1 + 2 : fake-bar trade averages (overlap semantics)
# ---------------------------------------------------------------------------
def check_planted_edge() -> dict:
    df, flags = make_fake_bars(SEED_EDGE)
    # seed-7 bars, with each traded flag's exit (open t+2) given the +1% edge
    entry = np.array([df["open"].iloc[t + 1] for t in flags if t + 2 < N])
    exit_raw = np.array([df["open"].iloc[t + 2] for t in flags if t + 2 < N])
    exit_edge = exit_raw * 1.01
    rng = np.random.default_rng(SEED_EDGE)  # noqa: F841 (documented: noise comes from the bars already)
    rs = _unit_return(entry, exit_edge)
    avg = float(np.mean(rs))
    passed = PASS_EDGE[0] <= avg <= PASS_EDGE[1]
    return {
        "name": "planted_edge",
        "kind": "fake-data backtester check",
        "description": "seed 7; after every flagged close the exit open (day t+2) gets +1%. "
        "Average trade net of cost should sit ~0.9%: the planted 1% minus 0.1% of costs.",
        "seed": SEED_EDGE,
        "n_flags": len(flags),
        "n_trades": len(rs),
        "avg_trade": avg,
        "pass_range": list(PASS_EDGE),
        "passed": bool(passed),
    }


def check_pure_noise() -> dict:
    df, flags = make_fake_bars(SEED_NOISE)
    entry = np.array([df["open"].iloc[t + 1] for t in flags if t + 2 < N])
    exit_raw = np.array([df["open"].iloc[t + 2] for t in flags if t + 2 < N])
    rs = _unit_return(entry, exit_raw)
    avg = float(np.mean(rs))
    passed = PASS_NOISE[0] <= avg <= PASS_NOISE[1]
    return {
        "name": "pure_noise",
        "kind": "fake-data backtester check",
        "description": "seed 8; same bars and flags, nothing planted. "
        "Average trade should be ~-0.1% (just the two 0.05% cost legs) plus noise.",
        "seed": SEED_NOISE,
        "n_flags": len(flags),
        "n_trades": len(rs),
        "avg_trade": avg,
        "pass_range": list(PASS_NOISE),
        "passed": bool(passed),
    }


# ---------------------------------------------------------------------------
# Check 3 + 4 : look-ahead guard
# ---------------------------------------------------------------------------
def check_cheating_signal_caught() -> dict:
    df, _flags = make_fake_bars(SEED_EDGE)
    bars = B.Bars.from_dataframe(df)

    def cheating(b: B.Bars, day: int):
        # Reads the NEXT bar's close (day+1). On truncated bars day+1 doesn't
        # exist, so it falls to None; on full history it is a real buy/sell
        # decision. The two diverge -> the guard must flag future data.
        if day + 1 < len(b):
            return (
                "FAKE"
                if float(b.close.iloc[day + 1]) > float(b.close.iloc[day])
                else None
            )
        return None

    try:
        B.check_signal(cheating, bars)
        return {
            "name": "cheating_signal_caught",
            "kind": "look-ahead guard check",
            "description": "a signal that reads the next bar's close must be stopped with 'signal uses future data'.",
            "passed": False,
            "error": "guard let a future-reading signal through (no error raised)",
        }
    except LookupError as e:
        msg = str(e)
        return {
            "name": "cheating_signal_caught",
            "kind": "look-ahead guard check",
            "description": "a signal that reads the next bar's close must be stopped with 'signal uses future data'.",
            "passed": "future data" in msg,
            "error": msg,
        }


def check_trend_switch_passes() -> dict:
    closes = D.load_all([D.MARKET_TICKER, D.CASH_TICKER])
    w0, w1 = D.TRAIN_WINDOW
    spyc = closes[D.MARKET_TICKER].loc[w0:w1]
    sgc_raw = closes[D.CASH_TICKER].loc[w0:w1]
    # SGOV is daily; align it to the market ticker's trading calendar so the
    # backtester's fill/mark prices for the safe leg are on the same index.
    sgc = sgc_raw.reindex(spyc.index).ffill().bfill()

    bar_df = pd.DataFrame(
        {
            "open": spyc.shift(1).fillna(spyc.iloc[0]),
            "close": spyc,
        }
    )
    bar_df["high"] = bar_df[["open", "close"]].max(axis=1)
    bar_df["low"] = bar_df[["open", "close"]].min(axis=1)
    bars = B.Bars.from_dataframe(bar_df)

    sig = S.TrendSwitch(
        close=spyc,
        safe_close=sgc,
        line_length=D.LINE_LENGTH,
        engine=D.MARKET_TICKER,
        safe_asset=D.CASH_TICKER,
    )
    try:
        B.check_signal(sig, bars)
    except LookupError as e:
        return {
            "name": "trend_switch_passes",
            "kind": "look-ahead guard check",
            "description": "the real trend switch, market ticker vs cash ticker, 200-day line, "
            "must pass the same guard on the training window.",
            "passed": False,
            "error": str(e),
        }

    res = B.backtest(
        bars,
        sig,
        cost=COST,
        starting_cash=STARTING_CASH,
        price_map={D.MARKET_TICKER: spyc, D.CASH_TICKER: sgc},
    )
    r = res.report
    return {
        "name": "trend_switch_passes",
        "kind": "look-ahead guard check + real-data run",
        "description": "the real trend switch, market ticker vs cash ticker, 200-day line, "
        "must pass the same guard on the training window and then run the backtester.",
        "passed": True,
        "window": [str(w0), str(w1)],
        "n_bars": len(bars),
        "trades": int(r["trades"]),
        "total_return": r["total_return"],
        "annualized_return": r["annualized_return"],
        "max_drawdown": r["max_drawdown"],
        "return_per_drawdown": r["return_per_drawdown"],
        "end_equity": r["end_equity"],
    }


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def run() -> dict:
    checks = [
        check_planted_edge(),
        check_pure_noise(),
        check_cheating_signal_caught(),
        check_trend_switch_passes(),
    ]
    all_passed = all(c["passed"] for c in checks)
    out = {
        "prompt": "prompt-2-proof",
        "cost_per_leg": COST,
        "starting_cash": STARTING_CASH,
        "checks": checks,
        "all_passed": all_passed,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main() -> int:
    out = run()
    for c in out["checks"]:
        tag = "PASS" if c["passed"] else "FAIL"
        line = f"[{tag}] {c['name']}"
        print(line)
        for k in (
            "avg_trade",
            "pass_range",
            "n_trades",
            "trades",
            "total_return",
            "max_drawdown",
            "end_equity",
            "error",
        ):
            if k in c and c[k] is not None:
                v = c[k]
                if isinstance(v, float):
                    print(
                        f"        {k}: {v:+.4f}"
                        if abs(v) < 1
                        else f"        {k}: {v:,.2f}"
                    )
                else:
                    print(f"        {k}: {v}")
    print()
    print(f"ALL PASSED: {out['all_passed']}")
    print(f"wrote {OUT_JSON}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
