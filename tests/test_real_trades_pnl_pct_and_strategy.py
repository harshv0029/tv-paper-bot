"""Tests for the real-trades-view PnL% and strategy/algo attribution
(2026-09-21, explicit user instruction: "In the today's real trades I
can't see pnL % in each row. Update it. It also does not mention which
strategy or algo used for that trade enter so mention that"):
  - /real-trades-today (whole-account Kotak aggregate): pnl_pct added,
    strategy stays the honest "real (Kotak)" placeholder (this view
    includes manually-placed trades too - genuinely unattributable).
  - /real-trades-today-bot-only (this app's own orders): pnl_pct added,
    strategy now reads the REAL strategy_tag the entry was placed under
    (real_trades.strategy, set at entry time from the matched paper
    signal), not a generic constant.
  - _maybe_place_real_entry: threads the paper signal's own strategy
    into both real_positions.strategy and real_trades.strategy."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---- /real-trades-today-bot-only -------------------------------------------

def _insert_real_trade(conn, symbol, side, qty, price_est, ts, strategy=None, order_id=None):
    conn.execute(
        "INSERT INTO real_trades (ts, day, symbol, kotak_trading_symbol, side, qty, price_est, "
        "notional_inr, status, order_id, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)",
        (ts, main.ist_now().strftime("%Y-%m-%d"), symbol, f"{symbol.split('.')[0]}-EQ", side,
         qty, price_est, qty * price_est, order_id, strategy),
    )
    conn.commit()


def test_bot_only_closed_trade_reports_the_real_entry_strategy():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_trade(conn, "TESTSTOCK.NS", "B", 10, 100.0, main.time.time(), strategy="universal_score")
        _insert_real_trade(conn, "TESTSTOCK.NS", "S", 10, 110.0, main.time.time() + 60)
    result = main.get_real_trades_today_bot_only()
    assert len(result["closed_trades"]) == 1
    assert result["closed_trades"][0]["strategy"] == "universal_score"


def test_bot_only_closed_trade_pnl_pct_matches_pnl_over_invested():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_trade(conn, "TESTSTOCK.NS", "B", 10, 100.0, main.time.time(), strategy="bullish_engulfing")
        _insert_real_trade(conn, "TESTSTOCK.NS", "S", 10, 110.0, main.time.time() + 60)
    result = main.get_real_trades_today_bot_only()
    trade = result["closed_trades"][0]
    assert trade["pnl_inr"] == 100.0  # (110-100)*10
    assert trade["pnl_pct"] == 10.0  # 100 / (100*10) * 100


def test_bot_only_closed_trade_strategy_falls_back_to_unknown_when_never_set():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_trade(conn, "TESTSTOCK.NS", "B", 10, 100.0, main.time.time(), strategy=None)
        _insert_real_trade(conn, "TESTSTOCK.NS", "S", 10, 105.0, main.time.time() + 60)
    result = main.get_real_trades_today_bot_only()
    assert result["closed_trades"][0]["strategy"] == "unknown"


# ---- /real-trades-today (whole-account) ------------------------------------

def test_whole_account_trade_gets_a_pnl_pct_and_stays_honestly_unattributed():
    _fresh_db()
    canned = [{
        "symbol": "TESTSTOCK.NS", "exit_time_utc": main.time.time(),
        "entry_price_native": 100.0, "exit_price_native": 120.0,
        "qty": 5, "pnl_inr": 100.0,
    }]
    with patch("main.get_real_trades_today_list", return_value=canned):
        result = main.get_real_trades_today()
    trade = result["trades"][0]
    assert trade["pnl_pct"] == 20.0  # 100 / (100*5) * 100
    assert trade["strategy"] == "real (Kotak)"


def test_whole_account_trade_pnl_pct_none_when_invested_is_zero():
    _fresh_db()
    canned = [{
        "symbol": "TESTSTOCK.NS", "exit_time_utc": main.time.time(),
        "entry_price_native": 0.0, "exit_price_native": 5.0,
        "qty": 0, "pnl_inr": 0.0,
    }]
    with patch("main.get_real_trades_today_list", return_value=canned):
        result = main.get_real_trades_today()
    assert result["trades"][0]["pnl_pct"] is None


# ---- _maybe_place_real_entry threads strategy through -----------------------

def _enable_real_trading(conn):
    conn.execute(
        "INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
        "VALUES (1, 1, ?, 'test', 'test')", (main.time.time(),),
    )
    conn.commit()


def _insert_paper_signal_with_strategy(conn, symbol, strategy, qty=10, stop_loss=90.0, target=130.0):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval, strategy) "
        "VALUES (?, '2026-09-21', 'long', 100.0, ?, ?, ?, ?, ?, 1.0, '5m', ?)",
        (symbol, stop_loss, stop_loss, target, qty, main.time.time(), strategy),
    )
    conn.commit()


def test_real_entry_copies_the_paper_signals_strategy_onto_the_real_position():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable_real_trading(conn)
            _insert_paper_signal_with_strategy(conn, "TESTSTOCK.NS", "universal_score")
            with patch("kotak_live_feed.get_live_ticks",
                       return_value={"TESTSTOCK.NS": {"ltp": 100.0, "trading_symbol": "TESTSTOCK-EQ"}}), \
                 patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
                 patch("main.get_runtime_setting", return_value=1000000.0), \
                 patch("main._real_today_spent_inr", return_value=0.0), \
                 patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
                 patch("kotak_real_orders.place_real_entry",
                       return_value={"ok": True, "qty": 10, "fill_price": 100.0, "order_id": "E1",
                                     "fill_price_confirmed": True}), \
                 patch("kotak_real_orders.place_real_stop_loss",
                       return_value={"ok": True, "order_id": "SL1", "trigger_price": 90.0}), \
                 patch("kotak_real_orders.place_real_target",
                       return_value={"ok": True, "order_id": "T1", "target_price": 130.0}):
                main._maybe_place_real_entry(conn, "TESTSTOCK.NS")
            position = dict(conn.execute(
                "SELECT * FROM real_positions WHERE symbol = 'TESTSTOCK.NS'"
            ).fetchone())
            trade = dict(conn.execute(
                "SELECT * FROM real_trades WHERE symbol = 'TESTSTOCK.NS' AND side = 'B'"
            ).fetchone())
    finally:
        del os.environ["REAL_TRADING_ENABLED"]
    assert position["strategy"] == "universal_score"
    assert trade["strategy"] == "universal_score"
