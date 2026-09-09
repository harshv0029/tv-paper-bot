"""Regression tests for the 2026-09-10 review-found fixes to the
universal-score architecture (see docs/TRADING_CONSTRAINTS.md and the
review discussion in-session): the target_hit/staged-ladder exit-state
ambiguity, the real partial-exit double-sell gap, the volume double-
counting in the entry score, real-fill-price vs paper-R slippage, the
aggregate open-risk gate, fail-closed protective-order handling, and an
unrelated bug found while auditing all of the above - _execute_partial_exit
silently losing its own conn.commit()/return during an earlier edit."""
import json
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


# ---- _execute_partial_exit's restored commit/return -------------------------

def test_execute_partial_exit_commits_its_own_write():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
            "VALUES ('RELIANCE.NS', ?, 'long', 100.0, 98.0, 98.0, 106.0, 10, ?, 1.0, '5m')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, 'RELIANCE.NS', 'buy', 10, 100.0, 1.0, 'orb-test', '{}')",
            (main.time.time(),),
        )
        conn.commit()
        pnl = main._execute_partial_exit(conn, "RELIANCE.NS", 4, 102.0, "TCS.NS", 0.9)
        assert pnl == (102.0 - 100.0) * 4
        # The whole point of the fix: no pending, uncommitted write left
        # on this connection after the function returns.
        assert conn.in_transaction is False
        row = conn.execute("SELECT qty FROM signal_state WHERE symbol='RELIANCE.NS'").fetchone()
        assert row["qty"] == 6


# ---- #6 fix: target_hit gated on no unfilled fixed leg ----------------------

def test_next_unfilled_leg_blocks_full_exit_semantics_while_legs_remain():
    # Direct proof of the exact condition _auto_signal_core's exit chain
    # now uses: `last_close >= current_target and next_leg is None`.
    legs = main._split_exit_legs(8, {"1.0R": 102.0, "1.5R": 103.0, "2.0R": 104.0})
    legs_json = json.dumps(legs)
    # primary_target sitting BELOW T1's own price (the sharper example
    # from review: structure/ATR project a tighter move than 2R) - price
    # at 101 has already cleared a primary_target of 100.5 but has NOT
    # reached T1 (102) yet.
    current_target = 100.5
    last_close = 101.0
    next_leg = main._next_unfilled_leg(legs_json)
    assert next_leg is not None and next_leg["leg"] == "T1"
    would_fire_target_hit = last_close >= current_target and next_leg is None
    assert would_fire_target_hit is False, "target_hit must not fire while T1/T2/T3 are still unfilled"


def test_next_unfilled_leg_allows_full_exit_once_every_leg_filled():
    legs = main._split_exit_legs(8, {"1.0R": 102.0, "1.5R": 103.0, "2.0R": 104.0})
    for leg in legs:
        if leg["leg"] != "trail":
            leg["status"] = "filled"
    legs_json = json.dumps(legs)
    next_leg = main._next_unfilled_leg(legs_json)
    assert next_leg is None
    would_fire_target_hit = 105.0 >= 104.5 and next_leg is None
    assert would_fire_target_hit is True


# ---- #2 fix: volume score is a graded RVOL read, not the same gate twice ----

def test_volume_breakout_score_graded_by_rvol_not_the_gate_boolean():
    df, today_df, sma_f, sma_s = _bullish_fixture()
    full = main._compute_universal_entry_score(df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=2.0)
    partial = main._compute_universal_entry_score(df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=1.2)
    none_ratio = main._compute_universal_entry_score(df, today_df, True, sma_f, sma_s, None, 9, 21, "ema", vol_ratio=None)
    assert full["breakdown"]["volume_breakout"] == main.UNIVERSAL_SCORE_WEIGHTS["volume_breakout"]
    assert partial["breakdown"]["volume_breakout"] == main.UNIVERSAL_SCORE_WEIGHTS["volume_breakout"] * 0.5
    assert none_ratio["breakdown"]["volume_breakout"] is None
    assert none_ratio["max_score"] < full["max_score"], "volume_breakout must drop out of max_score, not score 0"


def _bullish_fixture(n=60):
    import numpy as np
    import pandas as pd
    df = pd.DataFrame({
        "High": np.linspace(100, 130, n) + 0.5,
        "Low": np.linspace(100, 130, n) - 0.5,
        "Close": np.linspace(100, 130, n),
        "Volume": np.concatenate([np.full(n - 1, 1000.0), [3000.0]]),
    })
    today_df = df.iloc[-5:].copy()
    closes = df["Close"].to_numpy()
    sma_f = main._moving_average(closes, 9, "ema")
    sma_s = main._moving_average(closes, 21, "ema")
    return df, today_df, sma_f, sma_s


# ---- #11: aggregate open-risk gate ------------------------------------------

def test_open_positions_reserved_risk_sums_across_open_positions():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
            "('A.NS', ?, 'long', 100.0, 98.0, 98.0, 106.0, 10, ?, 1.0, '5m')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
            "('B.NS', ?, 'long', 200.0, 196.0, 196.0, 212.0, 5, ?, 1.0, '5m')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.commit()
        total = main._open_positions_reserved_risk_inr(conn)
        # A.NS: (100-98)*10=20, B.NS: (200-196)*5=20 -> 40 total
        assert total == 40.0
        excluded = main._open_positions_reserved_risk_inr(conn, exclude_symbol="A.NS")
        assert excluded == 20.0


# ---- #13: fail-closed retry + escalation ------------------------------------

def test_place_real_stop_loss_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def fake_place(sym, qty, price):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"ok": False, "detail": "transient"}
        return {"ok": True, "order_id": "SL-1", "trigger_price": price}

    with patch("kotak_real_orders.place_real_stop_loss", side_effect=fake_place), \
         patch.object(main.time, "sleep", return_value=None):
        result = main._place_real_stop_loss_with_retry("RELIANCE-EQ", 10, 98.0)
    assert result["ok"] is True
    assert calls["n"] == 3


def test_place_real_stop_loss_with_retry_reports_failure_after_exhausting_attempts():
    with patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": False, "detail": "rejected"}), \
         patch.object(main.time, "sleep", return_value=None):
        result = main._place_real_stop_loss_with_retry("RELIANCE-EQ", 10, 98.0)
    assert result["ok"] is False


def test_maybe_sync_real_stop_loss_never_force_closes_on_a_replacement_failure():
    # 2026-09-10, explicit user instruction after review: a force-close
    # escalation here was built, then explicitly reverted - the resting
    # broker order was never the ONLY protection; _auto_signal_core's own
    # tick-based stop_hit check needs no resting order to work, so
    # escalating on a mere placement failure would sell on an API hiccup
    # rather than an actual price event. Retries still happen (cheap),
    # but exhausting them must never trigger a full exit on its own.
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price) VALUES "
            "('RELIANCE.NS', 'RELIANCE-EQ', 10, 100.0, 'E1', ?, ?, 'SL-OLD', 97.0)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
            "('RELIANCE.NS', ?, 'long', 100.0, 98.0, 97.0, 106.0, 10, ?, 1.0, '5m')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.commit()

        with patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
             patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": False, "detail": "rejected"}), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "RELIANCE.NS")
            mock_force_exit.assert_not_called()
        row = conn.execute("SELECT sl_order_id FROM real_positions WHERE symbol='RELIANCE.NS'").fetchone()
        assert row["sl_order_id"] is None  # cleared so the next tick retries placing a fresh one


def test_maybe_sync_real_stop_loss_does_not_force_close_a_position_with_no_prior_sl():
    # Same non-escalation guarantee for a fresh/adopted position that
    # never had a tracked SL yet.
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES "
            "('RELIANCE.NS', 'RELIANCE-EQ', 10, 100.0, 'E1', ?, ?)",
            (main.time.time(), main.ist_now().strftime("%Y-%m-%d")),
        )
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
            "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) VALUES "
            "('RELIANCE.NS', ?, 'long', 100.0, 98.0, 97.0, 106.0, 10, ?, 1.0, '5m')",
            (main.ist_now().strftime("%Y-%m-%d"), main.time.time()),
        )
        conn.commit()

        with patch("kotak_real_orders.cancel_existing_resting_sl", return_value={"ok": True}), \
             patch("kotak_real_orders.place_real_stop_loss", return_value={"ok": False, "detail": "rejected"}), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main, "_maybe_place_real_exit") as mock_force_exit:
            main._maybe_sync_real_stop_loss(conn, "RELIANCE.NS")
            mock_force_exit.assert_not_called()


# ---- double-sell fix: _maybe_place_real_partial_exit ------------------------

def _insert_real_position_with_legs(conn, qty=8, legs=None):
    legs = legs if legs is not None else main._split_exit_legs(qty, {"1.0R": 102.0, "1.5R": 103.0, "2.0R": 104.0})
    conn.execute(
        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, target_order_id, "
        "target_price, exit_legs_json) VALUES "
        "('RELIANCE.NS', 'RELIANCE-EQ', ?, 100.0, 'E1', ?, ?, 'SL-1', 98.0, 'T1-ORD', 102.0, ?)",
        (qty, main.time.time(), main.ist_now().strftime("%Y-%m-%d"), json.dumps(legs)),
    )
    conn.commit()


def test_partial_exit_places_a_real_sell_when_the_resting_order_was_still_live():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_with_legs(conn)
        with patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}) as mock_cancel, \
             patch("kotak_real_orders.place_real_exit",
                   return_value={"ok": True, "qty": 2, "fill_price": 102.1, "order_id": "S1",
                                 "fill_price_confirmed": True}) as mock_sell, \
             patch("kotak_real_orders.place_real_target",
                   return_value={"ok": True, "order_id": "T2-ORD", "target_price": 103.0}), \
             patch("kotak_real_orders.place_real_stop_loss",
                   return_value={"ok": True, "order_id": "SL-2", "trigger_price": 98.0}):
            main._maybe_place_real_partial_exit(conn, "RELIANCE.NS", {"leg": "T1", "qty": 2})
        # cancel_real_order is also legitimately called again later (once
        # more for "T1-ORD" advancing to the next leg, and once for the
        # SL resize's own old order) - the point of this test is only that
        # the LEG's own order was checked before selling.
        mock_cancel.assert_any_call("T1-ORD")
        mock_sell.assert_called_once()  # the resting order was cancellable -> genuinely safe to sell
        row = conn.execute("SELECT qty FROM real_positions WHERE symbol='RELIANCE.NS'").fetchone()
        assert row["qty"] == 6


def test_partial_exit_reconciles_instead_of_double_selling_when_leg_already_filled_at_kotak():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _insert_real_position_with_legs(conn)
        with patch("kotak_real_orders.cancel_real_order", return_value={"ok": False, "detail": "order already complete"}) as mock_cancel, \
             patch("kotak_real_orders.place_real_exit") as mock_sell, \
             patch("kotak_real_orders.place_real_target",
                   return_value={"ok": True, "order_id": "T2-ORD", "target_price": 103.0}), \
             patch("kotak_real_orders.place_real_stop_loss",
                   return_value={"ok": True, "order_id": "SL-2", "trigger_price": 98.0}):
            main._maybe_place_real_partial_exit(conn, "RELIANCE.NS", {"leg": "T1", "qty": 2})
        mock_cancel.assert_any_call("T1-ORD")
        mock_sell.assert_not_called(), "must never place a second sell once the resting order can't be cancelled"
        row = conn.execute("SELECT qty, exit_legs_json FROM real_positions WHERE symbol='RELIANCE.NS'").fetchone()
        assert row["qty"] == 6  # qty still reconciled down, just without a redundant order
        legs = json.loads(row["exit_legs_json"])
        t1 = next(l for l in legs if l["leg"] == "T1")
        assert t1["status"] == "filled"
