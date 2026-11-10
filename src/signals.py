"""Signals the backtester and the live bot share.

Adding a signal here means the backtest and the bot both call the same code,
so signal logic never lives in two places (house rules).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import Bars


class _SignalBase:
    """Common behaviour: guard hashing source + (bars, day) protocol."""

    def __call__(self, bars: Bars, day: int):
        raise NotImplementedError

    def source(self) -> str:
        return repr(self)


class TrendSwitch(_SignalBase):
    """The core's trend switch.

    At each close, hold the engine if it closes above its line, otherwise
    hold the safe asset. Every buy and sell fills at the next open (the
    backtester handles fills and cost).

    Settings (engine, safe asset, line length) come from config
    (``config/system.yaml``) in production; here they are explicit so the
    fake-bar checks can pass synthetic series without a config file.

    Parameters
    ----------
    close: the engine's close series (aligned with the bar index).
    safe_close: the safe asset's close series, same alignment. Used only by
        the backtester's marking / filling for the "safe asset" leg; the
        switch's *decision* only looks at the engine's close and line.
    line_length: length of the engine's simple moving average line.

    The decision is a pure function of the engine's close up to and
    including day ``day`` — so it passes the look-ahead guard.
    """

    def __init__(
        self,
        close: pd.Series,
        safe_close: pd.Series,
        line_length: int,
        engine: str = "ENGINE",
        safe_asset: str = "SAFE",
    ):
        self.close = close
        self.safe_close = safe_close
        self.line_length = int(line_length)
        self.engine = engine
        self.safe_asset = safe_asset
        # No line until we have a full window of data; the trend switch is
        # undefined (and therefore defaults to the safe asset) before that.
        self._line = close.rolling(
            self.line_length, min_periods=self.line_length
        ).mean()

    def __call__(self, bars: Bars, day: int):
        # The decision at close of day ``day``: previous close vs previous
        # line, following labels.uptrend_days (a day's own move never decides
        # its label). The fill happens at the open of day+1 (the backtester
        # does that).
        if day == 0:
            return self.safe_asset
        prev_close = float(self.close.iloc[day - 1])
        prev_line = self._line.iloc[day - 1]
        if prev_line is None or pd.isna(prev_line):
            return self.safe_asset
        return self.engine if prev_close >= float(prev_line) else self.safe_asset

    # The backtester needs to know which price series to mark/fill each leg.
    def prices(self) -> dict:
        return {self.engine: self.close, self.safe_asset: self.safe_close}

    def source(self) -> str:
        return (
            f"TrendSwitch(engine={self.engine!r}, safe_asset={self.safe_asset!r}, "
            f"line_length={self.line_length}, close={self.close.to_dict()!r})"
        )


class FlagSignal(_SignalBase):
    """Every flag close is its own trade.

    The prompt's test strategy: buy at the next open after every flagged
    close, sell at the open after that (holding for exactly one session
    beyond the entry). A flag that fires is a trade even when two overlap,
    so the backtester treats each flag as its own unit (see
    ``engine_check.py``: it uses the overlap path there).

    We implement it as a signal that returns the single fake asset on flagged
    days and ``None`` on others.
    """

    def __init__(self, flags: np.ndarray):
        self.flags = np.asarray(flags, dtype=bool)

    def __call__(self, bars: Bars, day: int):
        return "FAKE" if self.flags[day] else None
