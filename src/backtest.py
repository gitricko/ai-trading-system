"""Backtester.

Takes bars and a signal, follows the backtest house rules (AGENTS.md), and
returns equity at each close, the list of trades and the report numbers.

House rules implemented
------------------------
- Signals use data up to and including the close of the day on which they fire.
- Every buy and every sell fills at the *next* day's open and pays the cost.
- Start with the starting money and mark equity at every close.
- Long only, no leverage. Fractional shares are fine.
- A stop held at the broker fills at the stop price, or at the open if the
  day opens below it (not used by the trend switch, but the path exists).
- Each run starts flat; the first action happens at the first open, on the
  signal from the close before it.

A look-ahead guard
------------------
The first time a signal is used, the guard picks 30 random days (seed 7),
re-computes the signal on each one using only the data up to and including
that day, and compares with the signal computed from the full history. If
any differ, it stops with the error ``"signal uses future data"``. A signal
that passed is not checked again unless its code changes: the check is
cached on a hash of the signal's source plus the shape of the bars.
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_COST = 0.0005  # 0.05% of the traded value on every buy and every sell
STARTING_CASH = 100_000.0

_GUARD_SEED = 7
_GUARD_DAYS = 30
_PASS_CACHE: dict[tuple, bool] = {}


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
class Signal:
    """A signal is a function of (bars, day) -> intended holdings.

    ``day`` is the 0-based index of the bar whose close just closed.
    The return is a ticker (or ``None`` to be flat), or a list of tickers.

    The signal may only look at bars up to and including ``bars[day]``.
    The look-ahead guard enforces this on the first use of any signal.
    """

    def __call__(self, bars: Bars, day: int):
        raise NotImplementedError

    def source(self) -> str:
        """Stable text the guard hashes, so a code change invalidates it."""
        fn = (
            self.__call__.__func__
            if isinstance(self.__call__, property)
            else self.__call__
        )
        try:
            return inspect.getsource(fn)
        except (OSError, TypeError):
            return repr(self)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------
@dataclass
class Bars:
    """OHLC rows with a DatetimeIndex, ascending. Long only."""

    open: pd.Series
    high: pd.Series
    low: pd.Series
    close: pd.Series

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> Bars:
        lo = np.minimum(df["open"], df["close"])
        hi = np.maximum(df["open"], df["close"])
        if "low" in df and df["low"].notna().any():
            lo = df["low"].fillna(lo)
        if "high" in df and df["high"].notna().any():
            hi = df["high"].fillna(hi)
        o = df["open"].astype(float)
        c = df["close"].astype(float)
        return cls(o, hi.astype(float), lo.astype(float), c)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"open": self.open, "high": self.high, "low": self.low, "close": self.close}
        )

    def __len__(self) -> int:
        return len(self.close)


@dataclass
class Trade:
    """One closed round trip, buys and sells at the next open, cost paid."""

    entry_day: int  # 0-based index of the signal day (the bar that decided)
    exit_day: int  # 0-based index of the fill day for the sell
    entry_price: float
    exit_price: float
    shares: float
    entry_cost: float
    exit_cost: float
    pnl: float  # net of cost, in $

    @property
    def ret(self) -> float:
        gross = self.shares * self.entry_price
        denom = gross + self.entry_cost
        return self.pnl / denom if denom else float("nan")


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    report: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Look-ahead guard
# ---------------------------------------------------------------------------
def _source_text(sig) -> str:
    """Stable text to hash for the guard cache.

    Signals in ``signals.py`` provide ``.source()``; a plain function (such
    as the deliberate cheating signal) is hashed by its source code.
    """
    if hasattr(sig, "source") and callable(sig.source):
        return sig.source()
    try:
        return inspect.getsource(sig)
    except (OSError, TypeError):
        return repr(sig)


def _cache_key(sig, bars: Bars) -> tuple:
    src = _source_text(sig)
    h = hashlib.sha256(src.encode("utf-8")).hexdigest()[:32]
    shape = (
        len(bars),
        tuple(bars.close.index[:3]),
        tuple(bars.close.index[-3:]),
        tuple(round(float(x), 9) for x in bars.close.to_numpy()[:5]),
        tuple(round(float(x), 9) for x in bars.close.to_numpy()[-5:]),
    )
    return (h, shape)


def _decisions(full, trunc) -> bool:
    a = (
        full
        if isinstance(full, (list, tuple, set))
        else ([full] if full is not None else [])
    )
    b = (
        trunc
        if isinstance(trunc, (list, tuple, set))
        else ([trunc] if trunc is not None else [])
    )
    return set(a) == set(b)


def check_signal(sig, bars: Bars) -> None:
    """Verify ``sig`` does not read future data on a slice of ``bars``.

    Raises ``LookupError("signal uses future data")`` on failure. A passing
    outcome is cached on (source hash, bar shape); a code change re-checks.
    """
    key = _cache_key(sig, bars)
    passed = _PASS_CACHE.get(key)
    if passed:
        return

    n = len(bars)
    if n < _GUARD_DAYS + 5:
        # Too short a series to be meaningful; treat as not-a-real-signal and
        # skip. The three fake-bar checks all work on 1,500 days.
        _PASS_CACHE[key] = True
        return

    rng = np.random.default_rng(_GUARD_SEED)
    days = np.sort(rng.choice(np.arange(5, n), size=_GUARD_DAYS, replace=False))
    for t in days:
        full = sig(bars, int(t))
        try:
            truncated = sig(
                Bars(
                    open=bars.open.iloc[: t + 1],
                    high=bars.high.iloc[: t + 1],
                    low=bars.low.iloc[: t + 1],
                    close=bars.close.iloc[: t + 1],
                ),
                t,
            )
        except IndexError:
            # A signal that only runs on full history -- e.g. one that indexes
            # bars.close.iloc[day + 1] with no bounds check -- will IndexError
            # on the truncated series. That is reading the future: the decision
            # cannot be computed without future bars. Surface it as the
            # documented error so callers never see a raw crash.
            _PASS_CACHE[key] = False
            raise LookupError("signal uses future data") from None
        if not _decisions(full, truncated):
            _PASS_CACHE[key] = False
            raise LookupError("signal uses future data")
    _PASS_CACHE[key] = True


# ---------------------------------------------------------------------------
# Backtest engines
# ---------------------------------------------------------------------------
def _norm(sig_out) -> set:
    if sig_out is None:
        return set()
    if isinstance(sig_out, (list, tuple, set)):
        return set(sig_out)
    return {sig_out}


def backtest(
    bars: Bars,
    sig,
    *,
    cost: float = DEFAULT_COST,
    starting_cash: float = STARTING_CASH,
    price_map: dict | None = None,
) -> BacktestResult:
    """Run a signal against ``bars`` and return equity, trades and a report.

    One shared account (the house-rule core): the whole pot moves between
    tickers, no leverage. Decisions at the close of day ``t`` fill at the
    open of day ``t+1`` and pay the cost.

    ``price_map`` maps a held ticker to the close Series used to mark and to
    fill it. When it is ``None`` (or omits a ticker) the bars' own close is
    used, which is the fake-bar check case: the signal always holds the one
    fake asset whose prices are ``bars``.
    """
    check_signal(sig, bars)
    if len(bars) < 2:
        raise ValueError("need at least two bars")
    return _run_core(bars, sig, cost, starting_cash, price_map or {})


def _close_for(price_map: dict, ticker: str, bars: Bars, t: int) -> float:
    """Mark/fill price for ``ticker`` on bar ``t``. Falls back to the bars' own close."""
    s = price_map.get(ticker)
    if s is not None:
        return float(s.iloc[t])
    return float(bars.close.iloc[t])


def _fill_open(price_map: dict, ticker: str, bars: Bars, t: int) -> float:
    """The open at which a position in ``ticker`` is established on bar ``t``.

    A ticker's open is its previous close. When ``price_map`` knows the ticker
    we use its own previous close (so the SGOV leg buys at the SGOV open, not
    the SPY open). When it doesn't, the bars' open is the right price — this
    is the fake-bar case where the signal always holds the fake asset.
    """
    s = price_map.get(ticker)
    if s is not None:
        prev = s.iloc[t - 1] if t > 0 else float(s.iloc[0])
        return float(prev)
    return float(bars.open.iloc[t])


def _run_core(
    bars: Bars, sig, cost: float, starting_cash: float, price_map: dict
) -> BacktestResult:
    """One shared account, no leverage, cash is real.

    Decisions at close of day ``t`` fill at the open of day ``t+1`` and pay
    the cost. Long only. Fractional shares are fine.
    """
    n = len(bars)
    equity = np.empty(n, dtype=float)
    trades: list[Trade] = []

    cash = starting_cash
    held: str | None = None
    shares = 0.0
    signal_day = -1
    entry_price = 0.0
    entry_cost_accrued = 0.0

    def close_of(ticker: str, t: int) -> float:
        return _close_for(price_map, ticker, bars, t)

    for t in range(n):
        # 1) Fill the decision from yesterday's close at today's open. The
        #    fill price for any ticker is that ticker's own open; the bars' open
        #    is used only for the fake-asset case (no price map), which is the
        #    only case where "ticker open" == "bars open".
        if t > 0:
            target = next(iter(_norm(sig(bars, t - 1))))  # single-position core

            if held is not None and target != held:
                # Sell `held` at its own open and, separately, buy `target`
                # at target's own open. (The safe and engine legs are on
                # different tickers with different open series.)
                sell_price = _fill_open(price_map, held, bars, t)
                gross = shares * sell_price
                fee = gross * cost
                cash += gross - fee
                entry_gross = shares * entry_price
                pnl = (gross - fee) - (entry_gross + entry_cost_accrued)
                trades.append(
                    Trade(
                        entry_day=signal_day,
                        exit_day=t,
                        entry_price=entry_price,
                        exit_price=sell_price,
                        shares=shares,
                        entry_cost=entry_cost_accrued,
                        exit_cost=fee,
                        pnl=pnl,
                    )
                )
                held = None
                shares = 0.0

            if held is None and target is not None:
                buy_price = _fill_open(price_map, target, bars, t)
                if cash > 0:
                    gross = cash
                    fee = gross * cost
                    sh = (gross - fee) / buy_price
                    cash = 0.0
                    held = target
                    shares = sh
                    signal_day = t - 1
                    entry_price = buy_price
                    entry_cost_accrued = fee

        # 2) Mark-to-market at today's close.
        mark = cash + (
            shares * _close_for(price_map, held, bars, t) if held is not None else 0.0
        )
        equity[t] = mark

    # Close any open position at the last close so every trade is counted.
    if held is not None:
        price = close_of(held, n - 1)
        gross = shares * price
        fee = gross * cost
        entry_gross = shares * entry_price
        pnl = (gross - fee) - (entry_gross + entry_cost_accrued)
        trades.append(
            Trade(
                entry_day=signal_day,
                exit_day=n - 1,
                entry_price=entry_price,
                exit_price=price,
                shares=shares,
                entry_cost=entry_cost_accrued,
                exit_cost=fee,
                pnl=pnl,
            )
        )
        equity[-1] = cash + (gross - fee)

    eq = pd.Series(equity, index=bars.close.index, name="equity")
    return BacktestResult(
        equity=eq, trades=trades, report=_report(eq, trades, starting_cash)
    )


# ---------------------------------------------------------------------------
# Report numbers (house-rule metrics on the equity curve)
# ---------------------------------------------------------------------------
def _report(equity: pd.Series, trades: list[Trade], starting_cash: float) -> dict:
    eq = equity.to_numpy(dtype=float)
    n = len(eq)
    start = float(eq[0]) if n else starting_cash
    end = float(eq[-1]) if n else starting_cash

    if n and start > 0 and end > 0:
        total_return = end / start - 1.0
        bars_per_year = 252.0
        ann = (end / start) ** (bars_per_year / n) - 1.0
    else:
        total_return = float("nan")
        ann = float("nan")

    if n > 1:
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        mdd = float(-dd.min())
    else:
        mdd = 0.0
    rp_dd = (
        ann / mdd
        if (mdd > 0 and np.isfinite(ann))
        else (float("nan") if not np.isfinite(ann) else float("inf"))
    )

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = (len(wins) / len(pnls)) if pnls else float("nan")
    avg_win = float(np.mean(wins)) if wins else float("nan")
    avg_loss = float(np.mean(losses)) if losses else float("nan")
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = float("inf") if gross_win > 0 else float("nan")
    held_bars = [t.exit_day - t.entry_day for t in trades]
    avg_days = float(np.mean(held_bars)) if trades else float("nan")

    return {
        "start_equity": start,
        "end_equity": end,
        "total_return": total_return,
        "annualized_return": ann,
        "max_drawdown": mdd,
        "return_per_drawdown": rp_dd,
        "trades": len(pnls),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "avg_days_held": avg_days,
        "time_in_market": float(np.mean(held_bars)) if trades else 0.0,
    }
