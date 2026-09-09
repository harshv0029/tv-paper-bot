"""Tests for GET /real-open-positions (2026-09-09, explicit user finding:
the /trade-view dashboard showed "No live positions or real trades
today" while Kotak's own account had a genuinely open real position
(MEDICAMEQ.NS) - trade-view.html had no data source for currently-OPEN
real positions at all, only open PAPER positions and CLOSED real trades.
See main.py's get_real_open_positions docstring for the full root
cause."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_returns_empty_when_no_real_positions():
    _fresh_db()
    result = main.get_real_open_positions()
    assert result == {"open_real_positions": [], "count": 0}


def test_includes_an_untracked_kotak_position_not_in_real_positions():
    # 2026-09-09, explicit user finding: Kotak's own Positions tab showed
    # 2 more open positions (NEWGEN, SANDUMA) than this endpoint did -
    # "Why not in sync still? I want them to be in sync with at max 10
    # second delay."
    _fresh_db()
    fake_kotak_neo = MagicMock()
    fake_kotak_neo.positions.return_value = {
        "data": [
            {"exSeg": "nse_cm", "trdSym": "NEWGEN-EQ", "flBuyQty": "1", "flSellQty": "0", "buyAmt": "515.70"},
        ],
    }
    fake_df = pd.DataFrame({"Close": [520.0]})
    with patch.dict("sys.modules", {"kotak_neo": fake_kotak_neo}), patch("main.fetch_ohlc", return_value=fake_df):
        result = main.get_real_open_positions()

    assert result["count"] == 1
    pos = result["open_real_positions"][0]
    assert pos["symbol"] == "NEWGEN.NS"
    assert pos["kotak_trading_symbol"] == "NEWGEN-EQ"
    assert pos["qty"] == 1
    assert pos["entry_price"] == 515.7
    assert pos["source"] == "kotak_untracked"
    assert pos["target_status"] == "not_bot_managed"
    assert pos["current_price"] == 520.0
    assert pos["unrealized_pnl_inr"] == pytest.approx(4.3, abs=1e-9)


def test_does_not_duplicate_an_already_bot_tracked_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("MEDICAMEQ.NS", "MEDICAMEQ-EQ", 3, 291.4, "1", 1788931043.9, "2026-09-09"),
        )
        conn.commit()
    fake_kotak_neo = MagicMock()
    fake_kotak_neo.positions.return_value = {
        "data": [
            {"exSeg": "nse_cm", "trdSym": "MEDICAMEQ-EQ", "flBuyQty": "3", "flSellQty": "0", "buyAmt": "874.20"},
        ],
    }
    with patch.dict("sys.modules", {"kotak_neo": fake_kotak_neo}), \
         patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    assert result["count"] == 1
    assert result["open_real_positions"][0]["source"] == "bot_tracked"


def test_kotak_fetch_failure_still_returns_bot_tracked_rows():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("MEDICAMEQ.NS", "MEDICAMEQ-EQ", 3, 291.4, "1", 1788931043.9, "2026-09-09"),
        )
        conn.commit()
    fake_kotak_neo = MagicMock()
    fake_kotak_neo.positions.side_effect = Exception("Kotak down")
    with patch.dict("sys.modules", {"kotak_neo": fake_kotak_neo}), \
         patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()  # must not raise
    assert result["count"] == 1
    assert result["open_real_positions"][0]["symbol"] == "MEDICAMEQ.NS"


def test_computes_current_price_and_unrealized_pnl_for_an_open_position():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("MEDICAMEQ.NS", "MEDICAMEQ-EQ", 3, 291.4, "260909000214760", 1788931043.9, "2026-09-09"),
        )
        conn.commit()

    fake_df = pd.DataFrame({"Close": [295.0, 297.5]})
    with patch("main.fetch_ohlc", return_value=fake_df):
        result = main.get_real_open_positions()

    assert result["count"] == 1
    pos = result["open_real_positions"][0]
    assert pos["symbol"] == "MEDICAMEQ.NS"
    assert pos["current_price"] == 297.5
    assert pos["invested_inr"] == 874.2  # 291.4 * 3
    assert pos["unrealized_pnl_inr"] == 18.3  # (297.5 - 291.4) * 3, rounded
    assert pos["unrealized_pnl_pct"] > 0
    # No target_order_id, no real_t1_restricted row, no failed target
    # event - nothing has been attempted yet.
    assert pos["target_status"] == "not_yet_attempted"


def test_target_status_resting_when_a_real_target_order_exists():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, target_order_id, target_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("RELIANCE.NS", "RELIANCE-EQ", 5, 1300.0, "1", 1788931043.9, "2026-09-09", "9999", 1339.0),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert pos["target_price"] == 1339.0
    assert pos["target_status"] == "resting"
    assert pos["target_status_detail"] is None


def test_target_status_blocked_when_symbol_is_t1_restricted_today():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, target_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("MEDICAMEQ.NS", "MEDICAMEQ-EQ", 3, 291.4, "1", 1788931043.9, "2026-09-09", 300.13),
        )
        main._flag_if_t1_restricted(
            conn, "MEDICAMEQ.NS",
            "Insufficient quantity held for this order... Selling Trade-to-Trade stocks on the "
            "same day of purchase is not allowed.",
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert pos["target_price"] == 300.13
    assert pos["target_status"] == "blocked"
    assert "Trade-to-Trade" in pos["target_status_detail"]


def test_target_status_failed_when_a_non_t1_rejection_is_logged():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, target_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("TCS.NS", "TCS-EQ", 1, 2300.0, "1", 1788931043.9, "2026-09-09", 2350.0),
        )
        main._log_real_order_event(
            conn, "TCS.NS", "target", "failed", kotak_trading_symbol="TCS-EQ",
            detail="order rejected: some other reason",
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert pos["target_status"] == "failed"
    assert pos["target_status_detail"] == "order rejected: some other reason"


def test_current_price_none_when_fetch_ohlc_fails_not_a_crash():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("MEDICAMEQ.NS", "MEDICAMEQ-EQ", 3, 291.4, "260909000214760", 1788931043.9, "2026-09-09"),
        )
        conn.commit()

    with patch("main.fetch_ohlc", side_effect=Exception("yahoo down")):
        result = main.get_real_open_positions()

    pos = result["open_real_positions"][0]
    assert pos["current_price"] is None
    assert pos["unrealized_pnl_inr"] is None
    assert pos["unrealized_pnl_pct"] is None
    # invested_inr must still compute - it doesn't depend on a live price
    assert pos["invested_inr"] == 874.2
