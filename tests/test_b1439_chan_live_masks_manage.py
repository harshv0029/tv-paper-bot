"""B-1439: an open chan_kalman position must NOT be 'flatten_1515'-exited mid-morning.

RELIANCE.NS 2026-11-02 IST (Kotak order log): real short 3 @ Rs1217.50 at 09:18:55 by
chan_kalman__band_mr__short__15m__...z1d0_fl1515__v2, BUY-to-cover at 09:20:59 with reason
'exited_short_flatten_1515' (paper book: 19 such round trips on RELIANCE before 10:00). Root cause:
_chan_short_manage / _chan_long_manage called the exit function without masks, so chan_flatten_masks ran on the
LIVE partial-day frame and marked its last bar as the day's 15:15 cut bar. Entry already used _chan_live_masks.
Run: pytest tests/test_b1439_chan_live_masks_manage.py -v"""
import numpy as np
import pandas as pd

import main

SHORT_TAG = "chan_kalman__band_mr__short__15m__atr4d0_hold40_ve10d0e4_z1d0_fl1515__v2"


def _live_frame(interval, last_ist="2026-11-02 09:15", days=3, flat=100.0):
    """Prior full sessions + today's bars up to last_ist, flat prices (kalman err ~0 -> no state exit by sign)."""
    step = main._CHAN_BAR_MIN[interval]
    idx = []
    for d in pd.date_range(end=pd.Timestamp(last_ist[:10]), periods=days, freq="B"):
        t = d + pd.Timedelta(hours=9, minutes=15)
        end = d + pd.Timedelta(hours=15, minutes=30)
        if d.date() == pd.Timestamp(last_ist).date():
            end = pd.Timestamp(last_ist) + pd.Timedelta(minutes=1)
        while t < end:
            idx.append(t)
            t += pd.Timedelta(minutes=step)
    ts = pd.DatetimeIndex(idx).tz_localize("Asia/Kolkata").tz_convert("UTC")
    n = len(ts)
    # slight downward drift so the kalman error is POSITIVE for a short (err <= 0 would be a state exit)
    close = flat + np.linspace(0.5, 0.0, n)
    df = pd.DataFrame({"Open": close, "High": close + 0.1, "Low": close - 0.1, "Close": close})
    return df, pd.Series(ts)


def test_raw_masks_mark_live_last_bar_as_cut_live_masks_do_not():
    df, ts = _live_frame("15m")
    idx = pd.DatetimeIndex(ts)
    assert main.chan_flatten_masks(idx, "15m")[0][-1]  # the bug's mechanism
    assert not main._chan_live_masks(idx, "15m")[0][-1]


def test_short_manage_no_flatten_at_0920(monkeypatch):
    df, ts = _live_frame("15m")
    row = {"stop_loss": 200.0, "entry_price": 100.0, "entry_ts": int(pd.DatetimeIndex(ts)[-1].timestamp()),
           "strategy": SHORT_TAG}
    monkeypatch.setattr(main, "chan_kalman_series", lambda c, ve: (np.ones(len(c)), np.ones(len(c))))
    why = main._chan_short_manage(None, "X.NS", row, df, pd.DatetimeIndex(ts), "15m", 9 * 60 + 20, 100.0, False)
    assert why is None
    # the real 15:10 flatten still fires
    assert main._chan_short_manage(None, "X.NS", row, df, pd.DatetimeIndex(ts), "15m", 15 * 60 + 10, 100.0,
                                   False) == "flatten_1515"


def test_long_manage_no_flatten_mid_morning(monkeypatch):
    tag = next(iter(main.CHAN_LONG_CELLS))
    df, ts = _live_frame("5m", last_ist="2026-11-02 10:05")
    row = {"stop_loss": 1.0, "entry_price": 100.0, "entry_ts": int(pd.DatetimeIndex(ts)[-1].timestamp()),
           "strategy": tag}
    monkeypatch.setattr(main, "chan_kalman_series", lambda c, ve: (-np.ones(len(c)), np.ones(len(c))))
    assert main._chan_long_manage(row, df, pd.DatetimeIndex(ts), "5m", 10 * 60 + 7, 100.0, False) is None


def test_short_manage_still_flattens_on_real_cut_bar(monkeypatch):
    """At the true last bar before 15:15 (15m: the 15:00 bar) the cut mask still applies."""
    df, ts = _live_frame("15m", last_ist="2026-11-02 15:00")
    row = {"stop_loss": 200.0, "entry_price": 100.0, "entry_ts": int(pd.DatetimeIndex(ts)[-5].timestamp()),
           "strategy": SHORT_TAG}
    monkeypatch.setattr(main, "chan_kalman_series", lambda c, ve: (np.ones(len(c)), np.ones(len(c))))
    assert main._chan_short_manage(None, "X.NS", row, df, pd.DatetimeIndex(ts), "15m", 15 * 60 + 5, 100.0,
                                   False) == "flatten_1515"
