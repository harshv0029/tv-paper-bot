"""Tests for wiring Minervini VCP into the live swing scan as a second
strategy alongside gap_and_go (2026-09-29, explicit user instruction after
the full-universe real-function validation replay - PFnet 0.908,
docs/MINERVINI_VCP_RESEARCH_LOG.md). Covers: Minervini VCP's real-order
mirror sharing gap_and_go's EXISTING is_real_swing_trading_enabled switch
rather than getting its own (a separate REAL_MINERVINI_VCP_TRADING_ENABLED
switch was built, then explicitly reverted same-day per user instruction -
"I just want one switch for manual closure of live trading... not many
trading switches which I will not able to track" - see CLAUDE.md's "ask
before creating any new real-trading switch" thumb rule), and
_run_swing_scan's two-pass RS-percentile computation + dual-strategy
entry/exit dispatch end to end."""
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


# ---- Minervini VCP shares gap_and_go's existing real-trading switch ---------

def test_no_separate_minervini_switch_exists():
    # Explicit user instruction (2026-09-29): only one manual real-trading
    # kill switch, not a growing set the user can't track. Locks down that
    # a separate is_real_minervini_vcp_trading_enabled never comes back.
    assert not hasattr(main, "is_real_minervini_vcp_trading_enabled")
    assert not hasattr(main, "_is_real_swing_trading_enabled_for_strategy")


def test_real_minervini_entry_mirror_gated_by_the_shared_swing_switch():
    _fresh_db()
    os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "minervini_vcp")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is None  # switch off (default) - no real order for either strategy
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)


def test_real_minervini_entry_mirror_proceeds_once_the_shared_switch_is_on():
    # 2026-09-30: minervini_vcp's own registered PFnet (0.908) is below the
    # real-money floor (see _is_strategy_viable_for_real_money), so it's
    # patched True here to keep this test's actual subject - the shared
    # swing kill switch - isolated from that separate, later-added gate.
    # See tests/test_pfnet_real_money_gate.py for the gate's own coverage,
    # including the regression case that minervini_vcp specifically is
    # blocked when that patch isn't in place.
    _fresh_db()
    os.environ["REAL_SWING_TRADING_ENABLED"] = "YES"  # same switch gap_and_go already uses
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
        patch("main._is_strategy_viable_for_real_money", return_value=True),
    ]
    started = [p.start() for p in patches]
    try:
        with closing(main.get_db()) as conn:
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "minervini_vcp")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is not None
            assert row["strategy"] == "minervini_vcp"
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        for p in patches:
            p.stop()


# ---- _run_swing_scan two-pass dispatch ---------------------------------------

def _minervini_breakout_df():
    """Same deterministic fixture as tests/test_minervini_vcp.py: a
    qualifying uptrend + a genuine tightening VCP base ending in a
    breakout bar with a volume surge - does NOT gap up, so gap_and_go
    never fires on it."""
    close1 = np.linspace(50.0, 150.0, 220)
    verts_x = [220, 240, 252, 264, 276, 298, 299]
    verts_y = [150.0, 180.0, 140.0, 175.0, 166.25, 170.0, 182.0]
    tail_idx = np.arange(220, 300)
    mid_tail = np.interp(tail_idx, verts_x, verts_y)
    mid = np.concatenate([close1, mid_tail])
    high = mid + 0.3
    low = mid - 0.3
    close = mid.copy()
    open_ = close.copy()  # never gaps: today's Open == yesterday's Close pattern, gap_and_go needs a real gap
    volume = np.full(300, 1000.0)
    volume[-1] = 5000.0
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume, "Date": dates})


def _flat_no_signal_df(n=300, price=100.0):
    return pd.DataFrame({
        "Open": np.full(n, price), "High": np.full(n, price + 0.5), "Low": np.full(n, price - 0.5),
        "Close": np.full(n, price), "Volume": np.full(n, 1000.0),
        "Date": pd.date_range("2023-01-01", periods=n, freq="B"),
    })


def test_run_swing_scan_opens_a_minervini_position_when_gap_and_go_does_not_fire(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["VCPTEST.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    # 2026-10-01: primary_base is checked earlier in the priority chain and
    # this fixture's genuine pullback-then-breakout shape can also satisfy
    # it - neutralize so this test still isolates the minervini_vcp fallback
    # it was written to check (see tests/test_primary_base_live_wiring.py
    # for primary_base's own wiring coverage).
    monkeypatch.setattr(main, "primary_base_entry_signal", lambda d: None)

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'VCPTEST.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "minervini_vcp"
        assert row["atr_at_entry"] is not None and row["atr_at_entry"] > 0
        assert row["running_max_close"] == row["entry_price"]
        assert row["gap_low"] is None


def test_run_swing_scan_no_signal_symbol_opens_nothing(monkeypatch):
    _fresh_db()
    df = _flat_no_signal_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["FLAT.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'FLAT.NS'").fetchone()
        assert row is None


def test_run_swing_scan_prefers_gap_and_go_over_minervini_on_the_same_symbol(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["BOTH.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(main, "primary_base_entry_signal", lambda d: None)  # see VCPTEST.NS test above
    # Force both signals to fire on the same symbol/day - gap_and_go must win.
    monkeypatch.setattr(main, "gap_and_go_entry_signal", lambda d: {"entry_price": 100.0, "stop_loss": 90.0, "gap_low": 95.0})
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0})

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'BOTH.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "gap_and_go"


def test_run_swing_scan_updates_running_max_close_without_exiting(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["HOLD.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('HOLD.NS', 'minervini_vcp', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 150.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "minervini_vcp_exit_reason", lambda d, entry_day, stop, atr, running_max: (None, 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'HOLD.NS'").fetchone()
        assert row is not None
        assert row["running_max_close"] == 182.0


def test_run_swing_scan_exits_a_minervini_position_and_calls_real_exit_mirror(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["EXIT.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    exit_mirror_calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_exit", lambda conn, symbol: exit_mirror_calls.append(symbol))

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('EXIT.NS', 'minervini_vcp', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 182.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "minervini_vcp_exit_reason", lambda d, entry_day, stop, atr, running_max: ("trail_stop_hit", 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'EXIT.NS'").fetchone()
        assert row is None
        trade = conn.execute("SELECT * FROM trades WHERE symbol = 'EXIT.NS' AND action = 'sell'").fetchone()
        assert trade is not None
        assert exit_mirror_calls == ["EXIT.NS"]


# ---- minervini_vcp_livermore: 2026-09-30, "Wire the viable ones" -----------
# (PFnet 2.043, clears PFNET_LIVE_FLOOR by a wide margin - checked BEFORE
# the plain base minervini_vcp entry, which stays below the floor at 0.908).

def test_livermore_tag_maps_to_the_correct_registry_entry_and_is_viable():
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["minervini_vcp_livermore"] == "minervini_vcp_livermore_confirmed"
    assert main._is_strategy_viable_for_real_money("minervini_vcp_livermore") is True
    # The plain base entry stays blocked - this wiring must not accidentally
    # also flip that one viable.
    assert main._is_strategy_viable_for_real_money("minervini_vcp") is False


def test_run_swing_scan_opens_a_livermore_position_when_the_filter_fires(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()  # content doesn't matter - livermore signal is monkeypatched directly
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["LIVERMORE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(main, "primary_base_entry_signal", lambda d: None)  # see VCPTEST.NS test above
    monkeypatch.setattr(
        main, "minervini_vcp_entry_signal_livermore_confirmed",
        lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0},
    )
    real_entry_calls = []
    monkeypatch.setattr(
        main, "_maybe_place_real_swing_entry",
        lambda conn, symbol, qty, entry_price, stop_loss, strategy: real_entry_calls.append(strategy),
    )

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'LIVERMORE.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "minervini_vcp_livermore"
        assert row["atr_at_entry"] == 2.0
        assert row["running_max_close"] == row["entry_price"]
    assert real_entry_calls == ["minervini_vcp_livermore"]


def test_run_swing_scan_falls_back_to_plain_minervini_when_livermore_does_not_fire(monkeypatch):
    # The exact base-entry fixture from the pre-existing test above - the
    # Livermore filter genuinely does not confirm on a single plain
    # breakout with no two-pullback structure, so this must still land as
    # "minervini_vcp", not silently stop firing at all.
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["PLAINVCP.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(main, "primary_base_entry_signal", lambda d: None)  # see VCPTEST.NS test above

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'PLAINVCP.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "minervini_vcp"


def test_run_swing_scan_prefers_livermore_over_plain_minervini_on_the_same_symbol(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["BOTHVCP.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    monkeypatch.setattr(main, "primary_base_entry_signal", lambda d: None)  # see VCPTEST.NS test above
    monkeypatch.setattr(
        main, "minervini_vcp_entry_signal_livermore_confirmed",
        lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0},
    )
    monkeypatch.setattr(
        main, "minervini_vcp_entry_signal",
        lambda d, rs_percentile=None: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 2.0},
    )

    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'BOTHVCP.NS'").fetchone()
        assert row is not None
        assert row["strategy"] == "minervini_vcp_livermore"


def test_run_swing_scan_exits_a_livermore_position_using_the_shared_chandelier_exit(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["EXITLIVERMORE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    exit_mirror_calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_exit", lambda conn, symbol: exit_mirror_calls.append(symbol))

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('EXITLIVERMORE.NS', 'minervini_vcp_livermore', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 182.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "minervini_vcp_exit_reason", lambda d, entry_day, stop, atr, running_max: ("trail_stop_hit", 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'EXITLIVERMORE.NS'").fetchone()
        assert row is None
        trade = conn.execute("SELECT * FROM trades WHERE symbol = 'EXITLIVERMORE.NS' AND action = 'sell'").fetchone()
        assert trade is not None
        assert exit_mirror_calls == ["EXITLIVERMORE.NS"]


def test_run_swing_scan_updates_livermore_running_max_close_without_exiting(monkeypatch):
    _fresh_db()
    df = _minervini_breakout_df()
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["HOLDLIVERMORE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)

    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
            "gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) "
            "VALUES ('HOLDLIVERMORE.NS', 'minervini_vcp_livermore', '2020-01-01', 150.0, 130.0, NULL, 10, 0, 1.0, 2.0, 150.0)"
        )
        conn.commit()
        monkeypatch.setattr(main, "minervini_vcp_exit_reason", lambda d, entry_day, stop, atr, running_max: (None, 182.0))

        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'HOLDLIVERMORE.NS'").fetchone()
        assert row is not None
        assert row["running_max_close"] == 182.0


def test_real_livermore_entry_mirror_proceeds_with_real_gate_and_switch_on():
    # End-to-end: the shared swing switch AND the PFnet gate both actually
    # allow this one through (unlike minervini_vcp/plain, see the blocked
    # regression test in test_pfnet_real_money_gate.py).
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
            main._maybe_place_real_swing_entry(conn, "TESTSTOCK.NS", 10, 100.0, 90.0, "minervini_vcp_livermore")
            row = conn.execute("SELECT * FROM real_positions_swing WHERE symbol = 'TESTSTOCK.NS'").fetchone()
            assert row is not None
            assert row["strategy"] == "minervini_vcp_livermore"
    finally:
        os.environ.pop("REAL_SWING_TRADING_ENABLED", None)
        for p in patches:
            p.stop()
