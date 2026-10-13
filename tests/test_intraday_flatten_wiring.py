"""B-914 chan_kalman band short wiring: cutoff, SL unwind, flatten, gate, reason logging.
Run: pytest tests/test_intraday_flatten_wiring.py -v"""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import numpy as np
import pandas as pd

import main

TAG = main.CHAN_SHORT_TAG
SYM = "TESTSTOCK.NS"


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _enable(conn):
    conn.execute("INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
                 "VALUES (1, 1, 0, 't', 't') ON CONFLICT(id) DO UPDATE SET enabled=1")
    conn.commit()


def _paper(conn, stop=110.0):
    conn.execute(
        "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, initial_stop_loss, qty, "
        "entry_ts, fx_to_inr, interval, strategy) VALUES (?, '2026-10-14', 'short', 100.0, ?, ?, 10, ?, 1.0, '5m', ?)",
        (SYM, stop, stop, main.time.time(), TAG))
    conn.commit()


class _Clock:
    def __init__(self, h, m):
        self.hour, self.minute = h, m

    def strftime(self, f):
        return "2026-10-14"


def _entry(conn, clock, sl_ok=True):
    with patch("kotak_live_feed.get_live_ticks", return_value={SYM: {"ltp": 100.0, "trading_symbol": "TEST-EQ"}}), \
         patch("main.ist_now", return_value=clock), \
         patch("main.get_scheduler_capital_inr", return_value=1000000.0), \
         patch("main._real_today_spent_inr", return_value=0.0), \
         patch("main._real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}), \
         patch("main._is_strategy_viable_for_real_money", return_value=True), \
         patch("main._kotak_bought_today", return_value=False), \
         patch("main._kotak_symbol_still_open_short", return_value=True), \
         patch("kotak_real_orders.place_real_short_entry",
               return_value={"ok": True, "qty": 10, "fill_price": 100.0, "order_id": "E1", "fill_price_confirmed": True}) as ent, \
         patch("kotak_real_orders.place_real_short_stop_loss",
               return_value={"ok": sl_ok, "order_id": "SL1", "trigger_price": 110.0, "detail": "rejected"}), \
         patch("kotak_real_orders.place_real_short_cover",
               return_value={"ok": True, "order_id": "C1", "fill_price": 100.0}) as cover:
        main._maybe_place_real_short_entry(conn, SYM)
    return ent, cover


def test_tag_in_registry_map_and_viable():
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[TAG] == TAG
    assert main._is_strategy_viable_for_real_money(TAG)


def test_no_entry_after_cutoff():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable(conn)
            _paper(conn)
            ent, _ = _entry(conn, _Clock(15, 1))
            ent.assert_not_called()
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_entry_unwound_when_sl_fails_with_reason():
    _fresh_db()
    os.environ["REAL_TRADING_ENABLED"] = "YES"
    try:
        with closing(main.get_db()) as conn:
            _enable(conn)
            _paper(conn)
            _, cover = _entry(conn, _Clock(10, 0), sl_ok=False)
            cover.assert_called_once()
            assert conn.execute("SELECT 1 FROM real_positions_short WHERE symbol=?", (SYM,)).fetchone() is None
            det = [r["detail"] or "" for r in conn.execute("SELECT detail FROM real_order_events WHERE symbol=?", (SYM,))]
            assert any("entry_sl_failed_unwind" in d for d in det)
    finally:
        del os.environ["REAL_TRADING_ENABLED"]


def test_manage_flatten_stop_and_hold():
    row = {"stop_loss": 110.0, "entry_price": 100.0, "entry_ts": 0}
    df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]})
    ts = pd.DatetimeIndex(["2026-10-14 05:00"], tz="UTC")
    assert main._chan_short_manage(None, SYM, row, df, ts, "5m", 600, 111.0, False) == "stop_hit"
    assert main._chan_short_manage(None, SYM, row, df, ts, "5m", 600, 99.0, True) == "daily_loss_cap_hit"
    assert main._chan_short_manage(None, SYM, row, df, ts, "5m", 15 * 60 + 10, 99.0, False) == "flatten_1515"


def test_flatten_due_window_and_ownership():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                     "opened_at, day, strategy) VALUES (?, 'T-EQ', 10, 100.0, 'E', 0, '2026-10-14', ?)", (SYM, TAG))
        conn.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                     "opened_at, day, strategy) VALUES ('OTHER.NS', 'O-EQ', 10, 100.0, 'E2', 0, '2026-10-14', 'orb-range-short')")
        conn.commit()
    with patch("main.ist_now", return_value=_Clock(15, 12)):
        assert main._chan_short_flatten_due(SYM)
        assert not main._chan_short_flatten_due("OTHER.NS")
    with patch("main.ist_now", return_value=_Clock(15, 9)):
        assert not main._chan_short_flatten_due(SYM)
    with patch("main.ist_now", return_value=_Clock(15, 15)):
        assert not main._chan_short_flatten_due(SYM)
