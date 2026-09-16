"""
RSI(2) mean-reversion signal detection for F&O option premium candles
(2026-09-16, explicit user choice after being asked which existing
strategy to wire first against kotak_fo_candle_feed.read_fo_candles_as_df's
own candle source - the first strategy to actually run on an option's own
premium data, not the underlying's price action).

Ported UNCHANGED from .github/workflows/swing-rsi2-mean-reversion-
research.yml's replay_symbol (Larry Connors' published 2-period RSI
mean-reversion system, originally tested there on DAILY bars of the
UNDERLYING's own price over a 2-year window) - same periods/thresholds
(TREND_SMA_N=200, RSI_N=2, RSI_ENTRY_MAX=10, RSI_EXIT_MIN=70, ATR_N=14,
ATR_STOP_MULT=2.0, MAX_HOLD_BARS=10), deliberately NOT retuned for the
different bar size (5-minute option-premium candles here, vs. daily
equity candles there) - reusing the validated logic exactly as chosen,
not quietly redesigning it for a new timeframe. Retuning periods to "fit
better" on new data without new validation evidence is exactly the kind
of blind parameter change this project's own standing discipline
prohibits (see CLAUDE.md).

IMPORTANT SCOPE NOTE, stated plainly: the original research workflow's
own comment already discloses this strategy has never been validated
against option premium data, only the underlying's own daily price -
this module is the FIRST time it's ever been pointed at a different
kind of series at all, on a completely different (5-min, tick-derived)
timeframe. No claim of edge is made here; this is live signal-DETECTION
plumbing (a "check the latest bar" shape, not a backtest replay), not a
validated production strategy. Real orders must not be placed from this
signal without a proper paper-trading validation period first, per this
session's standing plan.

MIN_LOOKBACK_BARS (205) is a real, binding constraint given
kotak_fo_candle_feed.py's own documented finding that individual F&O
contracts have short, discontinuous candle histories - most contracts
will likely never accumulate enough bars for this signal to ever
evaluate at all, let alone fire. That's an expected, disclosed
limitation of running a 200-period trend filter on data that resets
often, not a bug here.
"""
import numpy as np
import pandas as pd

TREND_SMA_N = 200
RSI_N = 2
RSI_ENTRY_MAX = 10.0
RSI_EXIT_MIN = 70.0
ATR_N = 14
ATR_STOP_MULT = 2.0
MAX_HOLD_BARS = 10

MIN_LOOKBACK_BARS = max(TREND_SMA_N, ATR_N, RSI_N) + 5


def _rsi(closes: np.ndarray, n: int) -> np.ndarray:
    """Exact port of the research workflow's own _rsi - Wilder-style
    smoothing via an EMA with alpha=1/n, not a simple rolling mean."""
    delta = np.diff(closes, prepend=closes[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    avg_loss = pd.Series(loss).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = np.where(avg_loss == 0, 100.0, rsi)
    return rsi


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int) -> np.ndarray:
    prev_close = np.concatenate(([np.nan], closes[:-1]))
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def rsi2_mean_reversion_entry_signal(df: pd.DataFrame) -> dict | None:
    """Checks ONLY the latest bar (df's last row) for an entry
    condition - a live "does this fire right now" check, not a backtest
    replay. Returns None if there isn't yet MIN_LOOKBACK_BARS of history,
    or if the entry condition isn't met at the latest bar; otherwise a
    dict with entry_price/stop_loss/rsi2/atr/entry_bar_ts for the caller
    to size, place, and later pass to rsi2_mean_reversion_exit_reason.
    `df` must be shaped like
    kotak_fo_candle_feed.read_fo_candles_as_df's own return value (Date/
    Open/High/Low/Close/Volume columns, oldest-first)."""
    n = len(df)
    if n < MIN_LOOKBACK_BARS:
        return None
    closes = df["Close"].to_numpy(dtype=float)
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)

    atr = _atr(highs, lows, closes, ATR_N)
    sma_trend = pd.Series(closes).rolling(TREND_SMA_N).mean().to_numpy()
    rsi2 = _rsi(closes, RSI_N)

    i = n - 1
    if np.isnan(atr[i]) or atr[i] <= 0 or np.isnan(sma_trend[i]):
        return None
    if closes[i] <= sma_trend[i]:
        return None  # trend filter: only mean-revert longs in an established uptrend
    if rsi2[i] >= RSI_ENTRY_MAX:
        return None

    entry_price = closes[i]
    stop_loss = entry_price - ATR_STOP_MULT * atr[i]
    if entry_price - stop_loss <= 0:
        return None
    return {
        "entry_price": float(entry_price), "stop_loss": float(stop_loss),
        "rsi2": float(rsi2[i]), "atr": float(atr[i]), "entry_bar_ts": df["Date"].iloc[i],
    }


def rsi2_mean_reversion_exit_reason(df: pd.DataFrame, entry_bar_ts, initial_stop: float) -> str | None:
    """Checks ONLY the latest bar for an exit condition on an already-
    open position, given its own entry_bar_ts (the value
    rsi2_mean_reversion_entry_signal returned as "entry_bar_ts") and
    initial_stop (frozen at entry, never trailed - same as the research
    workflow's own position["initial_stop"], which stays fixed for the
    life of the trade). Returns "stop_hit" / "rsi_reverted" /
    "max_hold_timeout", or None if no exit condition is met yet.

    held_bars is counted by ROW POSITION since entry_bar_ts (matching
    the original's index-difference math), not elapsed wall-clock time -
    a gap in this contract's own candle history (e.g. a re-subscribe
    after a universe refresh) shortens the effective bar count the same
    way a market holiday would in the original daily-bar version."""
    # Matched via pandas' own Series equality, not a raw numpy/np.datetime64
    # comparison - converting a tz-aware Timestamp through np.datetime64
    # silently drops its tzinfo and the comparison then never matches
    # anything (found while writing this function's own tests, not a
    # theoretical concern).
    entry_matches = df.index[df["Date"] == entry_bar_ts]
    if len(entry_matches) == 0:
        return None  # entry bar no longer in this contract's own history
    entry_idx = int(entry_matches[0])
    i = len(df) - 1
    if i <= entry_idx:
        return None

    closes = df["Close"].to_numpy(dtype=float)
    held_bars = i - entry_idx
    close_now = closes[i]
    rsi2 = _rsi(closes, RSI_N)

    if close_now <= initial_stop:
        return "stop_hit"
    if rsi2[i] > RSI_EXIT_MIN:
        return "rsi_reverted"
    if held_bars >= MAX_HOLD_BARS:
        return "max_hold_timeout"
    return None
