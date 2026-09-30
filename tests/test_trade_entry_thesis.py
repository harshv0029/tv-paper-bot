"""Tests for the 2026-09-30 "trade entry thesis" feature (explicit user
instruction): every open real position on the dashboard should carry one
paragraph answering, in plain language - why the trade was taken, its
entry price, its expected target (or why there isn't a fixed one), how
long it should stay open, when to expect closing it, what "the signal is
getting weak/unfavourable" means for that specific strategy, and whether
this app is actually tracking/managing it.

_build_trade_thesis is a pure function - every sentence it returns is
built from a strategy's own already-coded entry/exit rules
(_TRADE_THESIS_COMPONENTS), never invented commentary, so it can never
drift from what the position will actually do.

Run: pytest tests/test_trade_entry_thesis.py -v
"""
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


# ---- _build_trade_thesis: pure text generation -----------------------------

def test_answers_every_one_of_the_seven_questions_for_a_known_strategy():
    thesis = main._build_trade_thesis("orb-universal-score", 100.0, 95.0, 115.0, tracked=True)
    assert "entered because" in thesis  # why
    assert "Rs100.00" in thesis  # entry price
    assert "Rs115.00" in thesis  # target
    assert "INTRADAY" in thesis  # how long viable
    assert "3:14pm" in thesis  # when to expect close
    assert "trend_weakened" in thesis or "stop-loss is hit" in thesis  # weak-signal criterion
    assert "actively tracking" in thesis  # tracked or not


def test_no_fixed_target_is_stated_honestly_not_a_fabricated_number():
    thesis = main._build_trade_thesis("gap_and_go", 100.0, 90.0, None, tracked=True)
    assert "no fixed profit target" in thesis
    assert "The target is Rs" not in thesis


def test_untracked_position_says_so_plainly():
    thesis = main._build_trade_thesis("orb-universal-score", 100.0, 95.0, 115.0, tracked=False)
    assert "NOT actively tracking" in thesis
    assert "manage" in thesis.lower()


def test_no_stop_price_is_handled_without_crashing():
    thesis = main._build_trade_thesis("power_play", 100.0, None, None, tracked=True)
    assert "Rs100.00" in thesis
    assert isinstance(thesis, str) and len(thesis) > 0


def test_unknown_strategy_tag_falls_back_to_an_honest_default_not_a_crash():
    thesis = main._build_trade_thesis("some-unregistered-tag", 100.0, 90.0, None, tracked=True)
    assert "could not be identified" in thesis
    assert "Rs100.00" in thesis


def test_none_strategy_tag_falls_back_to_the_default():
    thesis = main._build_trade_thesis(None, 100.0, 90.0, None, tracked=False)
    assert "could not be identified" in thesis


def test_every_currently_live_strategy_tag_has_its_own_specific_thesis_text():
    # No silent fallback-to-default for any tag this app can actually open
    # a real position under today.
    for tag in ("orb-universal-score", "orb-range-short", "orb-trend-short",
                "gap_and_go", "minervini_vcp_livermore", "minervini_vcp", "power_play"):
        assert tag in main._TRADE_THESIS_COMPONENTS, f"{tag} has no dedicated thesis text"


def test_minervini_plain_variant_discloses_it_is_below_the_real_money_floor():
    thesis = main._build_trade_thesis("minervini_vcp", 100.0, 90.0, None, tracked=False)
    assert "0.908" in thesis
    assert "real-money floor" in thesis


def test_power_play_discloses_its_own_thin_sample_caveat():
    thesis = main._build_trade_thesis("power_play", 100.0, 90.0, None, tracked=True)
    assert "RAREST" in thesis
    assert "109" in thesis


# ---- get_real_open_positions: every row carries entry_thesis ---------------

def test_bot_tracked_long_position_carries_an_entry_thesis():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, sl_trigger_price, target_price, strategy) VALUES "
            "('RELIANCE.NS', 'RELIANCE-EQ', 5, 100.0, 'E1', ?, ?, 95.0, 115.0, 'orb-universal-score')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = result["open_real_positions"][0]
    assert "entry_thesis" in pos
    assert "Rs100.00" in pos["entry_thesis"]
    assert "actively tracking" in pos["entry_thesis"]


def test_bot_tracked_short_position_carries_a_short_specific_entry_thesis():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, sl_trigger_price, strategy) VALUES "
            "('TCS.NS', 'TCS-EQ', 1, 2100.0, 'E1', ?, ?, 2110.0, 'orb-range-short')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = next(p for p in result["open_real_positions"] if p["symbol"] == "TCS.NS")
    assert "SHORT" in pos["entry_thesis"]
    assert "VWAP mean-reversion" in pos["entry_thesis"]


def test_swing_position_carries_an_entry_thesis():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, stop_loss, sl_trigger_price, strategy) VALUES "
            "('GOODSTOCK.NS', 'GOODSTOCK-EQ', 2, 500.0, 'E1', ?, ?, 480.0, 480.0, 'power_play')",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.commit()
    with patch("main.fetch_ohlc", side_effect=Exception("no network in test")):
        result = main.get_real_open_positions()
    pos = next(p for p in result["open_real_positions"] if p["symbol"] == "GOODSTOCK.NS")
    assert "Power Play" in pos["entry_thesis"]
    assert "actively tracking" in pos["entry_thesis"]
