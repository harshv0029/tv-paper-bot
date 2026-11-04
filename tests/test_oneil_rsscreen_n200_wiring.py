"""B-1468: oneil_rsscreen LONG cells wired with RS ranked inside the live watchlist population (rs_universe=n200
replays: 1d run 41855872144, 1w run 41855879111). Mapping/gate, cascade placement, the RS matrix built once per pass
from the prefetched frames, eligibility (replay min_bars / clean_bars parity), fail-closed without a rank, and the
entry plumbing (stop < entry)."""
import inspect
import os
import sys

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

W = main.ONEIL_RSSCREEN_1W_N200_TAG
D = main.ONEIL_RSSCREEN_1D_N200_TAG
END = "2026-10-30"  # Friday


@pytest.fixture(autouse=True)
def _reset_rs():
    saved = dict(main._ONEIL_RS_PASS)
    main._ONEIL_RS_PASS.update({"1d": None, "1w": None})
    yield
    main._ONEIL_RS_PASS.update(saved)


def _frame(n, slope, end=END, seed=0):
    dates = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    c = 100.0 * np.exp(slope * np.arange(n) + rng.normal(0, 0.002, n).cumsum())
    df = pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c, "Volume": np.full(n, 1e5)},
                      index=dates)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in dates]
    return df


def test_mapped_wired_and_metrics_clear_owner_bar():
    names = {s.name: s for s in sr.REGISTRY}
    for tag, avg_hold_max in ((W, None), (D, 30)):
        m = names[tag].metrics
        assert m.pfnet > 1.0 and m.n_trades >= 30
        if avg_hold_max:
            assert m.avg_held_bars <= avg_hold_max
        assert names[tag.replace("__nonovl__v2", "_nonovl_segoos__v2")].metrics.pfnet > 1.0
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
        assert tag not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is True
    # the full-universe RS tags (population mismatch) stay unwired
    assert main.ONEIL_EXT_1W_RSSCREEN_TAG not in main.ONEIL_SWING_CELLS
    assert main.ONEIL_RSSCREEN_1D_TAG not in main.ONEIL_DAILY_CELLS


def test_cascade_placement_by_pfnet():
    weekly = list(main.ONEIL_SWING_CELLS)
    assert weekly[weekly.index("oneil_hft__breakout__long__1w__atr3_h26_srcmain__nonovl__v2") + 1] == W
    assert list(main.ONEIL_DAILY_CELLS)[0] == D
    assert main.ONEIL_DAILY_CELLS[D][1:] == (2.0, 40, False)


def test_pass_builds_rs_from_prefetched_frames_once():
    src = inspect.getsource(main._run_swing_scan_pass) if hasattr(main, "_run_swing_scan_pass") else inspect.getsource(main)
    assert src.count("_oneil_rs_set_for_pass(") >= 1


def test_eligibility_and_rank_parity_with_replay():
    import oneil_research as orx
    frames = {f"S{k}.NS": _frame(500, 0.0004 * (k - 5), seed=k) for k in range(10)}
    frames["SHORT.NS"] = _frame(200, 0.002, seed=99)  # < 300 clean daily bars: outside the population
    main._oneil_rs_set_for_pass(frames)
    m = main._ONEIL_RS_PASS["1d"]
    assert "SHORT.NS" not in m.columns and len(m.columns) == 10
    closes = pd.DataFrame({s: orx.clean_bars(f.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]])["Close"]
                           for s, f in frames.items() if s != "SHORT.NS"})
    ref = orx.rs_rank_matrix(closes, orx.CFG["1d"]["rs_lb"])
    pd.testing.assert_frame_equal(m.sort_index(axis=1), ref.sort_index(axis=1), check_names=False, check_freq=False)
    # strongest symbol ranks top at the last bar; weakest bottom
    assert m["S9.NS"].iloc[-1] == pytest.approx(99.0) and m["S0.NS"].iloc[-1] == pytest.approx(1 + 98 / 10)
    assert main._ONEIL_RS_PASS["1w"] is not None and "S9.NS" in main._ONEIL_RS_PASS["1w"].columns


def test_clean_bars_port_matches_research():
    import oneil_research as orx
    df = _frame(60, 0.001)[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.iloc[20, df.columns.get_loc("Close")] *= 1.6  # glitch
    df.iloc[30, df.columns.get_loc("Low")] = 0.0
    pd.testing.assert_frame_equal(main.oneil_clean_bars(df), orx.clean_bars(df))


def test_no_rank_fails_closed():
    df = _frame(500, 0.002)
    today = main._add_nse_trading_days(END, 1)
    assert main.oneil_daily_entry_signal(df, D, today=today, symbol="X.NS") is None
    assert main.oneil_daily_entry_signal(df, D, today=today, symbol=None) is None
    wk = _frame(505, 0.002, end="2026-11-02")  # Monday: newest week has 1 session
    assert main.oneil_swing_entry_signal(wk, W, "X.NS") is None
    assert main._oneil_rs_for("X.NS", "1d", ["2026-10-30"]) is None


def test_daily_fires_with_stop_below_entry_when_rank_top(monkeypatch):
    df = _frame(500, 0.002)
    today = main._add_nse_trading_days(END, 1)
    monkeypatch.setattr(main, "_oneil_rs_for", lambda s, tf, keys: np.full(len(keys), 95.0) if s == "A.NS" else None)
    calls = {}

    def fake(c, rs, tf, direction):
        calls["args"] = (tf, direction, len(c), len(rs))
        out = np.zeros(len(c), bool)
        out[-1] = True
        return out
    monkeypatch.setattr(main, "oneil_rsscreen_signals", fake)
    sig = main.oneil_daily_entry_signal(df, D, today=today, symbol="A.NS")
    assert sig and 0 < sig["stop_loss"] < sig["entry_price"]
    assert calls["args"] == ("1d", "long", 500, 500)
    assert main.oneil_daily_entry_signal(df, D, today=today, symbol="B.NS") is None


def test_weekly_fires_with_stop_below_entry_when_rank_top(monkeypatch):
    wk = _frame(505, 0.002, end="2026-11-02")
    monkeypatch.setattr(main, "_oneil_rs_for", lambda s, tf, keys: np.full(len(keys), 95.0) if s == "A.NS" else None)

    def fake(c, rs, tf, direction):
        assert tf == "1w" and direction == "long"
        out = np.zeros(len(c), bool)
        out[-1] = True
        return out
    monkeypatch.setattr(main, "oneil_rsscreen_signals", fake)
    sig = main.oneil_swing_entry_signal(wk, W, "A.NS")
    assert sig and 0 < sig["stop_loss"] < sig["entry_price"]
    assert main.oneil_swing_entry_signal(wk, W, "B.NS") is None


def test_live_callers_pass_symbol():
    assert "oneil_swing_entry_signal(df, tag, symbol)" in inspect.getsource(main._oneil_swing_try_entry)
    assert "symbol=symbol" in inspect.getsource(main._oneil_daily_try_entry)
    assert "_oneil_scan_signal(df, t, symbol)" in inspect.getsource(main)


def test_daily_sibling_cell_never_rebuys_same_signal_bar(monkeypatch):
    """B-1468: a buy of signal bar t under the leaders cell blocks the rsscreen cell (and vice versa)."""
    import sqlite3
    sig = {"entry_price": 125.0, "stop_loss": 120.0, "atr_at_entry": 2.5, "signal_day": END}
    monkeypatch.setattr(main, "oneil_daily_entry_signal", lambda df, tag, **k: dict(sig) if tag == D else None)
    monkeypatch.setattr(main, "_is_strategy_wired", lambda t: True)
    sized = []
    monkeypatch.setattr(main, "_swing_position_size", lambda *a: sized.append(1) or 0)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE trades (ts REAL, symbol TEXT, action TEXT, qty REAL, price REAL, strategy_id INTEGER, "
                 "source TEXT, raw_payload TEXT)")
    conn.execute("INSERT INTO trades VALUES (1, 'X.NS', 'buy', 1, 125, 1, 'swing', ?)",
                 ('{"entry_reason": "%s", "stop_loss": 120.0, "signal_day": "%s"}' % (main.ONEIL_LEADERS_1D_TAG, END),))
    today = main._add_nse_trading_days(END, 1)
    assert main._oneil_daily_try_entry(conn, "X.NS", None, 100000, 0.01, today, 1.0) is False
    assert not sized
