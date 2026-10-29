"""Shared live resting-stop model for the swing main.py replays (backlog B-1417, generalising B-1413).

Kotak can only rest a stop inside the stock's daily price band. A SELL stop below the widest (10%) band floor is
raised to prev_close x 0.9 x 1.003 before it is sent (kotak_real_orders._preclamp_long_stop, B-1411); a BUY stop
for a short above the 10% ceiling is lowered to prev_close x 1.1 x 0.997 (_preclamp_short_stop). The resting order
then triggers INTRADAY on the bar's low (long) / high (short) and fills at the worse of the open and the trigger.

band_cap modes:
  off   (default) the replay is unchanged: no resting-stop check at all, existing results stay bit-identical.
  live  resting stop = max(strategy stop, band floor) for a long, min(strategy stop, band ceiling) for a short,
        checked intraday from the bar AFTER the entry bar, BEFORE the strategy's own (often close-based) exit runs.
"prev close" is the previous SESSION's close (the last bar of the previous date), so intraday bars (1h macddiv) use
the daily band exactly as Kotak does, not the previous hourly bar.
"""
import os

import numpy as np

BAND_PCT = 0.10      # == kotak_real_orders._PRICE_BAND_PCTS[0] (asserted in tests/test_swing_bandcap_b1417.py)
BAND_PAD = 0.003     # the 0.3% inside-the-band pad used by _preclamp_long_stop / _preclamp_short_stop
MODES = ("off", "live")
BAND_PARAM = "rsbandfloor"  # same param token B-1413 used for its band-live registry tags


def normalize_mode(mode) -> str:
    m = (mode or "off").strip().lower()
    if m in ("", "none", "0", "false", "baseline"):
        m = "off"
    if m not in MODES:
        raise SystemExit(f"bad band_cap {mode!r}: expected one of {MODES}")
    return m


def mode_from_env(env=None) -> str:
    e = os.environ if env is None else env
    return normalize_mode(e.get("BAND_CAP"))


def band_floor(prev_close: float) -> float:
    """Lowest SELL stop Kotak accepts for a long (10% band floor, padded inside)."""
    return float(prev_close) * (1.0 - BAND_PCT) * (1.0 + BAND_PAD)


def band_ceiling(prev_close: float) -> float:
    """Highest BUY stop Kotak accepts for a short (10% band ceiling, padded inside)."""
    return float(prev_close) * (1.0 + BAND_PCT) * (1.0 - BAND_PAD)


def resting_trigger(strat_stop: float, prev_close: float, side: str = "long"):
    """(trigger, band_bound) of the stop Kotak actually rests. band_bound is True when the band, not the strategy,
    set the level (the strategy stop lies outside the band)."""
    if side == "long":
        fl = band_floor(prev_close)
        return (fl, True) if fl > float(strat_stop) else (float(strat_stop), False)
    ce = band_ceiling(prev_close)
    return (ce, True) if ce < float(strat_stop) else (float(strat_stop), False)


def resting_stop_exit(mode, side, strat_stop, prev_close, bar_open, bar_low, bar_high):
    """None when off / no prev close / not triggered; else (fill_price, reason). Long: triggered when low <= trigger,
    filled at min(open, trigger) (a gap below fills at the open). Short mirror on the high."""
    if normalize_mode(mode) == "off" or prev_close is None or not np.isfinite(prev_close) or prev_close <= 0:
        return None
    if strat_stop is None or not np.isfinite(strat_stop):
        return None
    trig, banded = resting_trigger(strat_stop, prev_close, side)
    why = "band_floor_stop_hit" if banded else "resting_stop_hit"
    if side == "long":
        if bar_low <= trig:
            return float(min(bar_open, trig)), why
        return None
    if bar_high >= trig:
        return float(max(bar_open, trig)), why
    return None


def prev_session_close(df) -> np.ndarray:
    """Per bar, the close of the last bar of the PREVIOUS session date (NaN for the first session). For 1d bars this
    is closes[i-1]; for intraday bars it is yesterday's last close, i.e. the reference of the exchange band."""
    closes = df["Close"].to_numpy(dtype=float)
    if "Date" in df.columns:
        days = df["Date"].astype(str).str[:10].to_numpy()
    else:
        import pandas as pd
        days = pd.DatetimeIndex(df.index).strftime("%Y-%m-%d").to_numpy()
    out = np.full(len(closes), np.nan)
    last_prev = np.nan
    for i in range(len(closes)):
        if i > 0 and days[i] != days[i - 1]:
            last_prev = closes[i - 1]
        out[i] = last_prev
    return out


def band_tag(tag: str, mode) -> str:
    """off -> tag unchanged. live -> the same tag with the `rsbandfloor` param inserted alphabetically into the params
    field (naming grammar: family__variant__dir__tf__params__...), a NEW tag, never a rename. A legacy tag without the
    grammar (gap_and_go, power_play, primary_base) gets `__rsbandfloor` appended."""
    if normalize_mode(mode) == "off":
        return tag
    parts = tag.split("__")
    if len(parts) >= 6:
        toks = [t for t in parts[4].split("_") if t]
        if BAND_PARAM not in toks:
            pos = next((k for k, t in enumerate(toks) if t > BAND_PARAM), len(toks))
            toks.insert(pos, BAND_PARAM)
        parts[4] = "_".join(toks)
        return "__".join(parts)
    return f"{tag}__{BAND_PARAM}"


class MemoMain:
    """Wraps the imported main module so a pure entry function evaluated at the same bar of the same symbol is computed
    once and shared by the off and live passes (their positions differ, the signal at bar k does not). Call reset() per
    symbol. Every other attribute passes straight through to the real module."""

    def __init__(self, module, names):
        self._m = module
        self._names = set(names)
        self._cache = {}

    def reset(self):
        self._cache.clear()

    def __getattr__(self, name):
        attr = getattr(self._m, name)
        if name not in self._names or not callable(attr):
            return attr

        def wrapped(df, *args, **kw):
            key = (name, len(df), df.index[-1] if len(df) else None, args, tuple(sorted(kw.items())))
            if key not in self._cache:
                self._cache[key] = attr(df, *args, **kw)
            return self._cache[key]
        return wrapped
