"""Prompt 3 — Find the core.

Steps 1–4 use the training window only; step 5 is the locked test (run once,
not used to change rules).

  1. Pick the engine: of the engine candidates in my settings, the one with
     the biggest trend gap from Prompt 1.
  2. Pick the safe asset: among candidates with daily correlation with the
     engine < 0.5, the one with highest annualized return on the engine's
     downtrend days. If no candidate beats the cash ticker (SGOV), use cash.
  3. The switch: hold the engine while it closes above its 200-day line,
     otherwise hold the safe asset. Traded at the next open.
  4. Neighbors: rerun with 100/150/250-day SMA, 200-day EMA, and 50/200 golden
     cross. Passes if every version makes money after costs in both windows.
  5. Locked test: run the core once on the locked test window; passes if it
     makes money after costs.
  6. Cost check: rerun at double cost on both windows.

Writes results/core.json. If steps 4 AND 5 pass, writes config/system.yaml.

Run:  python -m src.core
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd

import backtest as B
import data as D
import labels as L
import signals as S

# --- settings (from my settings / AGENTS.md) ---
ENGINE_CANDS = ["SPY", "QQQ", "IWM", "DIA"]
SAFE_CANDS = ["SGOV", "SHY", "IEF", "TLT", "GLD"]
CASH = "SGOV"
LINE_DAYS = 200
COST = B.DEFAULT_COST  # 0.05% per leg
BARS_PER_YEAR = L.BARS_PER_YEAR  # 252

TRAIN = (pd.Timestamp(D.TRAIN_WINDOW[0]), pd.Timestamp(D.TRAIN_WINDOW[1]))
LOCKED = (pd.Timestamp(D.LOCKED_TEST_WINDOW[0]), pd.Timestamp(D.LOCKED_TEST_WINDOW[1]))

OUT_JSON = ROOT / "results" / "core.json"
CONFIG_YAML = ROOT / "config" / "system.yaml"

# Single load of the adjusted-close series; reuse everywhere (avoids
# re-reading parquet + re-printing the download report per call).
_CACHE: dict[str, pd.Series] = {}


def _close(t: str) -> pd.Series:
    if t not in _CACHE:
        _CACHE[t] = D.load_all([t])[t].dropna()
    return _CACHE[t]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _bars_for(
    tickers: list[str], w0: pd.Timestamp, w1: pd.Timestamp, engine: str
) -> tuple[B.Bars, dict]:
    """Build (bars, price_map) for the backtester over [w0, w1].

    bars: built from the engine close on its own bars within [w0, w1];
           open = previous close (established Prompt 2 convention).
    price_map: {ticker: close-series-aligned-to-bars.index} for fill prices.
    """
    eng = _close(engine)
    base = eng.index[(eng.index >= w0) & (eng.index <= w1)]
    frame = pd.DataFrame(
        {
            "open": eng.reindex(base).shift(1).fillna(eng.iloc[0]),
            "close": eng.reindex(base),
        }
    )
    bars = B.Bars.from_dataframe(frame)
    pm = {}
    for t in tickers:
        pm[t] = _close(t).reindex(bars.close.index)
    return bars, pm


def _report_dict(res: B.BacktestResult) -> dict:
    r = res.report
    return {
        "total_return": round(r["total_return"], 6),
        "annualized_return": round(r["annualized_return"], 6),
        "max_drawdown": round(r["max_drawdown"], 6),
        "return_per_drawdown": round(r["return_per_drawdown"], 3),
        "trades": r["trades"],
        "win_rate": round(r["win_rate"], 4),
        "avg_win": round(r["avg_win"], 4),
        "avg_loss": round(r["avg_loss"], 4),
        "gross_win": round(r["gross_win"], 2),
        "gross_loss": round(r["gross_loss"], 2),
        "profit_factor": round(r["profit_factor"], 3),
        "avg_days_held": round(r["avg_days_held"], 2),
        "time_in_market": round(r["time_in_market"], 3),
        "end_equity": round(r["end_equity"], 2),
        "start_equity": round(r["start_equity"], 2),
        "equity_start": round(float(res.equity.iloc[0]), 2),
        "n_bars": len(res.equity),
    }


def _switches_and_time(above: pd.Series, engine: str, safe: str) -> dict:
    """Switches per year (first entry not counted) + share of time per ticker."""
    holdings = np.where(above.fillna(False).values, engine, safe)
    transitions = int(np.sum(holdings[1:] != holdings[:-1]))
    n_bars = len(holdings)
    years = n_bars / BARS_PER_YEAR
    shares = {
        engine: round(float(np.mean(holdings == engine)), 4),
        safe: round(float(np.mean(holdings == safe)), 4),
    }
    # list of (date, from, to) for every switch
    switches = []
    for i in range(1, n_bars):
        if holdings[i] != holdings[i - 1]:
            switches.append(
                {
                    "date": str(above.index[i].date()),
                    "from": holdings[i - 1],
                    "to": holdings[i],
                }
            )
    return {
        "switches_count": transitions,
        "switches_per_year": round(transitions / years, 3) if years > 0 else 0,
        "time_in": shares,
        "switches": switches,
    }


# ---------------------------------------------------------------------------
# main logic
# ---------------------------------------------------------------------------
def _step1_engine() -> tuple[str, dict]:
    """Pick the engine: biggest trend gap from Prompt 1 output."""
    study = json.loads((ROOT / "results" / "asset_study.json").read_text())
    byT = {r["ticker"]: r for r in study["rows"]}
    gaps = {t: round(byT[t]["trend_gap"], 6) for t in ENGINE_CANDS}
    engine = max(ENGINE_CANDS, key=lambda t: byT[t]["trend_gap"])
    return engine, {
        "candidates": [
            {"ticker": t, "trend_gap": gaps[t], "selected": t == engine}
            for t in ENGINE_CANDS
        ]
    }


def _step2_safe(engine: str) -> tuple[str, dict]:
    """Pick the safe asset: best ann-return on engine downtrend days, corr < 0.5;
    fallback to cash ticker if none beats it."""
    tr0, tr1 = TRAIN
    engine_full = _close(engine)
    inT = lambda s: (s.index >= tr0) & (s.index <= tr1)
    engine_close = engine_full[inT(engine_full)]
    upt = L.uptrend_days(engine_full, LINE_DAYS).fillna(False)
    downtrend_mask = (~upt).reindex(engine_close.index, fill_value=False)

    def ann_on_down(s: pd.Series) -> float:
        m = s[inT(s)]
        mask = downtrend_mask.reindex(m.index, fill_value=False).values
        r = m.pct_change().to_numpy()
        dd = np.where(np.isfinite(r), r, 0.0)
        return float(np.mean(dd[mask]) * BARS_PER_YEAR) if mask.any() else float("nan")

    def daily_corr(s: pd.Series) -> float:
        m = s[inT(s)].reindex(engine_close.index)
        both = pd.concat([engine_close, m], axis=1).dropna()
        return float(both.iloc[:, 0].pct_change().corr(both.iloc[:, 1].pct_change()))

    rows = []
    for t in SAFE_CANDS:
        s = _close(t)
        a = ann_on_down(s)
        c = daily_corr(s)
        eligible = c < 0.5
        rows.append(
            {
                "ticker": t,
                "ann_return_on_downtrend": round(a, 6),
                "daily_corr_with_engine": round(c, 5),
                "eligible": eligible,
                "is_cash": t == CASH,
                "selected": False,
            }
        )
    cash_ann = next(r for r in rows if r["ticker"] == CASH)
    eligible_row = [r for r in rows if r["eligible"]]
    best = (
        max(eligible_row, key=lambda r: r["ann_return_on_downtrend"])
        if eligible_row
        else None
    )
    if best and best["ann_return_on_downtrend"] > cash_ann["ann_return_on_downtrend"]:
        safe = best["ticker"]
    else:
        safe = CASH
    for r in rows:
        r["selected"] = r["ticker"] == safe
    return safe, {"candidates": rows}


def _core_run(
    engine: str, safe: str, w0: pd.Timestamp, w1: pd.Timestamp, cost: float = COST
) -> B.BacktestResult:
    """Run the standard 200-day-line switch on [w0, w1] at the given cost."""
    bars, pm = _bars_for([engine, safe], w0, w1, engine)
    sig = S.TrendSwitch(
        _close(engine), _close(safe), LINE_DAYS, engine=engine, safe_asset=safe
    )
    return B.backtest(bars, sig, cost=cost, starting_cash=B.STARTING_CASH, price_map=pm)


def _run_neighbor(
    engine: str,
    safe: str,
    w0: pd.Timestamp,
    w1: pd.Timestamp,
    length: int,
    kind: str,
    golden: bool,
    cost: float = COST,
) -> B.BacktestResult:
    bars, pm = _bars_for([engine, safe], w0, w1, engine)
    eng = _close(engine)
    if golden:
        above = (
            (L.sma(eng, 50) > L.sma(eng, 200)).reindex(bars.close.index).fillna(False)
        )
    elif kind == "ema":
        above = (
            (eng > eng.ewm(span=length, adjust=False).mean())
            .reindex(bars.close.index)
            .fillna(False)
        )
    else:
        above = (eng > L.sma(eng, length)).reindex(bars.close.index).fillna(False)

    def sig(bars_b: B.Bars, day: int) -> str:
        return engine if bool(above.iloc[day]) else safe

    return B.backtest(bars, sig, cost=cost, starting_cash=B.STARTING_CASH, price_map=pm)


def _equity_pairs(equity: pd.Series) -> list[list]:
    return [[str(d.date()), round(float(v), 2)] for d, v in equity.items()]


def _held_strip(
    engine: str, safe: str, w0: pd.Timestamp, w1: pd.Timestamp
) -> list[list]:
    """Per-bar holding: [date, 'engine'|'safe']."""
    eng = _close(engine)
    above = (
        (eng > L.sma(eng, LINE_DAYS))
        .reindex(eng.index[(eng.index >= w0) & (eng.index <= w1)])
        .fillna(False)
    )
    return [[str(d.date()), "engine" if b else "safe"] for d, b in above.items()]


# ---------------------------------------------------------------------------
def main() -> int:
    print("=== Prompt 3 · Finding the core ===", flush=True)

    # Step 1
    engine, eng_info = _step1_engine()
    print(
        f"Step 1 — engine: {engine}  (trend_gap={eng_info['candidates'][[c['ticker'] for c in eng_info['candidates']].index(engine)]['trend_gap']})"
    )

    # Step 2
    safe, safe_info = _step2_safe(engine)
    print(f"Step 2 — safe asset: {safe}")
    for r in safe_info["candidates"]:
        mark = " ←" if r["selected"] else ""
        print(
            f"   {r['ticker']:5s}  down_ret={r['ann_return_on_downtrend']:+.4f}  "
            f"corr={r['daily_corr_with_engine']:+.3f}  eligible={r['eligible']}{mark}"
        )

    tr0, tr1 = TRAIN
    lk0, lk1 = LOCKED

    # Step 3: core switch on both windows
    print("\nStep 3 — core switch (engine vs safe, 200-day line):")
    core_tr = _core_run(engine, safe, tr0, tr1)
    core_lk = _core_run(engine, safe, lk0, lk1)
    cost_tr2 = _core_run(engine, safe, tr0, tr1, cost=COST * 2)
    cost_lk2 = _core_run(engine, safe, lk0, lk1, cost=COST * 2)

    # Above-line vector for switches/time
    eng = _close(engine)
    above_tr = (
        (eng > L.sma(eng, LINE_DAYS))
        .reindex(eng.index[(eng.index >= tr0) & (eng.index <= tr1)])
        .fillna(False)
    )
    above_lk = (
        (eng > L.sma(eng, LINE_DAYS))
        .reindex(eng.index[(eng.index >= lk0) & (eng.index <= lk1)])
        .fillna(False)
    )
    sw_tr = _switches_and_time(above_tr, engine, safe)
    sw_lk = _switches_and_time(above_lk, engine, safe)

    r_tr = _report_dict(core_tr)
    r_lk = _report_dict(core_lk)
    print(
        f"   training : total={r_tr['total_return']:+.4f} ann={r_tr['annualized_return']:+.4f} "
        f"mdd={r_tr['max_drawdown']:.4f} rpdd={r_tr['return_per_drawdown']:.3f} "
        f"trades={r_tr['trades']} switches/yr={sw_tr['switches_per_year']}"
    )
    print(
        f"   locked   : total={r_lk['total_return']:+.4f} ann={r_lk['annualized_return']:+.4f} "
        f"mdd={r_lk['max_drawdown']:.4f} rpdd={r_lk['return_per_drawdown']:.3f} "
        f"trades={r_lk['trades']} switches/yr={sw_lk['switches_per_year']}"
    )

    # Step 4: neighbors
    print("\nStep 4 — neighbors (all must make money after costs, both windows):")
    NEIGHBORS = [
        ("100-day line", 100, "sma", False),
        ("150-day line", 150, "sma", False),
        ("250-day line", 250, "sma", False),
        ("200-day EMA", 200, "ema", False),
        ("50/200 golden cross", 50, "sma", True),
    ]
    neighbors = []
    all_neighbors_pass = True
    for name, ln, kind, golden in NEIGHBORS:
        r_n = _run_neighbor(engine, safe, tr0, tr1, ln, kind, golden)
        r_nl = _run_neighbor(engine, safe, lk0, lk1, ln, kind, golden)
        tr_ok = r_n.report["total_return"] > 0
        lk_ok = r_nl.report["total_return"] > 0
        ok = tr_ok and lk_ok
        all_neighbors_pass = all_neighbors_pass and ok
        neighbors.append(
            {
                "name": name,
                "training": _report_dict(r_n),
                "locked_test": _report_dict(r_nl),
                "makes_money_training": tr_ok,
                "makes_money_locked": lk_ok,
                "passes": ok,
            }
        )
        print(
            f"   {name:22s} train={r_n.report['total_return']:+.4f} "
            f"lock={r_nl.report['total_return']:+.4f}  {'PASS' if ok else 'FAIL'}"
        )

    # Step 5: locked test
    step5_pass = r_lk["total_return"] > 0
    print(
        f"\nStep 5 — locked test: {'PASS' if step5_pass else 'FAIL'} "
        f"(total_return={r_lk['total_return']:+.4f})"
    )

    # Step 6: cost check
    cost_tr_ok = cost_tr2.report["total_return"] > 0
    cost_lk_ok = cost_lk2.report["total_return"] > 0
    step6_pass = cost_tr_ok and cost_lk_ok
    print(
        f"Step 6 — cost check (2× cost): train={cost_tr2.report['total_return']:+.4f} "
        f"lock={cost_lk2.report['total_return']:+.4f}  "
        f"{'PASS' if step6_pass else 'FAIL'}"
    )

    # Step 7
    steps_pass = all_neighbors_pass and step5_pass
    print(f"\nSteps 4 & 5 pass: {steps_pass}")

    # --- assemble core.json ---
    out = {
        "engine": engine,
        "safe": safe,
        "line_days": LINE_DAYS,
        "cost_per_leg": COST,
        "steps": {
            "step1_engine": {**eng_info, "engine": engine},
            "step2_safe": {**safe_info, "safe": safe},
            "step3_core_switch": {
                "training": r_tr,
                "locked_test": r_lk,
                "switches_training": sw_tr,
                "switches_locked": sw_lk,
                "equity_training": _equity_pairs(core_tr.equity),
                "equity_locked": _equity_pairs(core_lk.equity),
                "held_training": _held_strip(engine, safe, tr0, tr1),
                "held_locked": _held_strip(engine, safe, lk0, lk1),
            },
            "step4_neighbors": {
                "all_pass": all_neighbors_pass,
                "neighbors": neighbors,
            },
            "step5_locked_test": {
                "passed": step5_pass,
                "total_return": r_lk["total_return"],
            },
            "step6_cost_check": {
                "cost": COST * 2,
                "training": _report_dict(cost_tr2),
                "locked_test": _report_dict(cost_lk2),
                "passes": step6_pass,
            },
        },
        "all_steps_pass": steps_pass,
        "window": {
            "training": [str(tr0.date()), str(tr1.date())],
            "locked_test": [str(lk0.date()), str(lk1.date())],
        },
        "fingerprint": (
            f"engine={engine}, safe={safe}, "
            f"train return/yr={r_tr['annualized_return'] * 100:.1f}%, "
            f"train max DD={r_tr['max_drawdown'] * 100:.1f}%, "
            f"test return/yr={r_lk['annualized_return'] * 100:.1f}%, "
            f"test max DD={r_lk['max_drawdown'] * 100:.1f}%, "
            f"train switches={sw_tr['switches_count']}, "
            f"neighbors={'pass' if all_neighbors_pass else 'fail'}, "
            f"locked test={'pass' if step5_pass else 'fail'}"
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf-8")
    print(f"\nwrote {OUT_JSON}")

    if steps_pass:
        CONFIG_YAML.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_YAML.write_text(
            f"core:\n  engine: {engine}\n  safe: {safe}\n  line_days: {LINE_DAYS}\n",
            encoding="utf-8",
        )
        print(f"wrote {CONFIG_YAML}")
    else:
        print("Steps 4 & 5 did NOT both pass — not writing config/system.yaml.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
