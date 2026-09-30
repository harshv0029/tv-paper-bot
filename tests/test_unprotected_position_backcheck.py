"""Tests for the 2026-09-30 MFSL.NS-incident backcheck: a genuinely
bot-placed real long position (MFSL.NS) sat open with ZERO stop-loss
order anywhere at Kotak - its real_positions row had been lost, so no
part of this app's own per-tick logic (which only ever manages rows it
still has a tracking row for) ever saw it needed protecting. Explicit
user instruction: "Make sure that this does not repeat... Put some
caveat... Do some back check during live market or live trades."

_find_unprotected_open_positions checks EVERY open Kotak position (long
or short, tracked or not) against Kotak's own order book directly, so it
catches this exact failure class regardless of which local table lost
track of the position. Persisted via real_protection_snapshot so
/real-protection-status can serve a cheap, always-on dashboard banner
without hitting Kotak on every page load.

Run: pytest tests/test_unprotected_position_backcheck.py -v
"""
import os
import tempfile
import time
from contextlib import closing

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


# ---- _find_unprotected_open_positions: pure classification ----------------

def test_long_position_with_a_live_resting_sl_is_protected():
    kotak_open = {"MFSL-EQ": {"qty": 1, "is_short": False}}
    order_rows = [
        {"trdSym": "MFSL-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending"},
    ]
    assert main._find_unprotected_open_positions(kotak_open, order_rows) == []


def test_long_position_with_no_sl_order_at_all_is_unprotected():
    # The exact MFSL.NS shape: only a completed BUY, no second order.
    kotak_open = {"MFSL-EQ": {"qty": 1, "is_short": False}}
    order_rows = [
        {"trdSym": "MFSL-EQ", "trnsTp": "B", "prcTp": "L", "ordSt": "complete"},
    ]
    result = main._find_unprotected_open_positions(kotak_open, order_rows)
    assert result == [{"kotak_trading_symbol": "MFSL-EQ", "qty": 1, "is_short": False}]


def test_short_position_needs_a_buy_side_sl_not_a_sell_side_one():
    # A SELL-side SL on a short's own symbol is the ENTRY leg's own SL
    # ancestry confusion risk - must not be mistaken for the short's own
    # protective BUY-side stop.
    kotak_open = {"TCS-EQ": {"qty": 1, "is_short": True}}
    order_rows = [
        {"trdSym": "TCS-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending"},
    ]
    result = main._find_unprotected_open_positions(kotak_open, order_rows)
    assert result == [{"kotak_trading_symbol": "TCS-EQ", "qty": 1, "is_short": True}]


def test_short_position_with_a_live_buy_side_sl_is_protected():
    kotak_open = {"TCS-EQ": {"qty": 1, "is_short": True}}
    order_rows = [
        {"trdSym": "TCS-EQ", "trnsTp": "B", "prcTp": "SL", "ordSt": "trigger pending"},
    ]
    assert main._find_unprotected_open_positions(kotak_open, order_rows) == []


def test_sl_m_counts_as_a_protective_order_too():
    kotak_open = {"HYUNDAI-EQ": {"qty": 1, "is_short": False}}
    order_rows = [
        {"trdSym": "HYUNDAI-EQ", "trnsTp": "S", "prcTp": "SL-M", "ordSt": "trigger pending"},
    ]
    assert main._find_unprotected_open_positions(kotak_open, order_rows) == []


def test_a_terminal_status_sl_does_not_count_as_live():
    # A rejected/cancelled/expired SL is no different from having none.
    for terminal_status in ("complete", "rejected", "cancelled", "expired"):
        kotak_open = {"X-EQ": {"qty": 1, "is_short": False}}
        order_rows = [
            {"trdSym": "X-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": terminal_status},
        ]
        result = main._find_unprotected_open_positions(kotak_open, order_rows)
        assert result == [{"kotak_trading_symbol": "X-EQ", "qty": 1, "is_short": False}], terminal_status


def test_never_gated_by_the_bot_order_tag_unlike_adopt():
    # Unlike adopt's entry-matching, the protection check does NOT filter
    # by ordSrc/algId - a manually-placed position with no SL is still
    # real, unprotected money and still belongs in the alert.
    kotak_open = {"MANUAL-EQ": {"qty": 1, "is_short": False}}
    order_rows = [
        {"trdSym": "MANUAL-EQ", "trnsTp": "B", "prcTp": "L", "ordSt": "complete",
         "ordSrc": "ADMINCPPAPI_MOB", "algId": "NA"},
    ]
    result = main._find_unprotected_open_positions(kotak_open, order_rows)
    assert result == [{"kotak_trading_symbol": "MANUAL-EQ", "qty": 1, "is_short": False}]


def test_multiple_open_positions_only_the_unprotected_ones_are_returned():
    kotak_open = {
        "MFSL-EQ": {"qty": 1, "is_short": False},
        "TCS-EQ": {"qty": 1, "is_short": True},
    }
    order_rows = [
        {"trdSym": "TCS-EQ", "trnsTp": "B", "prcTp": "SL", "ordSt": "trigger pending"},
    ]
    result = main._find_unprotected_open_positions(kotak_open, order_rows)
    assert result == [{"kotak_trading_symbol": "MFSL-EQ", "qty": 1, "is_short": False}]


def test_empty_open_positions_returns_empty_list():
    assert main._find_unprotected_open_positions({}, []) == []


# ---- /real-protection-status: cheap read of the persisted snapshot --------

def test_status_endpoint_reports_stale_true_when_never_checked():
    _fresh_db()
    result = main.real_protection_status()
    assert result == {"checked_at": None, "unprotected_positions": [], "stale": True}


def test_status_endpoint_serves_a_fresh_snapshot_as_not_stale():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_protection_snapshot (id, checked_at, unprotected_json) VALUES (1, ?, ?)",
            (time.time(), '[{"kotak_trading_symbol": "MFSL-EQ", "qty": 1, "is_short": false}]'),
        )
        conn.commit()
    result = main.real_protection_status()
    assert result["stale"] is False
    assert result["unprotected_positions"] == [{"kotak_trading_symbol": "MFSL-EQ", "qty": 1, "is_short": False}]


def test_status_endpoint_reports_stale_true_when_last_check_is_old():
    # >15 minutes old - the dashboard must treat this as "unknown", never
    # as a silent all-clear (exactly the class of gap that let MFSL go
    # unnoticed).
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_protection_snapshot (id, checked_at, unprotected_json) VALUES (1, ?, ?)",
            (time.time() - 1000, "[]"),
        )
        conn.commit()
    result = main.real_protection_status()
    assert result["stale"] is True
