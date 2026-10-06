"""Tests for wiring primary_base into the live swing scan (2026-10-01,
explicit user instruction: "wire to live real money only to viable ones",
after full-universe validation replay run 36820565494 - PFnet 2.069, clears
PFNET_LIVE_FLOOR). Mirrors tests/test_minervini_vcp_live_wiring.py's own
Livermore-confirmed wiring tests: same real-trading-switch sharing, same
dual-strategy entry/exit dispatch end to end. Primary Base is checked
SECOND in the priority chain (right after power_play, before
minervini_vcp_livermore) since its PFnet (2.069) ranks just above
Livermore's own (2.043); content of the OHLCV fixture doesn't matter for
most tests here since primary_base_entry_signal is monkeypatched directly,
same convention the Livermore tests use."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import numpy as np
import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _flat_df(n=300, price=100.0):
    return pd.DataFrame({
        "Open": np.full(n, price), "High": np.full(n, price + 0.5), "Low": np.full(n, price - 0.5),
        "Close": np.full(n, price), "Volume": np.full(n, 1000.0),
        "Date": pd.date_range("2023-01-01", periods=n, freq="B"),
    })


def test_no_separate_primary_base_switch_exists():
    # Explicit standing rule: only one manual real-trading kill switch.
    assert not hasattr(main, "is_real_primary_base_trading_enabled")


def test_primary_base_tag_maps_to_the_correct_registry_entry_and_is_viable():
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["primary_base"] == "primary_base"
    assert main._is_strategy_viable_for_real_money("primary_base") is True


def test_run_swing_scan_opens_a_primary_base_position_when_the_signal_fires(monkeypatch):
    _fresh_db()
    df = _flat_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["PRIMARYBASE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(
        main, "primary_base_entry_signal",
        lambda d: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0},
    )
    real_entry_calls = []
    monkeypatch.setattr(
        main, "_maybe_place_real_swing_entry",
        lambda conn, symbol, qty, entry_price, stop_loss, strategy: real_entry_calls.append(strategy),
    )

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'PRIMARYBASE.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "primary_base"
        assert row["atr_at_entry"] == 2.0
        assert row["running_max_close"] == row["entry_price"]
    assert real_entry_calls == ["primary_base"]


def test_run_swing_scan_falls_through_to_gap_and_go_when_primary_base_does_not_fire(monkeypatch):
    _fresh_db()
    df = _flat_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["NOPRIMARYBASE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(main, "primary_base_entry_signal", lambda d: None)
    monkeypatch.setattr(
        main, "gap_and_go_entry_signal",
        lambda d: {"entry_price": 100.0, "stop_loss": 90.0, "gap_low": 95.0},
    )

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'NOPRIMARYBASE.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "gap_and_go"


def test_run_swing_scan_prefers_primary_base_over_livermore_on_the_same_symbol(monkeypatch):
    _fresh_db()
    df = _flat_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["BOTHFIRE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(
        main, "primary_base_entry_signal",
        lambda d: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0},
    )
    monkeypatch.setattr(
        main, "minervini_vcp_entry_signal_livermore_confirmed",
        lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0},
    )

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'BOTHFIRE.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "primary_base"


def test_run_swing_scan_exits_a_primary_base_position_using_the_shared_chandelier_exit(monkeypatch):
    _fresh_db()
    df = _flat_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["EXITPRIMARYBASE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    exit_mirror_calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_exit", lambda conn, symbol, reason=None: exit_mirror_calls.append(symbol))

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('EXITPRIMARYBASE.NS', 'primary_base', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 182.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "minervini_vcp_exit_reason", lambda d, entry_day, stop, atr, running_max: ("trail_stop_hit", 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'EXITPRIMARYBASE.NS'").fetchone()
        assert row is None
        trade = conn.execute("SELECT * FROM trades WHERE symbol = 'EXITPRIMARYBASE.NS' AND action = 'sell'").fetchone()
        assert trade is not None
        assert exit_mirror_calls == ["EXITPRIMARYBASE.NS"]


def test_run_swing_scan_updates_primary_base_running_max_close_without_exiting(monkeypatch):
    _fresh_db()
    df = _flat_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["HOLDPRIMARYBASE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('HOLDPRIMARYBASE.NS', 'primary_base', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 150.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "minervini_vcp_exit_reason", lambda d, entry_day, stop, atr, running_max: (None, 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'HOLDPRIMARYBASE.NS'").fetchone()
        assert row is not None
        assert row["running_max_close"] == 182.0


def test_trade_thesis_has_a_primary_base_entry():
    # Part of the "daily tracking" requirement: every live strategy must
    # have its own thesis paragraph, not silently fall through to the
    # generic default.
    assert "primary_base" in main._TRADE_THESIS_COMPONENTS
    thesis = main._build_trade_thesis("primary_base", 100.0, 90.0, None, True)
    assert "Primary Base" in thesis
    assert "actively tracking" in thesis


def test_real_primary_base_entry_mirror_proceeds_with_real_gate_and_switch_on():
    # End-to-end: the shared swing switch AND the PFnet gate both actually
    # allow this one through.
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
    try:
        mocks = [p.start() for p in patches]
        mock_entry = mocks[4]
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "primary_base")
        # The real order actually got placed - confirms the PFnet gate and
        # the shared swing switch both let primary_base through end to end,
        # not blocked as "skipped_strategy_not_viable" the way a genuinely
        # non-viable strategy would be (see test_pfnet_real_money_gate.py's
        # own blocked-case tests for that contrast).
        assert mock_entry.call_count == 1
    finally:
        for p in patches:
            p.stop()
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
