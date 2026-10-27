"""swingminrr brk20_gate SHORT 1h atr3_rr4 wired into the short-swing engine (paper live; real leg behind the
fail-closed overnight-product check B-912; replay owed). Uses the real main.brk20_min_rr_entry_signal."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

TAG = "swingminrr__brk20_gate__short__1h__atr3_rr4__v1"


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _hourly(close, start="2024-01-01 09:15"):
    close = np.asarray(close, float)
    idx = pd.date_range(start, periods=len(close), freq="h")
    df = pd.DataFrame({"Open": close, "High": close + 0.2, "Low": close - 0.2, "Close": close, "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d %H:%M") for d in idx]
    return df


def _bars(rows, start="2024-02-01 09:15"):
    idx = pd.date_range(start, periods=len(rows), freq="h")
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    df["Volume"] = 1000.0
    df["Date"] = [d.strftime("%Y-%m-%d %H:%M") for d in idx]
    return df


def _breakdown_frame():
    """Fall to 100, rebound to 140 and range there, then close below the prior 20-bar low with a far 60-bar low."""
    path = list(np.linspace(150, 100, 30)) + list(np.linspace(100, 140, 30)) + [140.0, 140.5] * 15 + [137.0]
    return _hourly(path)


def test_tag_registered_mapped_and_replay_owed():
    names = {s.name for s in sr.REGISTRY}
    assert TAG in names
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[TAG] == TAG
    assert TAG in main.REPLAY_FAILED_TAGS  # B-1396c: main.py replay 40575438117 PFnet 0.592, below floor
    assert main._is_strategy_viable_for_real_money(TAG, check_switch=False) is False
    assert main.SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED is False


def test_entry_signal_uses_real_brk20_and_stop_is_above():
    sig = main.swingminrr_gate_short_entry_signal(_breakdown_frame())
    assert sig is not None and sig["stop_loss"] > sig["entry_price"]
    assert abs(sig["stop_loss"] - sig["entry_price"] - 3.0 * sig["atr_at_entry"]) < 1e-6
    assert main.swingminrr_gate_short_entry_signal(_hourly(np.linspace(100, 200, 91))) is None   # no breakdown


def test_exit_stop_gap_aware_and_31st_bar_timeout():
    flat = (100.0, 100.5, 99.5, 100.0)
    assert main.swingminrr_gate_short_exit_reason(_bars([flat] * 30), 110.0) is None
    assert main.swingminrr_gate_short_exit_reason(_bars([flat] * 31), 110.0) == ("max_hold_timeout", 100.0)
    gap = [flat] * 5 + [(115.0, 116.0, 114.0, 115.0)] + [flat] * 5
    assert main.swingminrr_gate_short_exit_reason(_bars(gap), 110.0) == ("stop_hit", 115.0)
    wick = [flat] * 5 + [(100.0, 111.0, 99.5, 100.0)]
    assert main.swingminrr_gate_short_exit_reason(_bars(wick), 110.0) == ("stop_hit", 110.0)


def test_hourly_date_string_and_forming_bar_dropped():
    df = _hourly(np.linspace(100, 110, 10), start="2024-03-01 09:15")
    out = main._hourly_with_str_date(df, now_naive=pd.Timestamp("2024-03-01 20:00"))
    assert len(out) == 10 and out["Date"].iloc[-1] == "2024-03-01 18:15"
    out = main._hourly_with_str_date(df, now_naive=pd.Timestamp("2024-03-01 18:30"))   # last bar still forming
    assert len(out) == 9
    tz = df.copy()
    tz["Date"] = pd.to_datetime(tz["Date"]).dt.tz_localize("Asia/Kolkata")
    assert main._hourly_with_str_date(tz, now_naive=pd.Timestamp("2024-03-02"))["Date"].iloc[0] == "2024-03-01 09:15"


def test_1h_pass_enters_with_stop_then_exits_on_later_bars(monkeypatch):
    _fresh_db()
    offered = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: offered.append(a))
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_exit", lambda *a, **k: None)
    df = _breakdown_frame()
    stamp = pd.Timestamp("2100-01-01")
    monkeypatch.setattr(main, "ist_now", lambda: stamp.to_pydatetime())
    with closing(main.get_db()) as conn:
        main._run_short_swing_1h_pass(conn, ["ABC.NS"], 1_000_000.0, "2024-03-01", set(), fetch=lambda s, p, i: df.drop(columns=["Date"]))
        row = conn.execute("SELECT * FROM signal_state_swing_short WHERE symbol='ABC.NS'").fetchone()
        assert row["strategy"] == TAG and row["initial_stop_loss"] > row["entry_price"] and row["qty"] > 0
        assert row["entry_day"] == df["Date"].iloc[-1]
        assert len(offered) == 1 and offered[0][5] == TAG and offered[0][4] == row["initial_stop_loss"]
        # same bars again: already open, no second entry, no exit
        main._run_short_swing_1h_pass(conn, ["ABC.NS"], 1_000_000.0, "2024-03-01", set(), fetch=lambda s, p, i: df.drop(columns=["Date"]))
        assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 1 and len(offered) == 1
        # a later bar spikes through the stop -> paper exit with the reason
        stop = float(row["initial_stop_loss"])
        nxt = _bars([(150.0, stop + 5, 149.0, 151.0)], start=(pd.Timestamp(df["Date"].iloc[-1]) + pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"))
        ext = pd.concat([df, nxt])
        main._run_short_swing_1h_pass(conn, ["ABC.NS"], 1_000_000.0, "2024-03-01", set(), fetch=lambda s, p, i: ext.drop(columns=["Date"]))
        assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 0
        assert conn.execute("SELECT exit_reason FROM short_trades_closed").fetchone()["exit_reason"] == "short_swing_stop_hit"


def test_daily_pass_leaves_1h_positions_alone(monkeypatch):
    _fresh_db()
    closed = []
    monkeypatch.setattr(main, "_short_swing_close_paper", lambda *a, **k: closed.append(a))
    monkeypatch.setattr(main, "short_swing_entry_signal", lambda df: (None, None))
    monkeypatch.setattr(main, "sector_rotation_fade_short_picks", lambda dfs, L, N: [])
    daily = _hourly(np.linspace(100, 110, 60), start="2024-01-01 00:00")
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing_short (symbol, strategy, entry_day, entry_price, initial_stop_loss, qty, entry_ts, fx_to_inr, atr_at_entry) "
                     "VALUES ('ABC.NS', ?, '2024-01-01 10:15', 100, 1.0, 5, 1, 1.0, 2.0)", (TAG,))
        conn.commit()
        main._run_short_swing_pass(conn, {"ABC.NS": daily}, 1_000_000.0, "2024-03-01", set())
    assert closed == []


def test_real_leg_fails_closed_overnight(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    ko = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "kotak_real_orders", ko)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, TAG)
        st = conn.execute("SELECT status FROM real_trades ORDER BY id DESC LIMIT 1").fetchone()["status"]
    ko.place_real_short_entry.assert_not_called()
    assert st == "skipped_overnight_short_product_unconfirmed"


def test_replay_driver_calls_real_main_functions():
    import importlib.util
    spec = importlib.util.spec_from_file_location("tsm_replay", os.path.join(os.path.dirname(__file__), "..", "scripts", "tasuki_swingminrr_short_main_replay.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    specs = mod.tag_specs(main)
    assert TAG in specs and all(t in specs for t in main.TASUKI_SHORT_CELLS)
    rng = np.random.default_rng(3)
    df = _hourly(100 + np.cumsum(rng.normal(0, 1, 300)))
    for t, sp in specs.items():
        out = mod.replay_symbol(main, df, t, sp, 0.008)
        assert all(set(r) >= {"gross", "net", "held", "reason"} for r in out)
    assert mod.plan({"NSHARDS": "4"})["include"][0]["group"] == "tasuki"
