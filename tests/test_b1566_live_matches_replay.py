"""B-1566: live chan cells fired 0 times on 16-Nov while the replay of the same main.py functions fired on TMPV /
KALYANKJIL 09:15 bars. Root causes: (1) the buy engine returned 'waiting_for_opening_range' before 09:30 IST, ahead of
every chan cell; (2) the chan entry check read Yahoo's still-forming bar instead of the completed signal bar;
(3) triggers on a symbol another engine holds were counted but never surfaced in /entry-funnel."""
import datetime as real_datetime
import math
import os
import tempfile
from unittest.mock import patch

import pandas as pd

import main


class _At0922Ist(real_datetime.datetime):
    _fixed = real_datetime.datetime(2026, 9, 9, 3, 52, 0)  # UTC -> 09:22 IST

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _fixture(today_bars=2):
    rows, i = [], 0
    for day in ["2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08"] + ["2026-09-09"]:
        n = 20 if day != "2026-09-09" else today_bars
        base = pd.Timestamp(f"{day} 03:45:00")
        for b in range(n):
            c = 100 + 0.15 * i + 0.3 * math.sin(i / 2.0)
            rows.append({"Date": base + pd.Timedelta(minutes=5 * b), "Open": c, "High": c + 0.2, "Low": c - 0.2,
                         "Close": c, "Volume": 1000})
            i += 1
    return pd.DataFrame(rows)


def test_chan_cells_evaluated_before_0930_and_orb_still_waits():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    calls = []

    def spy(*a, **k):
        calls.append(a[6])  # interval
        return None

    with patch("main.dt.datetime", _At0922Ist), patch("main.fetch_ohlc", return_value=_fixture()), \
            patch("main._chan_long_try_entry", side_effect=spy), \
            patch("main._chan_short_df_for", side_effect=RuntimeError("no 15m")):
        res = main._auto_signal_core("TESTSTOCK.NS", currency="INR")
    assert calls and calls[0] == "5m", f"chan long cells must be evaluated at 09:22 IST, got {res}"
    assert res["status"] == "waiting_for_opening_range"  # the ORB entry itself still waits for 09:30


def test_completed_frame_drops_only_the_forming_bar():
    idx = pd.date_range("2026-11-16 03:45", periods=3, freq="5min", tz="UTC")  # 09:15, 09:20, 09:25 IST
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=idx)
    # 09:28 IST: the 09:25 bar is still forming -> dropped; the 09:20 bar is the last completed one
    out = main._chan_completed_frame(df, "5m", now_utc=pd.Timestamp("2026-11-16 03:58", tz="UTC"))
    assert list(out["Close"]) == [1.0, 2.0]
    # 09:30 IST: the 09:25 bar is complete -> kept
    out = main._chan_completed_frame(df, "5m", now_utc=pd.Timestamp("2026-11-16 04:00", tz="UTC"))
    assert len(out) == 3
    # 15m: the 09:15 bar completes at 09:30
    idx15 = pd.date_range("2026-11-16 03:45", periods=1, freq="15min", tz="UTC")
    d15 = pd.DataFrame({"Close": [1.0]}, index=idx15)
    assert len(main._chan_completed_frame(d15, "15m", now_utc=pd.Timestamp("2026-11-16 03:59", tz="UTC"))) == 0
    assert len(main._chan_completed_frame(d15, "15m", now_utc=pd.Timestamp("2026-11-16 04:00", tz="UTC"))) == 1


def test_chan_try_entries_use_completed_frame():
    import inspect
    for fn in (main._chan_long_try_entry, main._chan_short_try_entry):
        assert "_chan_completed_frame(_chan_short_frame(df, ts_utc), interval)" in inspect.getsource(fn)


def test_blocked_by_position_counted_once_per_symbol_and_in_funnel():
    main._strategy_entry_blocked_by_position.clear()
    main._strategy_entry_blocked_by_position_seen.clear()
    tag = "macddiv__line_any__long__1h__atr3_w5__nonovl__v2"
    for sym in ("HCLTECH.NS", "HCLTECH.NS", "HCLTECH.NS", "TMPV.NS"):
        tok = main._current_scan_symbol.set(sym)
        try:
            assert main._scan_cell(tag, lambda: {"x": 1}, count=False, blocked=True)
        finally:
            main._current_scan_symbol.reset(tok)
    assert main._strategy_entry_blocked_by_position[tag] == 2
    import inspect
    src = inspect.getsource(main)
    assert '_r["blocked_by_position"]' in src and 'r.get("blocked_by_position")' in src
