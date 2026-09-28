"""Tests for the ALL-TRADING resume path reconciling against Kotak's own
live account first (2026-09-28, explicit user ask: "when i turn able to
this toggle from OFF... it should fetch live trades in kotak account
first and then based on that it should decide what to do next").

set_trading_control's resume branch calls _reconcile_real_positions_core
(the same logic /kotak-neo/reconcile-real-positions uses, extracted so it
can be called in-process without a token) with adopt="*", best-effort -
a Kotak/network failure must never block resuming PAPER trading.

Run: pytest tests/test_trading_control_resume_reconcile.py -v
"""
import os
import tempfile
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_resume_calls_the_reconcile_core_with_adopt_star():
    _fresh_db()
    fake_result = {
        "reconciled_at_utc": 1.0, "real_balance_inr": 1000.0,
        "qty_corrected_count": 0, "qty_corrected": [],
        "removed_ghost_count": 0, "removed_ghosts": [],
        "untracked_open_positions_count": 0, "untracked_open_positions": [],
        "adopted_count": 0, "adopted": [],
        "governance_backfilled_count": 0, "governance_backfilled": [],
    }
    with patch.object(main, "_reconcile_real_positions_core", return_value=fake_result) as mock_reconcile:
        result = main.set_trading_control(action="resume")
    mock_reconcile.assert_called_once_with(adopt="*")
    assert result["enabled"] is True
    assert result["kotak_reconcile"] == fake_result


def test_pause_never_calls_the_reconcile_core():
    _fresh_db()
    with patch.object(main, "_reconcile_real_positions_core") as mock_reconcile:
        result = main.set_trading_control(action="pause")
    mock_reconcile.assert_not_called()
    assert "kotak_reconcile" not in result


def test_kill_never_calls_the_reconcile_core():
    _fresh_db()
    with patch.object(main, "_reconcile_real_positions_core") as mock_reconcile, \
         patch.object(main, "_force_close_all_positions", return_value={"closed_count": 0, "total_pnl_inr": 0.0}):
        result = main.set_trading_control(action="kill")
    mock_reconcile.assert_not_called()
    assert "kotak_reconcile" not in result


def test_resume_still_succeeds_when_reconcile_raises():
    # Best-effort: a Kotak/network hiccup during reconcile must never
    # block resuming PAPER trading, which doesn't itself depend on Kotak.
    _fresh_db()
    with patch.object(main, "_reconcile_real_positions_core", side_effect=Exception("network hiccup")):
        result = main.set_trading_control(action="resume")
    assert result["enabled"] is True
    assert result["status"] == "resumed"
    assert "network hiccup" in result["kotak_reconcile"]["error"]


def test_resume_actually_flips_the_enabled_flag_in_the_db():
    _fresh_db()
    fake_result = {"qty_corrected_count": 0, "removed_ghost_count": 0,
                    "untracked_open_positions_count": 0, "adopted_count": 0}
    with patch.object(main, "_reconcile_real_positions_core", return_value=fake_result):
        main.set_trading_control(action="pause")
        main.set_trading_control(action="resume")
    assert main.get_trading_control()["enabled"] == 1
