"""Tests for the 2026-10-01 fix closing a real-money gap found during a
routine backlog review: the PFnet real-money viability gate
(_is_strategy_viable_for_real_money, tests/test_pfnet_real_money_gate.py)
was ONLY ever wired into the three equity/swing real entry functions,
despite CLAUDE.md's own 2026-09-30 standing rule claiming it applies
"across every category (buy, short_sell, swing, futures, options)".
_maybe_place_real_fo_call_entry (single-leg call mirror of a paper
index/MCX long) and _straddle_signal_core's own real straddle entry had
NO such check - confirmed live-exploitable, since REAL_FO_TRADING_ENABLED
was confirmed ON in production at the time this was found. Both now call
the gate the same way every other real entry does."""
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
    "kotak_trading_symbol": "NIFTY17OCT26C25000CE", "instrument_token": "999",
    "exchange_segment": "nse_fo", "expiry": "2026-10-17", "strike": 25000.0,
    "dte": 30, "iv": 0.2, "atm_iv": 0.2, "delta": 0.5,
    "lot_size": 25, "premium": 100.0,
}


# ---- single-leg call mirror -------------------------------------------------

def test_call_entry_blocked_when_underlying_strategy_is_not_viable():
    # universal_score (PFnet 0.05) is the real, current strategy tag every
    # WATCHLIST index/MCX symbol uses - this is the exact live gap: before
    # this fix, a real options call could open off this exact signal even
    # though the equivalent equity position is already correctly blocked.
    _fresh_db()
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("nse_fo_chain.select_nse_option_contract", return_value=(_CONTRACT, None)):
        with closing(main.get_db()) as conn:
            main._maybe_place_real_fo_call_entry(conn, "^NSEI", spot=25000.0, strategy_tag="orb-universal-score")
            row = conn.execute("SELECT status FROM real_fo_trades WHERE leg_key = 'NIFTY:CALL'").fetchone()
    assert row is not None
    assert row["status"] == "skipped_strategy_not_viable"


def test_call_entry_blocked_when_strategy_tag_is_missing():
    _fresh_db()
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("nse_fo_chain.select_nse_option_contract", return_value=(_CONTRACT, None)):
        with closing(main.get_db()) as conn:
            main._maybe_place_real_fo_call_entry(conn, "^NSEI", spot=25000.0, strategy_tag=None)
            row = conn.execute("SELECT status FROM real_fo_trades WHERE leg_key = 'NIFTY:CALL'").fetchone()
    assert row is not None
    assert row["status"] == "skipped_strategy_not_viable"


def test_call_entry_proceeds_past_the_gate_when_strategy_is_viable():
    # Confirms the gate is a real pass-through, not an accidental
    # always-block - a viable tag clears it and reaches the NEXT gate
    # (daily cap), a clean, distinct outcome that isolates this check.
    _fresh_db()
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("main._is_strategy_viable_for_real_money", return_value=True), \
         patch("main._day_open_capital_inr", return_value=1.0), \
         patch("nse_fo_chain.select_nse_option_contract", return_value=(_CONTRACT, None)):
        with closing(main.get_db()) as conn:
            main._maybe_place_real_fo_call_entry(conn, "^NSEI", spot=25000.0, strategy_tag="gap_and_go")
            row = conn.execute("SELECT status FROM real_fo_trades WHERE leg_key = 'NIFTY:CALL'").fetchone()
    assert row is not None
    assert row["status"] != "skipped_strategy_not_viable"


# ---- long straddle -----------------------------------------------------

def test_long_straddle_has_no_registry_entry_and_is_permanently_blocked():
    # "long_straddle" is explicitly documented as NOT YET BACKTESTED - it
    # has no strategy_registry.py entry at all, so the gate must fail
    # closed on it exactly like any other unrecognized tag.
    assert main._is_strategy_viable_for_real_money("long_straddle") is False


def test_straddle_real_entry_blocked_even_with_switches_on(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "is_real_fo_trading_enabled", lambda: True)
    contract_call = {**_CONTRACT, "kotak_trading_symbol": "NIFTY17OCT26C25000CE"}
    contract_put = {**_CONTRACT, "kotak_trading_symbol": "NIFTY17OCT26P25000PE", "strike": 25000.0}
    monkeypatch.setattr(
        main.nse_fo_chain if hasattr(main, "nse_fo_chain") else __import__("nse_fo_chain"),
        "select_nse_option_contract",
        lambda underlying, spot, right: (contract_call if right == "call" else contract_put, None),
    )
    with closing(main.get_db()) as conn:
        conn.execute(
            "INSERT INTO runtime_settings (key, value) VALUES ('real_straddle_enabled', 1.0) "
            "ON CONFLICT(key) DO UPDATE SET value = 1.0"
        )
        conn.commit()
        main._straddle_signal_core(conn, "NIFTY", vol_signal=True, halted=False,
                                    is_squareoff_time=False, spot=25000.0)
        rows = conn.execute(
            "SELECT status FROM real_fo_trades WHERE leg_key LIKE 'NIFTY:STRADDLE-%'"
        ).fetchall()
    assert len(rows) == 2
    assert all(r["status"] == "skipped_strategy_not_viable" for r in rows)
