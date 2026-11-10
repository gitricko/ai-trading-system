"""Tests for Prompt 2 (PROOF): the backtester and its fake-data checks.

The three *fake-data* checks are hermetic (no network, no downloads) and are
the gate the house rules require before any real result may go through the
backtester. The real-data trend-switch check is run when research data is
present (CI has none, so it is skipped there) - it exists to prove the
guard lets a legitimate signal through and the backtester can consume it.

``make test`` / ``pytest tests/`` runs all of this; the real-data check
skips automatically when the parquet is absent, so CI stays green.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pytest

import engine_check as EC

# --- hermetic fake-data checks (the CI gate) ------------------------------


def test_planted_edge_average_trade_is_correct() -> None:
    c = EC.check_planted_edge()
    lo, hi = c["pass_range"]
    assert c["passed"], c
    assert lo <= c["avg_trade"] <= hi
    # the planted 1% is visible: net-of-cost it lands near ~0.9%, well away
    # from the noise band.
    assert c["avg_trade"] > 0.005
    assert c["n_trades"] > 100  # plenty of flagged days to average


def test_pure_noise_average_trade_is_cost_only() -> None:
    c = EC.check_pure_noise()
    lo, hi = c["pass_range"]
    assert c["passed"], c
    assert lo <= c["avg_trade"] <= hi
    # nothing planted: the average is dominated by the two 0.05% cost legs
    # (about -0.1%), so it should sit at or below the noise floor.
    assert c["avg_trade"] < hi


def test_cheating_signal_is_caught_by_guard() -> None:
    c = EC.check_cheating_signal_caught()
    assert c["passed"], c
    assert "future data" in c.get("error", "")


def test_guard_raises_clean_error_when_signal_crashes_on_truncated_bars() -> None:
    # The reviewer's invariant (#1): a signal that only runs on full history is,
    # by definition, reaching forward -- whatever error it raises on a
    # truncated series. The specific error type is an artifact of how the
    # signal is written (IndexError / KeyError / ValueError), NOT a meaningful
    # distinction, so the guard must convert ALL of them into the one
    # documented LookupError the callers can actually catch.
    import backtest as B

    df, _ = EC.make_fake_bars(EC.SEED_EDGE)
    bars = B.Bars.from_dataframe(df)

    def _crash(b: B.Bars, day: int, exc, msg):
        """Each flavor raises the named ``exc`` only when truncated is too short."""
        if day + 1 < len(b):
            return "BUY"  # full-history path: a real decision
        raise exc(msg)  # truncated path: needs the future

    for exc, msg in (
        (IndexError, "single positional indexer is out-of-bounds"),
        (KeyError, "future bar not available"),
        (ValueError, "refusing to extrapolate beyond the last bar"),
    ):
        with pytest.raises(LookupError, match="signal uses future data"):
            B.check_signal(lambda b, d, _e=exc, _m=msg: _crash(b, d, _e, _m), bars)


def test_guard_cache_does_not_recheck_unchanged_signal():
    import backtest as B

    df, _ = EC.make_fake_bars(EC.SEED_EDGE)
    bars = B.Bars.from_dataframe(df)

    calls = {"n": 0}

    def sig(b: B.Bars, day: int):
        calls["n"] += 1
        return "X"

    B.check_signal(sig, bars)  # first check runs the guard (30 sig evals)
    after_first = calls["n"]
    assert after_first > 0
    B.check_signal(sig, bars)  # identical code+bars -> served from pass cache
    assert calls["n"] == after_first  # no further sig evaluations

    # A code change makes the cache key differ, so the guard must re-run.
    calls["n"] = 0

    def sig2(b: B.Bars, day: int):  # different source text -> different hash
        calls["n"] += 1
        return ("X",)

    B.check_signal(sig2, bars)
    assert calls["n"] > 0  # not served the previous pass


# --- real-data check (skipped when no research parquet is present) --------
@pytest.mark.skipif(
    not (ROOT / "data" / "prices.parquet").exists(),
    reason="research data (data/prices.parquet) not present in this environment",
)
def test_trend_switch_passes_guard_and_backtests() -> None:
    c = EC.check_trend_switch_passes()
    assert c["passed"], c
    assert c["trades"] >= 1
    assert c["max_drawdown"] < 0.5  # sane for a 200-day trend switch on SPY
