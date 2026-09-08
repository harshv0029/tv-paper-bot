"""Regression test for the AGL.NS/BHANDARI.NS ghost-resurrection bug found
live 2026-09-08 (explicit user finding, /live dashboard screenshot): a
position already closed (eod_squareoff/stale_timeout) and already durably
logged to docs/trade_outcomes_log.json kept reappearing as LIVE/open after
every restart, because reconcile_open_positions_from_journal() restored
blindly from the (up to ~15-min-stale) state/open_positions.json journal
with no check against what had already, durably, closed. See main.py's
_closed_in_durable_log docstring for the full root cause."""
import json
import os
import tempfile
from contextlib import closing

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_closed_in_durable_log_matches_symbol_and_entry_price():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump([
            {"symbol": "AGL.NS", "entry_price_native": 15.82, "exit_time_utc": 1788861395.6,
             "exit_reason": "eod_squareoff"},
        ], f)
    main.DOCS_TRADE_OUTCOMES_PATH = path
    try:
        assert main._closed_in_durable_log("AGL.NS", 15.82, 1788850407.3) is True
        # different symbol -> no match
        assert main._closed_in_durable_log("BHANDARI.NS", 15.82, 1788850407.3) is False
        # different entry price (a genuinely different, later trade on the
        # same symbol) -> must not match
        assert main._closed_in_durable_log("AGL.NS", 16.50, 1788850407.3) is False
        # exit before this trade's own entry -> a different, earlier trade,
        # must not match
        assert main._closed_in_durable_log("AGL.NS", 15.82, 1788870000.0) is False
    finally:
        os.remove(path)


def test_reconcile_skips_resurrecting_an_already_closed_position():
    _fresh_db()
    journal_fd, journal_path = tempfile.mkstemp(suffix=".json")
    os.close(journal_fd)
    outcomes_fd, outcomes_path = tempfile.mkstemp(suffix=".json")
    os.close(outcomes_fd)

    with open(journal_path, "w") as f:
        json.dump({"open_positions": [{
            "symbol": "AGL.NS", "qty": 7.0, "entry_price_native": 15.82,
            "stop_loss_native": 15.66, "initial_stop_loss_native": 15.66,
            "target_native": 16.29, "fx_to_inr": 1.0, "orb_high_native": 14.15,
            "orb_low_native": 13.55, "entry_ts": 1788850407.3, "interval": "5m",
            "strategy": "orb-15m-sma9-21", "sma_fast": 9, "sma_slow": 21,
        }]}, f)
    with open(outcomes_path, "w") as f:
        json.dump([{
            "symbol": "AGL.NS", "exit_time_utc": 1788861395.6, "entry_price_native": 15.82,
            "exit_price_native": 16.08, "currency": "INR", "qty": 7.0, "pnl_inr": 1.82,
            "exit_reason": "eod_squareoff", "strategy": "orb-15m-sma9-21",
        }], f)

    main.STATE_JOURNAL_PATH = journal_path
    main.DOCS_TRADE_OUTCOMES_PATH = outcomes_path
    try:
        main.reconcile_open_positions_from_journal()
        with closing(main.get_db()) as conn:
            row = conn.execute(
                "SELECT 1 FROM signal_state WHERE symbol = ? AND status = 'long'", ("AGL.NS",)
            ).fetchone()
            assert row is None, "already-closed position must NOT be resurrected as open"
    finally:
        os.remove(journal_path)
        os.remove(outcomes_path)


def test_reconcile_still_restores_a_genuinely_open_position():
    """Sanity check the fix doesn't break the original recovery behavior -
    a position with NO matching durable close must still be restored."""
    _fresh_db()
    journal_fd, journal_path = tempfile.mkstemp(suffix=".json")
    os.close(journal_fd)
    outcomes_fd, outcomes_path = tempfile.mkstemp(suffix=".json")
    os.close(outcomes_fd)

    with open(journal_path, "w") as f:
        json.dump({"open_positions": [{
            "symbol": "AARTIIND.NS", "qty": 1.0, "entry_price_native": 502.3,
            "stop_loss_native": 497.28, "initial_stop_loss_native": 497.28,
            "target_native": 517.36, "fx_to_inr": 1.0, "orb_high_native": 500.0,
            "orb_low_native": 495.0, "entry_ts": 1788870000.0, "interval": "5m",
            "strategy": "orb-15m-sma9-21", "sma_fast": 9, "sma_slow": 21,
        }]}, f)
    with open(outcomes_path, "w") as f:
        json.dump([], f)  # nothing closed yet - genuinely still open

    main.STATE_JOURNAL_PATH = journal_path
    main.DOCS_TRADE_OUTCOMES_PATH = outcomes_path
    try:
        main.reconcile_open_positions_from_journal()
        with closing(main.get_db()) as conn:
            row = conn.execute(
                "SELECT 1 FROM signal_state WHERE symbol = ? AND status = 'long'", ("AARTIIND.NS",)
            ).fetchone()
            assert row is not None, "a genuinely still-open position must still be restored"
    finally:
        os.remove(journal_path)
        os.remove(outcomes_path)
