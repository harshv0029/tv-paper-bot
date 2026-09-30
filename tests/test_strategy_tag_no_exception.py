"""Tests for the 2026-09-30 "strategy name for all entered trade...
without exception" fix - the exact two rows repeatedly flagged on the
dashboard (a paper OPEN position and a bot-tracked real position with a
NULL strategy column) never actually got fixed across several earlier,
adjacent fixes this session (the /strategy-info endpoint, the
kotak_untracked recovery). This closes those two specific gaps plus the
same gap in /real-trades-today's whole-account closed-trade view.

Run: pytest tests/test_strategy_tag_no_exception.py -v
"""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---- _watchlist_default_strategy_tag: pure classification ------------------

def test_defaults_to_universal_score_when_no_strategy_key_present():
    assert main._watchlist_default_strategy_tag({}) == "orb-universal-score"


def test_orb_breakout_uses_its_own_minutes_and_sma_params():
    cfg = {"strategy": "orb_breakout", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21}
    assert main._watchlist_default_strategy_tag(cfg) == "orb-15m-sma9-21"


def test_bullish_engulfing_uses_its_own_trend_sma():
    cfg = {"strategy": "bullish_engulfing", "trend_sma": 50}
    assert main._watchlist_default_strategy_tag(cfg) == "orb-bullish-engulfing-trend50"


def test_explicit_universal_score_matches_the_default():
    assert main._watchlist_default_strategy_tag({"strategy": "universal_score"}) == "orb-universal-score"


# ---- /daily-summary: the OPEN paper row's strategy fallback ----------------

def _insert_open_paper_position(conn, symbol="RELIANCE.NS"):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
        "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
        "(?, ?, 'long', 100.0, 95.0, 95.0, 115.0, 5, ?, 1.0, '5m')",
        (symbol, main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
    )
    conn.commit()


def test_open_position_falls_back_to_watchlist_strategy_when_no_matching_trade_row():
    # The exact live gap: a fresh OPEN paper position with no matching buy
    # row yet in `trades` (or one that predates strategy tracking) must
    # still show a real strategy name, not "no strategy tag recorded".
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
    result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    pos = next(p for p in result["open_positions"] if p["symbol"] == "RELIANCE.NS")
    assert pos["strategy"] == "orb-universal-score"


def test_open_position_prefers_the_real_trades_table_strategy_over_the_watchlist_default():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_open_paper_position(conn)
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy) "
            "VALUES (?, 'RELIANCE.NS', 'buy', 5, 100.0, 1.0, 'orb-bullish-engulfing-trend50')",
            (main.time.time(),),
        )
        conn.commit()
    result = main.daily_summary(capital=400000, daily_risk_pct=2.0)
    pos = next(p for p in result["open_positions"] if p["symbol"] == "RELIANCE.NS")
    assert pos["strategy"] == "orb-bullish-engulfing-trend50"


# ---- /real-open-positions: bot_tracked rows with a NULL strategy column ----

def test_bot_tracked_long_with_null_strategy_recovers_from_real_trades():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES ('RELIANCE.NS', 'RELIANCE-EQ', 5, 100.0, 'E1', ?, ?)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.execute(
            "INSERT INTO real_trades (ts, day, symbol, kotak_trading_symbol, side, qty, "
            "price_est, notional_inr, status, order_id, detail, strategy) "
            "VALUES (?, ?, 'RELIANCE.NS', 'RELIANCE-EQ', 'B', 5, 100.0, 500.0, 'confirmed', 'E1', NULL, 'orb-universal-score')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert pos["strategy"] == "orb-universal-score"


def test_bot_tracked_long_with_null_strategy_and_no_trade_log_falls_back_to_watchlist():
    # Adopted/backfilled with no known paper origin AND no real_trades
    # match either - the last-resort fallback still fires, never a blank.
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES ('RELIANCE.NS', 'RELIANCE-EQ', 5, 100.0, 'E1', ?, ?)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert pos["strategy"] == "orb-universal-score"


def test_bot_tracked_short_with_null_strategy_recovers_from_real_trades():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, strategy) VALUES "
            "('TCS.NS', 'TCS-EQ', 1, 2100.0, 'E1', ?, ?, NULL)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.execute(
            "INSERT INTO real_trades (ts, day, symbol, kotak_trading_symbol, side, qty, "
            "price_est, notional_inr, status, order_id, detail, strategy) "
            "VALUES (?, ?, 'TCS.NS', 'TCS-EQ', 'S', 1, 2100.0, 2100.0, 'confirmed', 'E1', NULL, 'range_short_staged_ladder')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = next(p for p in result["open_real_positions"] if p["symbol"] == "TCS.NS")
    assert pos["strategy"] == "range_short_staged_ladder"


def test_bot_tracked_short_with_null_strategy_and_no_trade_log_falls_back_to_watchlist():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, strategy) VALUES "
            "('TCS.NS', 'TCS-EQ', 1, 2100.0, 'E1', ?, ?, NULL)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = next(p for p in result["open_real_positions"] if p["symbol"] == "TCS.NS")
    assert pos["strategy"] == "orb-universal-score"


# ---- /real-trades-today: the whole-account closed-trade view --------------

def test_closed_trade_recovers_strategy_from_real_trades_log():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_trades (ts, day, symbol, kotak_trading_symbol, side, qty, "
            "price_est, notional_inr, status, order_id, detail, strategy) "
            "VALUES (?, ?, 'RELIANCE.NS', 'RELIANCE-EQ', 'B', 5, 100.0, 500.0, 'confirmed', 'E1', NULL, 'orb-universal-score')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    fake_positions = {"data": [{
        "trdSym": "RELIANCE-EQ", "exSeg": "nse_cm", "flBuyQty": "5", "flSellQty": "5",
        "buyAmt": "500.0", "sellAmt": "520.0",
        "hsUpTm": main.ist_now().strftime("%Y/%m/%d") + " 10:00:00",
    }]}
    with patch("kotak_neo.positions", return_value=fake_positions):
        main._refresh_real_trades_cache()
        result = main.get_real_trades_today()
    assert result["trades"][0]["strategy"] == "orb-universal-score"


def test_closed_trade_with_no_matching_bot_record_stays_honestly_labeled():
    _fresh_db()
    fake_positions = {"data": [{
        "trdSym": "SOMESTOCK-EQ", "exSeg": "nse_cm", "flBuyQty": "1", "flSellQty": "1",
        "buyAmt": "100.0", "sellAmt": "110.0",
        "hsUpTm": main.ist_now().strftime("%Y/%m/%d") + " 10:00:00",
    }]}
    with patch("kotak_neo.positions", return_value=fake_positions):
        main._refresh_real_trades_cache()
        result = main.get_real_trades_today()
    assert result["trades"][0]["strategy"] == "real (Kotak)"
