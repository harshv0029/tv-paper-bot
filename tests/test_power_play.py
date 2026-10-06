"""Tests for the Power Play / High Tight Flag strategy (2026-09-29,
explicit user instruction "Build Power Play first" after a second reading
pass over docs/Trade Like a Stock Market Wizard (2013).pdf surfaced it as
the clearest genuinely-new strategy candidate - see
docs/minervini_book_notes.txt's CHAPTER 10 (REST) section). Unlike
Minervini VCP, Power Play is NOT gated by the Trend Template or
fundamentals: an explosive prior move (>=100% in <=40 trading days), a
tight sideways flag (<=25% deep, final leg <=10%), then a breakout.
2026-09-30, "Wire it now anyway" (explicit user override of this
strategy's own thin-sample caution - see power_play_high_tight_flag's
registry entry, n=109): wired into _run_swing_scan, checked before
gap_and_go/Minervini VCP since it's the rarest of the four setups."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import numpy as np
import pandas as pd

import main


def _power_play_fixture(launch_bars=25, launch_start=100.0, launch_peak=210.0,
                         breakout_close=216.0, breakout_vol=3000.0):
    """25 bars of a launch move (+110% here by default, comfortably over
    the 100% floor) whose peak sits at the very last launch bar, followed
    by a 15-bar flag oscillating within 25% of that peak (tightening to
    within 10% over its final 5 bars), then a breakout bar clearing the
    flag's high on a volume surge."""
    launch = np.linspace(launch_start, launch_peak, launch_bars)
    flag_mid = np.concatenate([
        np.array([205.0, 192.0, 203.0, 194.0, 201.0, 196.0, 199.0, 197.0, 198.0, 197.5]),
        np.array([208.0, 209.0, 207.5, 209.5, 208.5]),
    ])
    close = np.concatenate([launch, flag_mid, [breakout_close]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = breakout_vol
    return pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })


# ---- _find_power_play_setup / power_play_entry_signal -----------------------

def test_power_play_entry_fires_on_a_clean_launch_flag_breakout():
    df = _power_play_fixture()
    sig = main.power_play_entry_signal(df)
    assert sig is not None
    assert sig["entry_price"] == df["Close"].iloc[-1]
    assert sig["stop_loss"] < sig["entry_price"]
    assert sig["atr_at_entry"] > 0


def test_power_play_entry_none_without_a_qualifying_launch():
    # Flat prior history instead of a >=100% move - same flag/breakout shape.
    launch_flat = np.full(25, 200.0) + np.linspace(0, 1, 25)
    flag_mid = np.concatenate([
        np.array([205.0, 192.0, 203.0, 194.0, 201.0, 196.0, 199.0, 197.0, 198.0, 197.5]),
        np.array([208.0, 209.0, 207.5, 209.5, 208.5]),
    ])
    close = np.concatenate([launch_flat, flag_mid, [216.0]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = 3000.0
    df = pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_when_flag_is_too_deep():
    # Same launch, but the flag corrects ~40% - well past the 25% ceiling.
    launch = np.linspace(100.0, 210.0, 25)
    flag_mid = np.concatenate([
        np.array([205.0, 130.0, 200.0, 135.0, 198.0, 140.0, 196.0, 145.0, 194.0, 150.0]),
        np.array([205.0, 206.0, 204.5, 206.5, 205.5]),
    ])
    close = np.concatenate([launch, flag_mid, [212.0]])
    volume = np.full(len(close), 1000.0)
    volume[-1] = 3000.0
    df = pd.DataFrame({
        "Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close,
        "Volume": volume,
        "Date": pd.date_range("2020-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d"),
    })
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_without_a_breakout():
    df = _power_play_fixture(breakout_close=205.0)  # still inside the flag's own high (211)
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_without_a_volume_surge():
    df = _power_play_fixture(breakout_vol=1000.0)  # no surge over the trailing average
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_none_on_insufficient_history():
    df = _power_play_fixture().iloc[-15:].reset_index(drop=True)
    assert main.power_play_entry_signal(df) is None


def test_power_play_entry_stop_uses_flag_low():
    df = _power_play_fixture()
    sig = main.power_play_entry_signal(df)
    setup = main._find_power_play_setup(df)
    assert sig["stop_loss"] == setup["consol_low"]


# ---- power_play_exit_reason ---------------------------------------------

def test_power_play_exit_none_while_holding():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 102.0, 104.0],
    })
    reason, running_max = main.power_play_exit_reason(df, "2026-01-02", 90.0, 5.0, 100.0)
    assert reason is None
    assert running_max == 104.0


def test_power_play_exit_trail_stop_hit():
    df = pd.DataFrame({
        "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "Close": [100.0, 130.0, 119.0],
    })
    # running_max ratchets to 130 after bar 2; trail_stop = 130 - 2*5 = 120 > initial_stop(90)
    reason, running_max = main.power_play_exit_reason(df, "2026-01-02", 90.0, 5.0, 130.0)
    assert reason == "trail_stop_hit"
    assert running_max == 130.0


def test_power_play_exit_max_hold_timeout():
    dates = pd.bdate_range("2026-01-02", periods=main.POWER_PLAY_MAX_HOLD_DAYS + 2).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.power_play_exit_reason(df, dates[0], 50.0, 5.0, 100.0)
    assert reason == "max_hold_timeout"


def test_power_play_exit_not_yet_at_max_hold():
    dates = pd.bdate_range("2026-01-02", periods=main.POWER_PLAY_MAX_HOLD_DAYS - 5).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"Date": dates, "Close": [100.0] * len(dates)})
    reason, _ = main.power_play_exit_reason(df, dates[0], 50.0, 5.0, 100.0)
    assert reason is None


# ---- _run_swing_scan wiring: 2026-09-30, "Wire it now anyway" -------------

def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_power_play_tag_maps_to_the_correct_registry_entry_and_is_viable():
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["power_play"] == "power_play_high_tight_flag"
    assert main._is_strategy_viable_for_real_money("power_play") is True


def test_run_swing_scan_opens_a_power_play_position_on_a_real_fixture(monkeypatch):
    _fresh_db()
    df = _power_play_fixture(launch_bars=40)  # total len 56, clears _run_swing_scan's own len>=50 gate
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["POWERPLAY.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    real_entry_calls = []
    monkeypatch.setattr(
        main, "_maybe_place_real_swing_entry",
        lambda conn, symbol, qty, entry_price, stop_loss, strategy: real_entry_calls.append(strategy),
    )

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'POWERPLAY.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "power_play"
        assert row["atr_at_entry"] is not None and row["atr_at_entry"] > 0
        assert row["running_max_close"] == row["entry_price"]
    assert real_entry_calls == ["power_play"]


def test_run_swing_scan_power_play_takes_priority_over_gap_and_go_and_minervini(monkeypatch):
    # Power Play is checked FIRST (see _run_swing_scan's own comment) - a
    # symbol qualifying for it must never instead be recorded under a
    # less-selective, more-frequently-firing signal.
    _fresh_db()
    df = _power_play_fixture(launch_bars=40)  # total len 56, clears _run_swing_scan's own len>=50 gate
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["ALLTHREE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(main, "gap_and_go_entry_signal", lambda d: {"entry_price": 100.0, "stop_loss": 90.0, "gap_low": 95.0})
    monkeypatch.setattr(main, "minervini_vcp_entry_signal_livermore_confirmed",
                         lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0})
    monkeypatch.setattr(main, "minervini_vcp_entry_signal",
                         lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0})

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'ALLTHREE.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "power_play"


def test_run_swing_scan_exits_a_power_play_position_using_its_own_exit_mechanics(monkeypatch):
    _fresh_db()
    df = _power_play_fixture(launch_bars=40)  # total len 56, clears _run_swing_scan's own len>=50 gate
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["EXITPOWERPLAY.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    exit_mirror_calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_exit", lambda conn, symbol, reason=None: exit_mirror_calls.append(symbol))

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('EXITPOWERPLAY.NS', 'power_play', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 182.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "power_play_exit_reason", lambda d, entry_day, stop, atr, running_max: ("trail_stop_hit", 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'EXITPOWERPLAY.NS'").fetchone()
        assert row is None
        trade = conn.execute("SELECT * FROM trades WHERE symbol = 'EXITPOWERPLAY.NS' AND action = 'sell'").fetchone()
        assert trade is not None
        assert exit_mirror_calls == ["EXITPOWERPLAY.NS"]


def test_run_swing_scan_updates_power_play_running_max_close_without_exiting(monkeypatch):
    _fresh_db()
    df = _power_play_fixture(launch_bars=40)  # total len 56, clears _run_swing_scan's own len>=50 gate
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["HOLDPOWERPLAY.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('HOLDPOWERPLAY.NS', 'power_play', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 150.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "power_play_exit_reason", lambda d, entry_day, stop, atr, running_max: (None, 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'HOLDPOWERPLAY.NS'").fetchone()
        assert row is not None
        assert row["running_max_close"] == 182.0


def test_real_power_play_entry_mirror_proceeds_with_real_gate_and_switch_on():
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"
    patches = [
        patch("kotak_live_feed.get_live_ticks",
              return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}),
        patch("main.get_scheduler_capital_inr", return_value=1_000_000.0),
        patch("main._real_today_spent_inr", return_value=0.0),
        patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}),
        patch("kotak_real_orders.place_real_entry",
              return_value={"ok": True, "qty": 10, "fill_price": 100.0, "order_id": "E1", "fill_price_confirmed": True}),
        patch("kotak_real_orders.place_real_stop_loss",
              return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}),
    ]
    started = [p.start() for p in patches]
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "power_play")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is not None
            assert row["strategy"] == "power_play"
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        for p in patches:
            p.stop()
