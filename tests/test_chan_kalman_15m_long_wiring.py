"""B-1470: chan_kalman v1 band LONG 15m cells wired into the buy engine (scanned on the 15m frame from the 5m tick)."""
import inspect

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

TAGS = [
    "chan_kalman__band_srcmain__long__15m__atr4d0_hold40_ve10d0e4_z2d0__v1",
    "chan_kalman__band_srcmain__long__15m__atr4d0_hold40_ve10d0e4_z1d0__v1",
    "chan_kalman__band_srcmain__long__15m__atr4d0_hold40_ve1d0e4_z2d0__v1",  # B-1471 pooled bar
]


def test_cells_appended_after_5m_and_registered_viable():
    cells = list(main.CHAN_LONG_CELLS)
    assert cells[-3:] == TAGS
    assert all(main.CHAN_LONG_CELL_INTERVAL[t] == "5m" for t in cells[:-3])
    by = {d.name: d for d in sr.REGISTRY}
    for t in TAGS:
        assert main.CHAN_LONG_CELL_INTERVAL[t] == "15m"
        assert main.CHAN_LONG_CELLS[t] == (4.0, 1e-3 if "ve10d0e4" in t else 1e-4, 2.0 if "z2d0" in t else 1.0)
        assert by[t].metrics.pfnet > 1.0 and by[t].metrics.n_trades >= 30
        assert t.replace("__v1", "_segoos__v1") in by  # OOS for the record (B-1471: pooled decides)
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t in main.CHAN_INTRADAY_LONG_TAGS


def test_short_srcmain_intraday_cells_not_double_wired():
    for t in main.CHAN_SHORT_CELLS:
        assert "band_srcmain" not in t


def test_5m_scan_skips_15m_cells(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "_record_strategy_scan", lambda t: seen.append(t))
    monkeypatch.setattr(main, "chan_kalman_band_long_entry_signal", lambda *a, **k: None)
    idx = pd.date_range("2026-11-02 04:00", periods=30, freq="5min", tz="UTC")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": np.linspace(1, 2, 30)}, index=range(30))
    main._chan_long_try_entry(None, "X.NS", df, idx, 2.0, "2026-11-02", "5m", 1e5, 1.0, 1.0, "INR", {})
    assert seen and not set(seen) & set(TAGS)
    seen.clear()
    main._chan_long_try_entry(None, "X.NS", df, idx, 2.0, "2026-11-02", "15m", 1e5, 1.0, 1.0, "INR", {})
    assert seen == TAGS


def test_manage_15m_cell_stop_flatten_and_needs_symbol(monkeypatch):
    ts = pd.DatetimeIndex(["2026-10-14 05:00"], tz="UTC")
    df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]})
    for tag in TAGS:
        row = {"stop_loss": 90.0, "entry_price": 100.0, "entry_ts": 0, "strategy": tag}
        assert main._chan_long_manage(row, df, ts, "5m", 600, 89.0, False) == "stop_hit"
        assert main._chan_long_manage(row, df, ts, "5m", 15 * 60 + 10, 101.0, False) == "flatten_1515"
        assert main._chan_long_manage(row, df, ts, "5m", 600, 101.0, False) is None  # no symbol -> no 15m frame
    calls = []

    def fake_df_for(sym, iv):
        calls.append((sym, iv))
        raise RuntimeError("offline")
    monkeypatch.setattr(main, "_chan_short_df_for", fake_df_for)
    row = {"stop_loss": 90.0, "entry_price": 100.0, "entry_ts": 0, "strategy": TAGS[0]}
    assert main._chan_long_manage(row, df, ts, "5m", 600, 101.0, False, symbol="X.NS") is None
    assert calls == [("X.NS", "15m")]


def test_wiring_sources():
    src = inspect.getsource(main._auto_signal_core)
    assert '_chan_short_df_for(symbol, "15m")' in src and '"15m", capital' in src
    assert "symbol=symbol))" in src
