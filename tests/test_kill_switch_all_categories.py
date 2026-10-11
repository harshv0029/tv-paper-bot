"""2026-10-11 user: the ALL TRADING toggle OFF must stop new trades immediately in EVERY category and close live positions
in EVERY category (short, swing/holdings, options/MCX), not only the intraday long table.
Run: pytest tests/test_kill_switch_all_categories.py -v"""
import os
import tempfile
import time
from contextlib import closing
from unittest.mock import patch

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def test_new_real_entries_blocked_when_switch_off():
    _fresh_db()
    tag = next(t for t in main._STRATEGY_TAG_TO_REGISTRY_NAME if main._is_strategy_viable_for_real_money(t))
    main.set_trading_control(action="pause")
    assert main._is_strategy_viable_for_real_money(tag) is False
    with patch.object(main, "_reconcile_real_positions_core", return_value={}):
        main.set_trading_control(action="resume")
    assert main._is_strategy_viable_for_real_money(tag) is True


def test_kill_closes_short_swing_and_fo_real_positions():
    _fresh_db()
    calls = []
    def fake_short(conn, symbol, reason=None):
        calls.append(("short", symbol, reason))
    def fake_swing(conn, symbol, reason=None):
        calls.append(("swing", symbol, reason))
    def fake_leg(conn, row, reason):
        calls.append(("fo", row["leg_key"], reason))
    with closing(main.get_db()) as conn:
        cols_short = [r[1] for r in conn.execute("PRAGMA table_info(real_positions_short)").fetchall()]
        cols_swing = [r[1] for r in conn.execute("PRAGMA table_info(real_positions_swing)").fetchall()]
        def ins(tbl, cols, vals):
            data = {c: vals.get(c, 0 if c not in ("symbol", "kotak_trading_symbol") else "X") for c in cols}
            conn.execute(f"INSERT INTO {tbl} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [data[c] for c in cols])
        ins("real_positions_short", cols_short, {"symbol": "SHORT.NS", "kotak_trading_symbol": "SHORT-EQ"})
        ins("real_positions_swing", cols_swing, {"symbol": "SWING.NS", "kotak_trading_symbol": "SWING-EQ"})
        conn.execute("INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, "
                     "exchange_segment, qty, entry_price, opened_at, day) VALUES ('NIFTY:CALL','NIFTY','t','S','1','nse_fo',50,10,?,'d')",
                     (time.time(),))
        conn.commit()
    with patch.object(main, "_maybe_place_real_short_exit", fake_short), \
            patch.object(main, "_maybe_place_real_swing_exit", fake_swing), \
            patch.object(main, "_close_real_fo_option_leg", fake_leg):
        res = main.set_trading_control(action="kill", reason="test")
    kinds = {c[0] for c in calls}
    assert kinds == {"short", "swing", "fo"}
    assert all("kill_switch" in c[2] for c in calls)
    assert res["enabled"] is False
    assert res["real_close_failed_count"] == 3  # mocks leave rows open: they must be reported, not hidden
