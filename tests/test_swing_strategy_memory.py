"""Swing strategy memory (2026-10-06): signal_state_swing Upstash mirror +
daily per-strategy resting-SL ratchet. No real Upstash/Kotak involved.

Run: pytest tests/test_swing_strategy_memory.py -v
"""
import json
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock, patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _state(conn, symbol="NYKAA.NS", strategy="minervini_vcp", initial=100.0, atr=5.0, peak=130.0):
    conn.execute(
        "INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
        "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (symbol, strategy, "2026-10-01", 110.0, initial, None, 3, 1.0, 1.0, atr, peak))


def _real(conn, symbol="NYKAA.NS", sl=100.0, order="OLD1", strategy="minervini_vcp"):
    conn.execute(
        "INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
        "opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (symbol, symbol.replace(".NS", "-EQ"), 3, 110.0, "E1", 1.0, "2026-10-01", 100.0, order, sl, strategy))


def test_stop_level_chandelier_per_strategy():
    f = main._swing_strategy_stop_level
    assert f("minervini_vcp", 100, 5, 130) == 130 - main.MINERVINI_ATR_STOP_MULT * 5
    assert f("power_play", 100, 5, 130) == 130 - main.POWER_PLAY_ATR_STOP_MULT * 5
    assert f("order_block_delta", 100, 5, 130) == 130 - main.ORDER_BLOCK_ATR_TRAIL_MULT * 5
    assert f("volume_profile_poc", 100, 5, 130) == 130 - main.VP_ATR_TRAIL_MULT * 5
    assert f("minervini_vcp", 120, 5, 130) == 120  # never below initial stop


def test_stop_level_gap_and_go_and_unknown_frozen():
    f = main._swing_strategy_stop_level
    assert f("gap_and_go", 100, None, None) == 100
    assert f("some_new_tag", 100, 5, 130) == 100  # never guesses a multiplier


def test_ratchet_scans_book_then_replaces_via_ensure_resting_sl():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _state(conn); _real(conn)
        conn.commit()
        with patch("kotak_real_orders.ensure_resting_sl",
                   return_value={"ok": True, "order_id": "NEW1", "trigger_price": 120.0, "action": "replaced"}) as place, \
             patch("kotak_real_orders.cancel_real_order") as cancel:
            acts = main._sync_swing_resting_sl_to_strategy(conn)
        place.assert_called_once()
        assert place.call_args[0][2] == 130 - main.MINERVINI_ATR_STOP_MULT * 5
        cancel.assert_not_called()  # ensure_resting_sl cancels the old stop itself, after scanning the book
        row = conn.execute("SELECT * FROM real_positions_swing").fetchone()
        assert row["sl_order_id"] == "NEW1"
        assert acts[0]["ok"] is True


def test_ratchet_never_lowers_and_failure_keeps_old():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _state(conn, peak=105.0); _real(conn, sl=100.0)  # target 95 -> floor 100 == current: no-op
        conn.commit()
        with patch("kotak_real_orders.ensure_resting_sl") as place:
            assert main._sync_swing_resting_sl_to_strategy(conn) == []
            place.assert_not_called()
        conn.execute("UPDATE signal_state_swing SET running_max_close = 140")
        conn.commit()
        with patch("kotak_real_orders.ensure_resting_sl", return_value={"ok": False, "detail": "rej", "action": "replace_failed"}), \
             patch("kotak_real_orders.cancel_real_order") as cancel:
            acts = main._sync_swing_resting_sl_to_strategy(conn)
        cancel.assert_not_called()
        assert acts[0]["ok"] is False
        assert conn.execute("SELECT sl_order_id FROM real_positions_swing").fetchone()[0] == "OLD1"


def test_mirror_roundtrip_restores_exit_state_and_paper_position():
    _fresh_db()
    store = {}
    def fake_post(url, headers=None, data=None, timeout=None):
        store["v"] = data.decode()
        return MagicMock()
    def fake_get(url, headers=None, timeout=None):
        m = MagicMock(); m.json.return_value = {"result": store.get("v")}; return m
    with patch.object(main, "UPSTASH_REDIS_REST_URL", "http://x"), patch.object(main, "UPSTASH_REDIS_REST_TOKEN", "t"), \
         patch.object(main.requests, "post", fake_post), patch.object(main.requests, "get", fake_get):
        with closing(main.get_db()) as conn:
            _state(conn, strategy="power_play", atr=4.0, peak=150.0); conn.commit()
            main._sync_signal_state_swing_external(conn)
        _fresh_db()  # simulated restart wipe
        assert main.hydrate_signal_state_swing_from_external() is True
        with closing(main.get_db()) as conn:
            r = conn.execute("SELECT * FROM signal_state_swing").fetchone()
            assert (r["strategy"], r["atr_at_entry"], r["running_max_close"]) == ("power_play", 4.0, 150.0)
            assert conn.execute("SELECT qty FROM positions WHERE symbol='NYKAA.NS'").fetchone()[0] == 3


def test_hydrate_noop_without_upstash():
    with patch.object(main, "UPSTASH_REDIS_REST_URL", ""), patch.object(main, "UPSTASH_REDIS_REST_TOKEN", ""):
        assert main.hydrate_signal_state_swing_from_external() is False
