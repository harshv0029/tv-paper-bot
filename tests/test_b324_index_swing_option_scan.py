"""B-324: _run_index_swing_option_scan routes an index's own daily swing signal to an option on that index.
Long gap_and_go -> CALL, short mirror -> PUT; once per IST day; only 09:20-15:00 IST; off when the F&O switch is off."""
import datetime as dt

import pandas as pd
import pytest

import main


def _df(n=60):
    return pd.DataFrame({"Open": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n, "Close": [100.5] * n,
                         "Volume": [1000] * n})


@pytest.fixture
def scan(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_index_swing_option_scan_day", None)
    monkeypatch.setattr(main, "is_real_fo_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_nse_closed_day", lambda t: False)
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime(2026, 11, 16, 10, 0))
    monkeypatch.setattr(main, "fetch_ohlc", lambda s, p, i: _df())
    monkeypatch.setattr(main, "_note_symbol_strategy_scan", lambda s, t: None)
    monkeypatch.setattr(main, "_maybe_place_real_fo_call_entry", lambda c, s, spot, tag: calls.append(("CE", s, tag)))
    monkeypatch.setattr(main, "_maybe_place_real_fo_put_entry", lambda c, s, spot, tag: calls.append(("PE", s, tag)))
    return monkeypatch, calls


def test_long_signal_buys_call_on_each_index(scan):
    mp, calls = scan
    mp.setattr(main, "gap_and_go_entry_signal", lambda df: True)
    mp.setattr(main, "gap_and_go_entry_signal_short", lambda df: False)
    main._run_index_swing_option_scan(None)
    assert calls == [("CE", s, "gap_and_go") for s in main._INDEX_SWING_OPTION_SYMBOLS]


def test_short_signal_buys_put(scan):
    mp, calls = scan
    mp.setattr(main, "gap_and_go_entry_signal", lambda df: False)
    mp.setattr(main, "gap_and_go_entry_signal_short", lambda df: True)
    main._run_index_swing_option_scan(None)
    assert calls and all(c[0] == "PE" and c[2] == "gap_and_go_short" for c in calls)


def test_once_per_ist_day(scan):
    mp, calls = scan
    mp.setattr(main, "gap_and_go_entry_signal", lambda df: True)
    main._run_index_swing_option_scan(None)
    n = len(calls)
    main._run_index_swing_option_scan(None)
    assert len(calls) == n


@pytest.mark.parametrize("hm", [(9, 19), (15, 0), (15, 30)])
def test_outside_window_no_entry(scan, hm):
    mp, calls = scan
    mp.setattr(main, "ist_now", lambda: dt.datetime(2026, 11, 16, *hm))
    mp.setattr(main, "gap_and_go_entry_signal", lambda df: True)
    main._run_index_swing_option_scan(None)
    assert calls == []


def test_fo_switch_off_no_entry(scan):
    mp, calls = scan
    mp.setattr(main, "is_real_fo_trading_enabled", lambda: False)
    mp.setattr(main, "gap_and_go_entry_signal", lambda df: True)
    main._run_index_swing_option_scan(None)
    assert calls == []


def test_short_fetch_skipped(scan):
    mp, calls = scan
    mp.setattr(main, "fetch_ohlc", lambda s, p, i: _df(10))
    mp.setattr(main, "gap_and_go_entry_signal", lambda df: True)
    main._run_index_swing_option_scan(None)
    assert calls == []
