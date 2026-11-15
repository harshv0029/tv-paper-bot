"""B-1600 (b): the 12 island LONG 4h _tfs cells (all PFnet > 1.00, main.py-function sweep run 43692422951) wired into the
long swing engine's 1h leg on research-identical session-anchored 4h bars, entry only on a completed bar-0 signal."""
import datetime as dt
import inspect
import os
import sys
from contextlib import closing

import numpy as np
import pandas as pd

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import resample_4h as r4  # noqa: E402

SLOTS = ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]


def _hourly(days=30, last_day_slots=None, start="2026-10-01"):
    """_hourly_with_str_date-shaped 1h frame (string IST Date, RangeIndex), weekdays only."""
    rows, d = [], pd.Timestamp(start)
    ds = []
    while len(ds) < days:
        if d.weekday() < 5:
            ds.append(d)
        d += pd.Timedelta(days=1)
    for i, day in enumerate(ds):
        slots = SLOTS if (i < len(ds) - 1 or last_day_slots is None) else SLOTS[:last_day_slots]
        for s in slots:
            rows.append(f"{day:%Y-%m-%d} {s}")
    n = len(rows)
    c = 100.0 + np.sin(np.arange(n) / 3.0)
    return pd.DataFrame({"Date": rows, "Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c + 0.1,
                         "Volume": np.arange(n, dtype=float) + 1.0})


def test_resample_matches_research_helper_naive_and_tz():
    df = _hourly(10)
    x = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["Date"])))[["Open", "High", "Low", "Close", "Volume"]]
    a, b = main.resample_1h_to_4h_session(x), r4.resample_1h_to_4h(x)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 20 and list(a.index[:2].strftime("%H:%M")) == ["09:15", "13:15"]
    xt = x.tz_localize("Asia/Kolkata").tz_convert("UTC")  # yfinance-style tz-aware index, read in IST hours
    at = main.resample_1h_to_4h_session(xt)
    np.testing.assert_allclose(at[["Open", "High", "Low", "Close", "Volume"]].to_numpy(), b.to_numpy())
    assert list(at.index[:2].strftime("%H:%M")) == ["09:15", "13:15"]


def test_cells_wired_ordered_and_replay_verified():
    rows = {t: (n, pf) for t, n, pf in main._replay_rows()}
    tags = main.ISLAND_TFS_LONG_4H_TAGS
    assert len(tags) == 12 == len(set(tags)) and all("__long__4h__" in t and "_tfs__" in t for t in tags)
    pfs = [rows[t][1] for t in tags]
    assert all(p > 1.0 for p in pfs) and pfs == sorted(pfs, reverse=True)
    for t, sel, k in main.ISLAND_LONG_4H_CELLS:
        assert t not in main.REPLAY_OWED_TAGS and t not in main.REPLAY_FAILED_TAGS
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t and main._registry_entry(t).metrics.pfnet > 1.0
        assert main._is_strategy_wired(t)
        assert main._ISLAND_FILTER_OF_TAG[sel] in ("gap05", "none", "px20", "turn1cr")
        assert t.split("__")[1].startswith("island_" + main._ISLAND_FILTER_OF_TAG[sel])
        assert k == {"1d5": 1.5, "2d5": 2.5, "4": 4.0}[t.split("__")[4].split("_")[0][3:]]
        assert main._strategy_hold_spec(t) == (30, "4h")
        assert "30-bar max hold" in main._SWING_SL_RULES[t]


def test_only_completed_4h_bars():
    df = _hourly(25, last_day_slots=3)  # last day: 09:15/10:15/11:15 only -> bar 0 still forming
    last_day = df["Date"].iloc[-1][:10]
    noon = pd.Timestamp(f"{last_day} 12:20")
    d4 = main._island_4h_completed_bars(df, noon)
    assert d4["Date"].iloc[-1][:10] < last_day and d4["Date"].iloc[-1].endswith("13:15")
    # clock past 13:15 but the 12:15 1h bar is not in yet: still not complete
    assert main._island_4h_completed_bars(df, pd.Timestamp(f"{last_day} 13:20"))["Date"].iloc[-1][:10] < last_day
    df4 = _hourly(25, last_day_slots=4)
    assert main._island_4h_completed_bars(df4, pd.Timestamp(f"{last_day} 13:20"))["Date"].iloc[-1] == f"{last_day} 09:15"
    df6 = _hourly(25, last_day_slots=7)
    assert main._island_4h_completed_bars(df6, pd.Timestamp(f"{last_day} 15:20"))["Date"].iloc[-1] == f"{last_day} 09:15"
    assert main._island_4h_completed_bars(df6, pd.Timestamp(f"{last_day} 15:31"))["Date"].iloc[-1] == f"{last_day} 13:15"


def test_entry_timing_rule():
    now = dt.datetime(2026, 11, 16, 13, 30)
    assert main._island_4h_entry_timing("2026-11-16 09:15", now) == (True, "")
    assert main._island_4h_entry_timing("2026-11-13 13:15", now) == (False, "skipped_4h_signal_after_close")
    assert main._island_4h_entry_timing("2026-11-13 09:15", now) == (False, "skipped_4h_signal_stale")
    assert main._island_4h_entry_timing("2026-11-16 09:15", now.replace(hour=15, minute=0))[1] == "skipped_4h_entry_window_closed"


def _sig(px=100.0, atr=2.0):
    return {"entry_price": px, "stop_loss": px - 3.0, "atr_at_entry": atr, "risk": 3.0, "signal_close": px,
            "direction": "long", "filter": "gap05"}


def _patch_entry(monkeypatch, placed):
    monkeypatch.setattr(main, "island_swing_entry_signal", lambda df, tag, entry_price=None: _sig())
    monkeypatch.setattr(main, "_swing_position_size", lambda *a, **k: 3)
    monkeypatch.setattr(main, "_sync_signal_state_swing_external", lambda c: None)
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda c, s, q, p, sl, t: placed.append((s, q, p, sl, t)))
    monkeypatch.setattr(main, "_log_real_attempt", lambda c, s, side, st, **k: placed.append(("LOG", s, st)))
    main._ISLAND_4H_SIG_CACHE.clear()
    main._ISLAND_4H_SKIP_LOGGED.clear()
    main._SWING_LIVE_PX.pop("ZZ4H.NS", None)


def test_entry_on_completed_bar0_with_sl_and_first_cell(monkeypatch):
    main.init_db()
    placed = []
    _patch_entry(monkeypatch, placed)
    df = _hourly(25, last_day_slots=4)
    day = pd.Timestamp(df["Date"].iloc[-1][:10])
    with closing(main.get_db()) as conn:
        conn.execute("DELETE FROM signal_state_swing WHERE symbol = 'ZZ4H.NS'")
        conn.commit()
        # 12:30: bar 0 still forming -> the last completed bar is yesterday's bar 1 -> skipped (logged once), no row
        assert main._island_long_4h_try_entry(conn, "ZZ4H.NS", df, 1e6, 1.0, now=day.replace(hour=12, minute=30)) is None
        assert main._island_long_4h_try_entry(conn, "ZZ4H.NS", df, 1e6, 1.0, now=day.replace(hour=12, minute=45)) is None
        assert [p for p in placed if p[0] == "LOG"] == [("LOG", "ZZ4H.NS", "skipped_4h_signal_after_close")]
        main._SWING_LIVE_PX["ZZ4H.NS"] = 101.0
        tag = main._island_long_4h_try_entry(conn, "ZZ4H.NS", df, 1e6, 1.0, now=day.replace(hour=13, minute=25))
        assert tag == main.ISLAND_TFS_LONG_4H_TAGS[0]
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'ZZ4H.NS'").fetchone()
        assert row["strategy"] == tag and row["entry_day"] == f"{day:%Y-%m-%d} 09:15"
        assert row["entry_price"] == 101.0 and row["initial_stop_loss"] == main.brk20_stop_price(101.0, 2.0, 1.5, "long")
        assert placed[-1] == ("ZZ4H.NS", 3, 101.0, row["initial_stop_loss"], tag)
        conn.execute("DELETE FROM signal_state_swing WHERE symbol = 'ZZ4H.NS'")
        conn.commit()
    main._SWING_LIVE_PX.pop("ZZ4H.NS", None)


def test_exit_replays_on_4h_bars_by_timestamp():
    df = main._island_4h_completed_bars(_hourly(25), pd.Timestamp("2027-01-01"))
    sig_bar = df["Date"].iloc[-6]
    pos = {"strategy": main.ISLAND_TFS_LONG_4H_TAGS[0], "entry_day": sig_bar, "entry_price": 100.0,
           "initial_stop_loss": float(df["Low"].iloc[-5]) + 0.01}
    r = main._island_long_4h_exit(df, pos)
    assert r == ("island_stop_loss", pos["initial_stop_loss"])  # hit on the fill bar (the 4h bar after the signal bar)
    pos["initial_stop_loss"] = 1.0
    pos["entry_day"] = df["Date"].iloc[-1]
    assert main._island_long_4h_exit(df, pos) is None  # no 4h bar after the signal bar yet
    pos["entry_day"] = df["Date"].iloc[-32]  # 31 bars after the signal bar: the 30-bar max hold (or an earlier rule exit)
    r = main._island_long_4h_exit(df, pos)
    assert r is not None and r[0] in ("island_max_hold_timeout", "island_rule_exit")


def test_wired_in_1h_leg_and_daily_island_unchanged():
    src = inspect.getsource(main._run_long_swing_1h_pass)
    assert "_island_long_4h_try_entry(conn, symbol, df, capital" in src
    assert "_island_long_4h_exit(_island_4h_completed_bars(df), pos)" in src
    assert "SWING_LONG_4H_TAGS" in inspect.getsource(main._with_held_1h_long_symbols)  # B-1605: island + pl1d 4h
    assert set(main.ISLAND_TFS_LONG_4H_TAGS) <= set(main.SWING_LONG_4H_TAGS)
    assert "ISLAND_TFS_LONG_4H_TAGS" in inspect.getsource(main._scan_only_1h_long_cells)
    assert "SWING_LONG_4H_TAGS" in inspect.getsource(main._run_swing_scan_pass)  # daily pass skips 4h positions
    assert not set(main.ISLAND_TFS_LONG_4H_TAGS) & set(main.ISLAND_ALL_TAGS)
    assert main.ISLAND_ALL_TAGS[:12] == main.ISLAND_TFS_LONG_1D_TAGS
    assert "ISLAND_ALL_TAGS" in inspect.getsource(main._island_swing_try_entry)
    assert main._ISLAND_ATR_OF_TAG.get(main.ISLAND_NONE_TAG, main.ISLAND_ATR_MULT) == 1.5
