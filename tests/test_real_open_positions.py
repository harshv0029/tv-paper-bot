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
from unittest.mock import patch

import pandas as pd

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
