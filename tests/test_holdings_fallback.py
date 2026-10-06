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


def test_heal_core_places_atr_stop_for_any_holding():
    import numpy as np
    held = {"qty": 10, "avg_price": 100.0, "symbol": "TCS"}
    with patch.object(main, "fetch_ohlc", return_value=object()), \
         patch.object(main, "_swing_atr", return_value=np.array([4.0])), \
         patch.object(main, "_sync_real_positions_swing_external"), \
         patch("kotak_real_orders.place_real_stop_loss",
               return_value={"ok": True, "order_id": "X1", "trigger_price": 90.0}) as place:
        res = main._heal_swing_holding_core("TCS-EQ", held, [])
    assert res["sl_ok"] and res["stop"] == 90.0 and place.call_count == 1
    assert place.call_args[0][:3] == ("TCS-EQ", 10, 90.0)


def test_heal_core_noop_when_sl_resting():
    sl = {"trdSym": "TCS-EQ", "trnsTp": "S", "prcTp": "SL-M", "ordSt": "open"}
    with patch("kotak_real_orders.place_real_stop_loss") as place:
        res = main._heal_swing_holding_core("TCS-EQ", {"qty": 1, "avg_price": 50.0, "symbol": "TCS"}, [sl])
    assert res["status"].startswith("already_protected") and not place.called


def test_heal_places_nothing_when_already_protected():
    from fastapi.testclient import TestClient
    sl = {"trdSym": "NYKAA-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "open"}
    with patch.object(main, "_require_kotak_token", return_value=None), \
         patch.object(main, "_kotak_holdings_open_by_trdsym",
                      return_value={"NYKAA-EQ": {"qty": 1, "avg_price": 340.11, "symbol": "NYKAA"}}), \
         patch("kotak_neo.order_report", return_value={"data": [sl]}), \
         patch("kotak_real_orders.place_real_stop_loss") as place:
        r = TestClient(main.app).post("/kotak-neo/heal-swing-holding-sl?kotak_trading_symbol=NYKAA-EQ")
    assert r.json()["status"].startswith("already_protected") and not place.called
