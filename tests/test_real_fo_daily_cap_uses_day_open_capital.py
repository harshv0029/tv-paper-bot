"""Tests for the F&O daily spend cap (2026-09-17, explicit user
instruction: "Daily F&O cap = Kotak available capital. Not a fix
number"). _maybe_place_real_fo_call_entry now checks the day's remaining
F&O spend budget against _day_open_capital_inr(conn) (the account's own
real capital as of today's open, same basis the joint real-loss-cap
already uses) instead of a fixed real_fo_daily_cap_inr runtime setting -
that setting has been removed entirely."""
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


_CONTRACT = {
    "kotak_trading_symbol": "GOLDM17OCT26C1500CE", "instrument_token": "999",
    "exchange_segment": "mcx_fo", "expiry": "2026-10-17", "strike": 1500.0,
    "dte": 30, "iv": 0.2, "atm_iv": 0.2, "delta": 0.5,
    "lot_size": 10, "premium": 500.0,
}


def test_removed_setting_no_longer_exists():
    assert "real_fo_daily_cap_inr" not in main.RUNTIME_SETTINGS_META


def test_over_day_open_capital_is_skipped_not_a_fixed_threshold():
    _fresh_db()
    # notional = lot_size(10) * premium(500) = 5000; day-open capital of
    # just 1000 must reject it, even though the old fixed default
    # (Rs 2000) would also have rejected it - the point is this now
    # tracks a LIVE capital figure, not a configured constant.
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("main._day_open_capital_inr", return_value=1000.0), \
         patch("nse_fo_chain.select_nse_option_contract", return_value=(_CONTRACT, None)):
        with closing(main.get_db()) as conn:
            main._maybe_place_real_fo_call_entry(conn, "^NSEI", spot=25000.0)
            row = conn.execute(
                "SELECT status, detail FROM real_fo_trades WHERE leg_key = 'NIFTY:CALL'"
            ).fetchone()
    assert row["status"] == "skipped_over_daily_cap"
    assert "1000.00" in row["detail"]


def test_higher_day_open_capital_clears_the_cap_gate():
    _fresh_db()
    # Same 5000 notional, but day-open capital of 100000 (well above the
    # old fixed Rs 2000 default) now clears the cap check - proving the
    # gate scales with real capital instead of being stuck at a constant.
    # Stopped at the NEXT gate (real loss budget) via a clean, distinct
    # outcome so this test isolates the cap check specifically.
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("main._day_open_capital_inr", return_value=100000.0), \
         patch("nse_fo_chain.select_nse_option_contract", return_value=(_CONTRACT, None)), \
         patch("main._real_loss_budget", return_value={
             "real_pnl_today": -50.0, "ok": False, "detail": "loss cap hit", "cap_inr": 10.0,
             "day_open_capital_inr": 100000.0,
         }):
        with closing(main.get_db()) as conn:
            main._maybe_place_real_fo_call_entry(conn, "^NSEI", spot=25000.0)
            row = conn.execute(
                "SELECT status FROM real_fo_trades WHERE leg_key = 'NIFTY:CALL'"
            ).fetchone()
    assert row["status"] == "skipped_real_daily_loss_cap_hit"
