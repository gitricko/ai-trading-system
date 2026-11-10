"""Download and reuse research data from Yahoo Finance.

House rules:
- Research data lives in data/prices.parquet and stops at the end date in the
  settings, so results never change. Reuse it and only download tickers it
  doesn't have yet.
- After every download, print the rows, first date, last date and any missing
  days for each ticker.
- The live bot never writes here.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PARQUET = PROJECT_ROOT / "data" / "prices.parquet"

# --- settings (from CLAUDE.md, "My settings") ---
START_DATE = "2020-07-01"
END_DATE = "2026-10-23"  # inclusive
# yfinance treats the end date as exclusive, so pass the day after:
_DOWNLOAD_END = "2026-10-24"

STUDY_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
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
    "TLT",
    "IEF",
    "SHY",
    "SGOV",
    "GLD",
    "SLV",
    "USO",
    "DBC",
    "TQQQ",
    "SQQQ",
    "BTC-USD",
]

TRAIN_WINDOW = ("2022-01-03", "2024-12-31")
LOCKED_TEST_WINDOW = ("2025-01-02", "2026-10-23")

MARKET_TICKER = "SPY"
CASH_TICKER = "SGOV"
LINE_LENGTH = 200  # the 200-day line


def ensure_data(tickers: list[str] | None = None) -> pd.DataFrame:
    """Return a dict-of-Series frame of adjusted closes for the needed tickers.

    Reuses data/prices.parquet and only downloads tickers it doesn't have.
    """
    tickers = tickers or STUDY_TICKERS
    have: dict[str, pd.Series] = {}
    if DATA_PARQUET.exists():
        stored = pd.read_parquet(DATA_PARQUET)
        # stored is either a dict of series or a single-ticker frame
        if stored.shape[1] == 1:
            stored = stored.rename(columns={stored.columns[0]: tickers[0]})
        have = {c: stored[c].dropna() for c in stored.columns}

    missing = [t for t in tickers if t not in have or len(have[t]) == 0]
    if missing:
        print(f"downloading {len(missing)} ticker(s): {', '.join(missing)}")
        for i, t in enumerate(missing):
            close = None
            for attempt in range(3):
                df = yf.download(
                    t,
                    start=START_DATE,
                    end=_DOWNLOAD_END,
                    auto_adjust=True,
                    progress=False,
                )
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        s = df["Close"][t]
                    else:
                        s = df["Close"]
                    s = s.dropna()
                    s.index = (
                        s.index.tz_localize(None) if s.index.tz is not None else s.index
                    )
                    close = s
                    break
                time.sleep(1.0)
            if close is None:
                print(f"  {t}: NO DATA after 3 attempts")
                have[t] = pd.Series(dtype=float)
                continue
            have[t] = close
            if i < len(missing) - 1:
                time.sleep(0.5)

        # The stored parquet is frozen research data: it can grow (new
        # tickers) but never shrink, and it is written atomically so an
        # interrupted run can never leave a truncated file behind.
        DATA_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        save = {k: v for k, v in have.items() if len(v) > 0}
        if DATA_PARQUET.exists():
            stored_cols = set(pd.read_parquet(DATA_PARQUET).columns)
            dropped = sorted(stored_cols - save.keys())
            if dropped:
                raise RuntimeError(
                    "refusing to shrink the frozen research data; "
                    f"stored columns missing from the save set: {dropped}"
                )
        tmp = DATA_PARQUET.with_suffix(".parquet.tmp")
        pd.DataFrame(save)[sorted(save)].to_parquet(tmp)
        tmp.replace(DATA_PARQUET)
        n_empty = [t for t in missing if t not in save]
        if n_empty:
            print(f"  empty (not saved): {', '.join(n_empty)}")

    out = {t: have[t] for t in tickers if t in have and len(have[t]) > 0}
    missing_now = [t for t in tickers if t not in out]
    for t in missing_now:
        print(f"WARNING: no data at all for {t}")
    return out


def report(close: pd.Series, market_close: pd.Series | None = None) -> None:
    """Print rows, first date, last date and any missing days for one ticker.

    Missing days = days the market ticker (SPY) traded while this ticker has no bar.
    For tickers that trade on days the market doesn't (e.g. BTC-USD on weekends),
    those extra days are not counted as missing.
    """
    if close is None or close.empty:
        return
    first, last = close.index[0], close.index[-1]
    if market_close is not None:
        market_days = set(market_close.loc[close.index[0] : close.index[-1]].index)
        missing_days = sorted(market_days - set(close.index))
    else:
        missing_days = []
    print(
        f"{close.name if close.name else '?':>8}: rows={len(close):5d}  "
        f"first={first.date()}  last={last.date()}  missing_days={len(missing_days)}"
        + (
            f"  {missing_days[:10]}{' ...' if len(missing_days) > 10 else ''}"
            if missing_days
            else ""
        )
    )


def load_all(tickers: list[str] | None = None) -> dict[str, pd.Series]:
    """Download if needed, print the per-ticker report, and return a dict
    ticker -> adjusted close series on its own bars (no NaN padding)."""
    closes = ensure_data(tickers)
    market = closes.get(MARKET_TICKER)
    for t in STUDY_TICKERS if tickers is None else tickers:
        if t in closes:
            report(closes[t], market if t != MARKET_TICKER else None)
    return closes
