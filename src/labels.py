"""Shared label code. Every later prompt uses these, so label logic lives in exactly one place."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

BARS_PER_YEAR = 252  # daily bars; for another bar size, bars in 252 trading days

# Defaults from the house rules "My settings". The quarterly re-pick reuses these
# functions with a different window and different event minimums.
DEFAULT_MIN_EVENTS_KEEPS_GOING = 6
DEFAULT_MIN_EVENTS_SNAPS_BACK = 12


# ---------------------------------------------------------------------------
# indicators
# ---------------------------------------------------------------------------


def sma(close: pd.Series, length: int) -> pd.Series:
    """Simple moving average of the close."""
    return close.rolling(length, min_periods=length).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    """RSI with Wilder's smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0.0, 100.0)
    flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    if int(flat.sum()):
        out = out.mask(flat, 50.0)
    return out


def wilder_rsi2(close: pd.Series) -> pd.Series:
    """RSI(2): the 2-period RSI with Wilder's smoothing."""
    return rsi(close, 2)


def is_above_line(close: pd.Series, line_length: int) -> pd.Series[bool]:
    """A ticker is above its line when that day's close is above that day's line."""
    line = sma(close, line_length)
    return close > line


def uptrend_days(close: pd.Series, line_length: int) -> pd.Series[bool]:
    """Uptrend day: a day whose previous close was above the previous day's line.

    A day's own move never decides its label.
    """
    return is_above_line(close, line_length).shift(1, fill_value=False)


def realized_vol(
    close: pd.Series, window: int, bars_per_year: int = BARS_PER_YEAR
) -> pd.Series:
    """Rolling annualized volatility: stdev of the last `window` returns * sqrt(bars per year)."""
    ret = close.pct_change()
    return ret.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(bars_per_year)


def wild_days(
    close: pd.Series, window: int = 20, median_span: int = 252
) -> pd.Series[bool]:
    """Wild day: 20-day volatility above its own median over the previous 252 days.

    "Previous" means the 252 strictly older observations, so the current value is excluded.
    """
    vol = realized_vol(close, window)
    median = vol.shift(1).rolling(median_span, min_periods=median_span).median()
    return vol > median


# ---------------------------------------------------------------------------
# return measures (as defined in "What words mean")
# ---------------------------------------------------------------------------


def forward_returns(close: pd.Series, n: int) -> pd.Series:
    """Return from today's close to the close n bars later, per calendar day of the series."""
    fwd = close.shift(-n) / close - 1.0
    idx = close.index
    mask = (
        idx >= close.dropna().index[min(n, len(idx) - 1)]
        if len(idx) > n
        else idx >= idx[-(len(idx) - n)]
    )
    return fwd[mask]


def annualized_return_of_days(
    close: pd.Series, day_mask: pd.Series, bars_per_year: int = BARS_PER_YEAR
) -> float | None:
    """Average close-to-close return of a set of days, times bars per year."""
    ret = close.pct_change()
    m = day_mask & ret.notna()
    if int(m.sum()) == 0:
        return None
    return float(ret[m].mean() * bars_per_year)


def annualized(
    total_multiple: float, n_bars: int, bars_per_year: int = BARS_PER_YEAR
) -> float:
    """(ending equity / starting equity) to the power of (bars per year / the run's bars), minus 1."""
    return float(total_multiple ** (bars_per_year / n_bars) - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    """Largest fall from a peak in equity, using the series as given (closes)."""
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(-dd.min())


# ---------------------------------------------------------------------------
# the three labels
# ---------------------------------------------------------------------------


def _pos(c: pd.Series, window: tuple, holding_bars: int):
    """Positional booleans inside the outer window: in-window and end-inside-window."""
    w0, w1 = (
        np.datetime64(pd.Timestamp(window[0])),
        np.datetime64(pd.Timestamp(window[1])),
    )
    idx = np.asarray(c.index, dtype="datetime64[ns]")
    in_window = (idx >= w0) & (idx <= w1)
    end_ok = np.zeros(len(idx), dtype=bool)
    if len(idx) > holding_bars:
        end_ok[: len(idx) - holding_bars] = idx[holding_bars:] <= w1
    return in_window, end_ok


@dataclass
class KeepsGoing:
    label: bool
    excess: (
        float | None
    )  # average 20-day event return minus the average of every 20-day return in the window
    events: int
    min_events: int


@dataclass
class SnapsBack:
    label: bool
    excess: float | None
    events: int
    min_events: int


@dataclass
class HoldsUp:
    label: bool
    return_on_downtrend_days: float | None
    cash_return_on_downtrend_days: float | None
    correlation_with_market: float | None
    correlation_limit: float


def keeps_going(
    close: pd.Series,
    line_length: int,
    window: tuple,  # (start, end) dates, both inclusive of that day's bar
    holding_bars: int = 20,
    min_event_gap_bars: int = 20,
    min_events: int = DEFAULT_MIN_EVENTS_KEEPS_GOING,
    bars_per_year: int = BARS_PER_YEAR,
) -> KeepsGoing:
    """Every close that is the highest close of the last 50 days (counting that day) while
    above its line, at least `min_event_gap_bars` after the last kept event, and whose next
    `holding_bars` days end inside the window. Labelled if the excess return is positive
    with at least `min_events` events."""
    in_window, end_ok = _pos(close, window, holding_bars)
    cvals = close.to_numpy(float)
    line_ok = is_above_line(close, line_length).to_numpy()
    rolling_max = close.rolling(50, min_periods=1).max().to_numpy()
    base = in_window & line_ok & (cvals >= rolling_max) & end_ok

    events = []
    last_kept = None
    for i in np.where(base)[0]:
        if last_kept is not None and (i - last_kept) < min_event_gap_bars:
            continue
        last_kept = i
        events.append(i)

    excess = None
    if events:
        avg_event = float(
            np.mean([cvals[i + holding_bars] / cvals[i] - 1.0 for i in events])
        )
        base_rate = float(
            np.mean(
                [
                    cvals[i + holding_bars] / cvals[i] - 1.0
                    for i in np.where(in_window & end_ok)[0]
                ]
            )
        )
        excess = avg_event - base_rate
    n = len(events)
    return KeepsGoing(
        label=bool(excess is not None and excess > 0 and n >= min_events),
        excess=excess,
        events=n,
        min_events=min_events,
    )


def snaps_back(
    close: pd.Series,
    line_length: int,
    window: tuple,
    holding_bars: int = 5,
    min_event_gap_bars: int = 5,
    rsi_below: float = 10.0,
    side: str = "above",  # "above" or "below" its line
    min_events: int = DEFAULT_MIN_EVENTS_SNAPS_BACK,
) -> SnapsBack:
    """Every close with RSI(2) below `rsi_below` while `side` its line, at least
    `min_event_gap_bars` after the last kept event, and whose next `holding_bars` days end
    inside the window. Labelled if the excess return is positive with at least `min_events`."""
    in_window, end_ok = _pos(close, window, holding_bars)
    c = close
    line_state = is_above_line(c, line_length).to_numpy()
    if side == "above":
        cond = line_state
    elif side == "below":
        cond = ~line_state
    else:
        raise ValueError("side must be 'above' or 'below'")
    r = wilder_rsi2(c).to_numpy()
    base = in_window & cond & (~np.isnan(r)) & (r < rsi_below) & end_ok

    events = []
    last_kept = None
    for i in np.where(base)[0]:
        if last_kept is not None and (i - last_kept) < min_event_gap_bars:
            continue
        last_kept = i
        events.append(i)

    excess = None
    if events:
        cvals = c.to_numpy(float)
        avg_event = float(
            np.mean([cvals[i + holding_bars] / cvals[i] - 1.0 for i in events])
        )
        base_rate = float(
            np.mean(
                [
                    cvals[i + holding_bars] / cvals[i] - 1.0
                    for i in np.where(in_window & end_ok)[0]
                ]
            )
        )
        excess = avg_event - base_rate
    n = len(events)
    return SnapsBack(
        label=bool(excess is not None and excess > 0 and n >= min_events),
        excess=excess,
        events=n,
        min_events=min_events,
    )


def holds_up(
    close: pd.Series,
    market_close: pd.Series,
    cash_close: pd.Series,
    line_length_market: int,
    window: tuple,
    correlation_limit: float = 0.5,
    bars_per_year: int = BARS_PER_YEAR,
) -> HoldsUp:
    """Annualized return on the market ticker's downtrend days beats the cash ticker's,
    and daily correlation with the market ticker is below `correlation_limit`."""
    w0, w1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    idx = close.index
    in_window = (idx >= w0) & (idx <= w1)

    # the market ticker's downtrend days, as a set of dates (its own bars)
    down_days = set(
        market_close.index[~uptrend_days(market_close, line_length_market).to_numpy()]
    )

    # ticker measured on its own bars, only on dates that are market downtrend days
    m = in_window & pd.Series(np.array([d in down_days for d in idx]), index=idx)
    ret = close.pct_change()
    t_ret = float(ret[m].mean() * bars_per_year) if int(m.sum()) else None

    ci = cash_close.index
    cmask = (
        (ci >= w0)
        & (ci <= w1)
        & pd.Series(np.array([d in down_days for d in ci]), index=ci)
    )
    c_ret = (
        float(cash_close.pct_change()[cmask].mean() * bars_per_year)
        if int(cmask.sum())
        else None
    )

    # daily correlation with the market ticker, on days both traded
    a = close.index.intersection(market_close.index)
    ca = close.loc[a].pct_change()
    cb = market_close.loc[a].pct_change()
    corr = float(ca.corr(cb))

    return HoldsUp(
        label=bool(
            t_ret is not None
            and c_ret is not None
            and t_ret > c_ret
            and corr is not None
            and corr < correlation_limit
        ),
        return_on_downtrend_days=t_ret,
        cash_return_on_downtrend_days=c_ret,
        correlation_with_market=corr,
        correlation_limit=correlation_limit,
    )
