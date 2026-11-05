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
BAND_PARAM = "rsbandfloor"  # same param token B-1413 used for its band-live registry tags
# B-1484 (user 2026-11-05: "backtest different TRAILING SL rules on each wired FIXED SL strategy; wire the trail only if
# it beats the fixed one"): live_<trail> modes = the live resting-stop model above PLUS a trailing stop that only ever
# RAISES the strategy's frozen stop (long; LOWERS it for a short). R = |entry - initial stop|. The peak is the best
# PREVIOUS-SESSION close since entry (the same daily-close running max the live swing engine stores), so no look-ahead:
#   trN   stop = max(stop0, peak - N x R)                       (chandelier in R units; N=1 ratchets from the first gain)
#   beN   stop = max(stop0, entry x (1 + cost)) once peak >= entry + N x R   (net breakeven, cost = 0.8% round trip)
#   ltN   (B-1484 b, user: "trailing SL can be 0.5R, 1.0R ... multiplied by LTP checked recently") stop = max(stop0,
#         peak LTP - N x R), peak LTP = the highest HIGH of the bars already completed since entry (the price the live
#         per-tick LTP trail would have seen; the current bar's own high is never used, so no look-ahead)
TRAIL_RULES = {"tr0d5": ("chand", 0.5), "tr1": ("chand", 1.0), "tr1d5": ("chand", 1.5), "tr2": ("chand", 2.0),
               "tr3": ("chand", 3.0), "be1": ("be", 1.0), "be2": ("be", 2.0),
               "lt0d5": ("ltp", 0.5), "lt1": ("ltp", 1.0), "lt1d5": ("ltp", 1.5), "lt2": ("ltp", 2.0)}
TRAIL_PARAM = {"tr0d5": "trailr0d5", "tr1": "trailr1", "tr1d5": "trailr1d5", "tr2": "trailr2", "tr3": "trailr3",
               "be1": "trailbe1r", "be2": "trailbe2r",
               "lt0d5": "trailltp0d5r", "lt1": "trailltp1r", "lt1d5": "trailltp1d5r", "lt2": "trailltp2r"}
TRAIL_MODES = tuple(f"live_{k}" for k in TRAIL_RULES)
MODES = ("off", "live") + TRAIL_MODES
BE_COST = 0.008  # == main.ROUND_TRIP_COST_PCT / 100 (asserted in tests/test_swing_trail_overlay_b1484.py)
_TRAIL_STATE: dict = {}  # (side, entry) -> {"stop0", "first_prev", "peak"}; reset_trail() before every replay pass


def reset_trail():
    _TRAIL_STATE.clear()


def trail_rule(mode):
    m = normalize_mode(mode)
    return TRAIL_RULES[m[5:]] if m.startswith("live_") else None


def trailed_stop(mode, side, strat_stop, prev_close, entry_price, bar_high=None, bar_low=None):
    """The strategy stop raised (long) / lowered (short) by the trail rule of a live_<trail> mode; strat_stop unchanged
    otherwise. Stateful per trade, keyed by (side, entry price); the FIRST prev_close seen for a trade is never used (on
    1h bars it is the session before the entry day, on daily bars it is the entry bar itself and the peak starts at the
    entry price anyway), so the trail can only lag, never look ahead."""
    rule = trail_rule(mode)
    if rule is None:
        return strat_stop
    if entry_price is None or not np.isfinite(entry_price) or entry_price <= 0:
        raise ValueError(f"trail mode {mode!r} needs the trade's entry_price")
    ep = float(entry_price)
    key = (side, round(ep, 8))
    st = _TRAIL_STATE.get(key)
    if st is None:
        st = _TRAIL_STATE[key] = {"stop0": float(strat_stop), "first_prev": prev_close, "peak": ep, "pk_ltp": ep,
                                  "pend_hi": None, "pend_lo": None}
    else:
        if prev_close is not None and np.isfinite(prev_close) and prev_close != st["first_prev"]:
            st["peak"] = max(st["peak"], float(prev_close)) if side == "long" else min(st["peak"], float(prev_close))
        # the PREVIOUS call's bar is complete now: its high (long) / low (short) joins the peak LTP
        if side == "long" and st["pend_hi"] is not None:
            st["pk_ltp"] = max(st["pk_ltp"], st["pend_hi"])
        if side != "long" and st["pend_lo"] is not None:
            st["pk_ltp"] = min(st["pk_ltp"], st["pend_lo"])
    st["pend_hi"] = float(bar_high) if bar_high is not None and np.isfinite(bar_high) else None
    st["pend_lo"] = float(bar_low) if bar_low is not None and np.isfinite(bar_low) else None
    r = abs(ep - st["stop0"])
    if r <= 0:
        return strat_stop
    kind, nmul = rule
    if kind == "ltp":
        kind, st = "chand", dict(st, peak=st["pk_ltp"])
    if side == "long":
        lvl = st["peak"] - nmul * r if kind == "chand" else (ep * (1 + BE_COST) if st["peak"] >= ep + nmul * r else None)
        return float(strat_stop) if lvl is None else max(float(strat_stop), lvl)
    lvl = st["peak"] + nmul * r if kind == "chand" else (ep * (1 - BE_COST) if st["peak"] <= ep - nmul * r else None)
    return float(strat_stop) if lvl is None else min(float(strat_stop), lvl)


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


def resting_stop_exit(mode, side, strat_stop, prev_close, bar_open, bar_low, bar_high, entry_price=None):
    """None when off / no prev close / not triggered; else (fill_price, reason). Long: triggered when low <= trigger,
    filled at min(open, trigger) (a gap below fills at the open). Short mirror on the high. B-1484: a live_<trail> mode
    first applies trailed_stop (needs entry_price); reason trail_stop_hit when the trail set the level."""
    if normalize_mode(mode) == "off" or prev_close is None or not np.isfinite(prev_close) or prev_close <= 0:
        return None
    if strat_stop is None or not np.isfinite(strat_stop):
        return None
    eff = trailed_stop(mode, side, strat_stop, prev_close, entry_price, bar_high, bar_low)
    trailed = eff != float(strat_stop)
    trig, banded = resting_trigger(eff, prev_close, side)
    why = "band_floor_stop_hit" if banded else ("trail_stop_hit" if trailed else "resting_stop_hit")
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


def make_band(df, mode):
    """B-1426: (mode, prev_session_close array) when mode is live, else None (off: the replay is unchanged). Build it
    on the SAME reset-index frame the replay walks."""
    return (normalize_mode(mode), prev_session_close(df)) if normalize_mode(mode) != "off" else None


def band_hit(band, df, j, strat_stop, side="long", entry_price=None):
    """B-1426: resting_stop_exit on bar j of df for a make_band() context; None when band is None (off)."""
    if band is None:
        return None
    return resting_stop_exit(band[0], side, strat_stop, band[1][j], float(df["Open"].iloc[j]),
                             float(df["Low"].iloc[j]), float(df["High"].iloc[j]), entry_price)


def band_tag(tag: str, mode) -> str:
    """off -> tag unchanged. live -> the same tag with the `rsbandfloor` param inserted alphabetically into the params
    field (naming grammar: family__variant__dir__tf__params__...), a NEW tag, never a rename. A legacy tag without the
    grammar (gap_and_go, power_play, primary_base) gets `__rsbandfloor` appended."""
    m = normalize_mode(mode)
    if m == "off":
        return tag
    new = [BAND_PARAM] + ([TRAIL_PARAM[m[5:]]] if m.startswith("live_") else [])
    parts = tag.split("__")
    if len(parts) >= 6:
        toks = [t for t in parts[4].split("_") if t]
        for p in new:  # B-1484: the trail token joins rsbandfloor, alphabetically, as a NEW tag
            if p not in toks:
                pos = next((k for k, t in enumerate(toks) if t > p), len(toks))
                toks.insert(pos, p)
        parts[4] = "_".join(toks)
        return "__".join(parts)
    return tag + "".join(f"__{p}" for p in new)


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
