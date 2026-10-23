"""B-1210: inverted-cup "3C cheat" SHORT mirror, a pattern_lab-independent RESEARCH rule (not in main.py yet).

pattern_lab's r_bases has no short side for base_cup_cheat_3c. This is the definitional mirror, written here from scratch
(it imports neither pattern_lab nor main): run the long rule on the RECIPROCAL series (H' = 1/L, L' = 1/H, C' = 1/C), so a
dome (inverted cup) with a tight pause below the recovery level and a close BELOW the pause low triggers a short.
Reciprocal (not negative) prices keep every ratio threshold (depth 15-35%, 0.95 rim, 12% handle, 10% pause, mid +/- band)
symmetric in log space; a plain sign flip would break the ratios. Stop = entry + k x ATR14 (simple mean), ALWAYS defined
(no trade without SL). Entry convention as the long port: signal close. Own tag family
`base__cup_cheat_3c__short__1h__atr<k>_h<N>__v1`; NOT registered or ported until a main.py function + full-universe replay exist
(owed, backlog B-1210). Rule constants are the long rule's, verbatim.

B-1190/B-1210 (2026-10-23 IST): DataFrame wrappers for the full-universe short replay (scripts/cup_cheat_main_replay.py with
DIRECTION=short). main.py has NO short cup-cheat function, so that replay is RESEARCH-SIDE: entry = cup_cheat_short_entry_signal
(sell short at the signal close, buy-to-cover stop = entry + k x ATR14, always above entry), exit = cup_cheat_short_exit_reason,
the exact mirror of main.cup_cheat_3c_exit_reason (gap-aware stop: fill bar at the stop, later bars at max(stop, open); else the
close of the hold-th bar). The long rule has no fixed profit target (timeout-only upside), so neither does the mirror. Same 9
cells as main.CUP_CHEAT_1H_CELLS (ATR 2.5/4/6 x hold 6/18/30), own tags with dir=short.
"""
import numpy as np

MIN_BARS = 71
CUP_CHEAT_SHORT_1H_CELLS = {
    f"base__cup_cheat_3c__short__1h__atr{fa}_h{h}__v1": (k, h)
    for fa, k in (("2d5", 2.5), ("4", 4.0), ("6", 6.0))
    for h in (6, 18, 30)
}


def recip_ohlc(h, l, c):
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    return 1.0 / l, 1.0 / h, 1.0 / c


def _long_cheat_last(h, l, c):
    """Long 3C-cheat rule at the last bar of the arrays (independent re-statement)."""
    if len(c) < MIN_BARS:
        return False
    hw, lw = h[-61:-1], l[-61:-1]
    left_hi = hw[:20].max()
    low = lw.min()
    low_i = int(np.argmin(lw))
    depth = (left_hi - low) / left_hi
    right_hi = hw[48:].max()
    handle_lo = lw[52:].min()
    if not (0.15 <= depth <= 0.35 and 15 <= low_i <= 50 and right_hi >= left_hi * 0.95
            and (right_hi - handle_lo) / right_hi <= 0.12):
        return False
    mid = low + 0.4 * (left_hi - low)
    p_hi, p_lo = hw[54:].max(), lw[54:].min()
    return bool(mid * 0.97 <= p_hi <= mid * 1.10 and (p_hi - p_lo) / p_hi <= 0.10 and c[-1] > p_hi)


def cup_cheat_short_fires(h, l, c) -> bool:
    """True when the inverted-cup cheat fires at the last bar (arrays of High/Low/Close)."""
    return _long_cheat_last(*recip_ohlc(h, l, c))


def cup_cheat_short_signal(h, l, c, atr_mult: float = 4.0):
    """{entry_price, stop_loss, ...} or None. The stop is always above entry."""
    if not cup_cheat_short_fires(h, l, c):
        return None
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    if len(c) <= 14:
        return None
    atr = float(tr[-14:].mean())
    if not np.isfinite(atr) or atr <= 0:
        return None
    px = float(c[-1])
    return {"entry_price": px, "stop_loss": px + atr_mult * atr, "atr_at_entry": atr, "direction": "short"}


def _hlc(df):
    return tuple(df[x].to_numpy(dtype=float) for x in ("High", "Low", "Close"))


def cup_cheat_short_fires_df(df) -> bool:
    """DataFrame form of cup_cheat_short_fires (tag-independent), evaluated at the last bar."""
    return cup_cheat_short_fires(*_hlc(df))


def cup_cheat_short_entry_signal(df, tag: str):
    """None when no signal / unknown tag. Sell short at the signal close; the buy-to-cover stop is always ABOVE entry."""
    cfg = CUP_CHEAT_SHORT_1H_CELLS.get(tag)
    if cfg is None:
        return None
    sig = cup_cheat_short_signal(*_hlc(df), atr_mult=cfg[0])
    if not sig or not (sig["stop_loss"] > sig["entry_price"] > 0):
        return None
    sig["risk"] = sig["stop_loss"] - sig["entry_price"]
    return sig


def cup_cheat_short_exit_reason(df, entry_pos: int, stop: float, hold: int):
    """Mirror of main.cup_cheat_3c_exit_reason for a SHORT entered at the close of bar entry_pos, checked on the last bar j:
    gap-aware buy-to-cover stop (high >= stop: fill bar at the stop, later bars at max(stop, open)), else the close of the
    hold-th bar after entry. (reason, px) or None while open."""
    j = len(df) - 1
    if j <= entry_pos:
        return None
    o, h, c = (float(df[x].iloc[j]) for x in ("Open", "High", "Close"))
    if h >= stop:
        return "cup_cheat_short_stop_loss", (float(stop) if j == entry_pos + 1 else max(float(stop), o))
    if j - entry_pos >= hold:
        return "cup_cheat_short_max_hold_timeout", c
    return None
