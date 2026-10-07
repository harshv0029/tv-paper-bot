"""2026-10-07 (B-294): LTP-peak trail for rerouted orphan swing rows, NYKAA
gap_and_go state restore, swing exit holdings check, closed-market SL gate."""
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import pandas as pd

import main


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _seed(conn, sym="RVNL.NS", trd="RVNL-EQ", strategy=main.ORPHAN_SWING_STRATEGY_TAG, sl=193.25, r=10.0, stop=190.0):
    conn.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                 "stop_loss, strategy, sl_order_id, sl_trigger_price) VALUES (?, ?, 2, 200.0, 1.0, '2026-10-06', ?, ?, 'o1', ?)",
                 (sym, trd, stop, strategy, sl))
    conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, qty, "
                 "entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES (?, ?, '2026-10-06', 200.0, ?, ?, 2, 1.0, 1.0, ?, 200.0)",
                 (sym, strategy, stop, stop, r))
    conn.commit()


def test_ltp_trail_stop_is_peak_minus_1r_and_floored():
    assert main._ltp_trail_stop(230.0, 10.0, 190.0) == 220.0
    assert main._ltp_trail_stop(195.0, 10.0, 190.0) == 190.0  # never below the carried initial stop


def test_trail_raises_stop_off_peak_and_never_lowers():
    _db()
    calls = []
    def fake_ensure(trd, qty, trg):
        calls.append(trg)
        return {"ok": True, "order_id": "o2", "trigger_price": trg, "action": "replaced"}
    with closing(main.get_db()) as conn:
        _seed(conn)
        with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
             patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"RVNL-EQ": {"qty": 2}}), \
             patch.object(main, "_swing_live_ltp_peak", return_value=(228.0, 230.0)), \
             patch("kotak_real_orders.ensure_resting_sl", side_effect=fake_ensure):
            a = main._sync_swing_ltp_trail(conn)
        assert calls == [220.0] and a[0]["ok"]
        assert conn.execute("SELECT sl_trigger_price FROM real_positions_swing").fetchone()[0] == 220.0
        # price falls back: peak is remembered, stop is NOT lowered / no new order
        with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
             patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"RVNL-EQ": {"qty": 2}}), \
             patch.object(main, "_swing_live_ltp_peak", return_value=(215.0, 216.0)), \
             patch("kotak_real_orders.ensure_resting_sl", side_effect=fake_ensure):
            a = main._sync_swing_ltp_trail(conn)
        assert a == [] and calls == [220.0]
        assert conn.execute("SELECT peak_ltp FROM swing_ltp_peak").fetchone()[0] == 230.0


def test_trail_skips_when_market_closed_or_holdings_unknown_or_stop_above_ltp():
    _db()
    with closing(main.get_db()) as conn:
        _seed(conn)
        with patch.object(main, "_nse_equity_market_open_now", return_value=False):
            assert main._sync_swing_ltp_trail(conn) == []
        with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
             patch.object(main, "_kotak_holdings_open_by_trdsym", return_value=None):
            assert main._sync_swing_ltp_trail(conn) == []
        with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
             patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"RVNL-EQ": {"qty": 2}}), \
             patch.object(main, "_swing_live_ltp_peak", return_value=(219.0, 230.0)), \
             patch("kotak_real_orders.ensure_resting_sl") as ens:
            assert main._sync_swing_ltp_trail(conn) == []  # target 220 >= ltp 219
            ens.assert_not_called()


def test_trail_ignores_other_strategies():
    _db()
    with closing(main.get_db()) as conn:
        _seed(conn, sym="NYKAA.NS", trd="NYKAA-EQ", strategy="gap_and_go")
        with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
             patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"NYKAA-EQ": {"qty": 2}}), \
             patch("kotak_real_orders.ensure_resting_sl") as ens:
            assert main._sync_swing_ltp_trail(conn) == []
            ens.assert_not_called()


def test_swing_exit_does_not_clear_row_for_a_delivery_holding():
    with patch.object(main, "_kotak_symbol_still_open", return_value=False), \
         patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"NYKAA-EQ": {"qty": 1}}):
        assert main._kotak_swing_symbol_still_held("NYKAA-EQ") is True
    with patch.object(main, "_kotak_symbol_still_open", return_value=False), \
         patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={}):
        assert main._kotak_swing_symbol_still_held("NYKAA-EQ") is False
    with patch.object(main, "_kotak_symbol_still_open", return_value=False), \
         patch.object(main, "_kotak_holdings_open_by_trdsym", return_value=None):
        assert main._kotak_swing_symbol_still_held("NYKAA-EQ") is None


def test_derive_gap_and_go_state_matches_price_and_is_honest_when_absent():
    df = pd.DataFrame({"Date": [f"2026-09-{i:02d}" for i in range(1, 30)] + ["2026-10-01"] * 30})
    df = pd.DataFrame({"Date": [str(i) for i in range(80)]})
    sig = {"entry_price": 340.0, "stop_loss": 315.0, "gap_low": 331.0}
    def fake(d):
        return sig if len(d) == 70 else None
    with patch.object(main, "gap_and_go_entry_signal", side_effect=fake):
        d = main._derive_gap_and_go_state(df, 340.11)
        assert d["entry_day"] == "69" and d["gap_low"] == 331.0 and d["stop_loss"] == 315.0
        assert main._derive_gap_and_go_state(df, 400.0) is None  # price too far: nothing invented


def test_nykaa_state_restored_once_and_not_when_row_exists():
    _db()
    main._gap_and_go_state_last_day = None
    with closing(main.get_db()) as conn:
        _seed(conn, sym="NYKAA.NS", trd="NYKAA-EQ", strategy="holding_atr_stop")
        conn.execute("DELETE FROM signal_state_swing WHERE symbol='NYKAA.NS'")
        conn.commit()
        d = {"entry_day": "2026-09-25", "entry_price": 340.0, "stop_loss": 315.0, "gap_low": 331.0}
        with patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"NYKAA-EQ": {"qty": 2, "avg_price": 340.11}}), \
             patch.object(main, "fetch_ohlc", return_value=pd.DataFrame({"Date": ["x"]})), \
             patch.object(main, "_derive_gap_and_go_state", return_value=d):
            out = main._ensure_gap_and_go_state_for_held(conn)
        assert out[0]["derived"]
        st = conn.execute("SELECT * FROM signal_state_swing WHERE symbol='NYKAA.NS'").fetchone()
        assert st["strategy"] == "gap_and_go" and st["gap_low"] == 331.0
        assert conn.execute("SELECT strategy FROM real_positions_swing WHERE symbol='NYKAA.NS'").fetchone()[0] == "gap_and_go"


def test_trail_covers_drreddy_even_when_relabelled_volume_profile_poc():
    _db()
    with closing(main.get_db()) as conn:
        _seed(conn, sym="DRREDDY.NS", trd="DRREDDY-EQ", strategy="volume_profile_poc", sl=1172.6, r=40.0, stop=1160.0)
        conn.execute("UPDATE signal_state_swing SET entry_price = 1200.0 WHERE symbol='DRREDDY.NS'")
        conn.commit()
        with patch.object(main, "_nse_equity_market_open_now", return_value=True), \
             patch.object(main, "_kotak_holdings_open_by_trdsym", return_value={"DRREDDY-EQ": {"qty": 2}}), \
             patch.object(main, "_swing_live_ltp_peak", return_value=(1255.0, 1260.0)), \
             patch("kotak_real_orders.ensure_resting_sl", return_value={"ok": True, "order_id": "o9", "trigger_price": 1220.0, "action": "replaced"}) as ens:
            a = main._sync_swing_ltp_trail(conn)
        ens.assert_called_once_with("DRREDDY-EQ", 2, 1220.0)  # peak 1260 - 1R (1200-1160=40)
        assert a[0]["ok"]
