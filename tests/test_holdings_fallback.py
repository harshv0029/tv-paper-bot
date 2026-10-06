"""B-46b (2026-10-06): swing shares are Kotak holdings(), absent from
positions() (probe run 37423810072: NYKAA). Covers the holdings helper and
the reconcile ghost guard. Run: pytest tests/test_holdings_fallback.py -v"""
import os
import sys
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

HOLD = {"data": [{"symbol": "NYKAA", "series": "EQ", "exchangeSegment": "nse_cm", "quantity": 1, "averagePrice": 340.11},
                 {"symbol": "ZERO", "series": "EQ", "exchangeSegment": "nse_cm", "quantity": 0, "averagePrice": 1}]}


def test_helper_parses_and_skips_zero_qty():
    with patch("kotak_neo.holdings", return_value=HOLD):
        assert main._kotak_holdings_open_by_trdsym() == {
            "NYKAA-EQ": {"qty": 1, "avg_price": 340.11, "symbol": "NYKAA"}}


def test_helper_none_on_failure_or_bad_shape():
    with patch("kotak_neo.holdings", side_effect=RuntimeError("x")):
        assert main._kotak_holdings_open_by_trdsym() is None
    with patch("kotak_neo.holdings", return_value={"error": "x"}):
        assert main._kotak_holdings_open_by_trdsym() is None


def _swing_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = path; main.init_db()
    with closing(main.get_db()) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(real_positions_swing)")]
        row = {"symbol": "NYKAA.NS", "kotak_trading_symbol": "NYKAA-EQ", "qty": 1, "entry_price": 340.0,
               "stop_loss": 320.0, "sl_order_id": "X1", "opened_at": "t", "day": "2026-10-05"}
        row = {k: v for k, v in row.items() if k in cols}
        conn.execute(f"INSERT INTO real_positions_swing ({','.join(row)}) VALUES ({','.join('?'*len(row))})", tuple(row.values()))
        conn.commit()


def _run(holdings):
    _swing_db()
    with patch("kotak_neo.positions", return_value={"data": []}), patch("kotak_neo.limits", return_value={}), \
         patch("kotak_neo.order_report", return_value={"data": []}), \
         patch.object(main, "_kotak_holdings_open_by_trdsym", return_value=holdings):
        res = main._reconcile_real_positions_core(adopt=None)
    with closing(main.get_db()) as conn:
        n = conn.execute("SELECT COUNT(*) FROM real_positions_swing").fetchone()[0]
    return res, n


def test_held_swing_row_not_ghosted():
    res, n = _run({"NYKAA-EQ": {"qty": 1, "avg_price": 340.0, "symbol": "NYKAA"}})
    assert n == 1 and res["removed_ghost_count"] == 0


def test_unknown_holdings_keeps_row():
    res, n = _run(None)
    assert n == 1 and res["removed_ghost_count"] == 0


def test_not_held_still_ghosted():
    res, n = _run({})
    assert n == 0 and res["removed_ghost_count"] == 1
