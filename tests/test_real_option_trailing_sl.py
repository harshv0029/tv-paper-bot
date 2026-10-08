"""Real single-strike option path (2026-10-08): PUT mirror, trailing SL on the
premium, Kotak-first sync, SL cancelled on exit. Kotak is fully mocked."""
import os
import tempfile
import time
from contextlib import closing
from unittest.mock import patch

import main

CONTRACT = {"kotak_trading_symbol": "NIFTY17OCT26C25000PE", "instrument_token": "999",
            "exchange_segment": "nse_fo", "expiry": "2026-10-17", "strike": 25000.0,
            "dte": 5, "iv": 0.2, "atm_iv": 0.2, "delta": 0.5, "lot_size": 25, "premium": 100.0}


def _db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = path; main.init_db()


def _insert(conn, key="NIFTY:PUT", tag="single_leg_put", opened=None, entry=100.0, trig=None, peak=None):
    conn.execute(
        "INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, "
        "exchange_segment, expiry, strike, lot_size, qty, entry_price, entry_order_id, opened_at, day, "
        "sl_order_id, sl_trigger_price, peak_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key, "NIFTY", tag, CONTRACT["kotak_trading_symbol"], "999", "nse_fo", "2026-10-17", 25000.0, 25, 25, entry,
         "o1", opened or time.time() - 600, "2026-10-08", None, trig, peak or entry))
    conn.commit()


def _state(net=25, sls=()):
    return {"ok": True, "net_qty": net, "live_sls": list(sls)}


def test_put_entry_viable_places_order_and_initial_sl():
    _db()
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("main._is_strategy_viable_for_real_money", return_value=True), \
         patch("main._day_open_capital_inr", return_value=1e6), \
         patch("main._real_loss_budget", return_value={"ok": True, "real_pnl_today": 0, "detail": ""}), \
         patch("nse_fo_chain.select_nse_option_contract", return_value=(CONTRACT, None)) as sel, \
         patch("kotak_real_fo_orders.check_margin_affordable", return_value={"ok": True}), \
         patch("kotak_real_fo_orders.place_real_fo_entry", return_value={"ok": True, "order_id": "E1"}), \
         patch("main._sync_real_fo_option_sl", return_value="placed") as sync, \
         closing(main.get_db()) as conn:
        main._maybe_place_real_fo_put_entry(conn, "^NSEI", 25000.0, "x")
        assert sel.call_args[0][2] == "put"
        row = conn.execute("SELECT * FROM real_fo_positions WHERE leg_key='NIFTY:PUT'").fetchone()
        assert row and row["strategy_tag"] == "single_leg_put" and row["peak_price"] == 100.0
        assert sync.called


def test_put_entry_blocked_when_not_viable():
    _db()
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("main._is_strategy_viable_for_real_money", return_value=False), \
         patch("kotak_real_fo_orders.place_real_fo_entry") as placed, closing(main.get_db()) as conn:
        main._maybe_place_real_fo_put_entry(conn, "^NSEI", 25000.0, "universal_score")
        assert not placed.called


def test_sensex_is_covered():
    assert main._REAL_OPTION_UNDERLYING["^BSESN"] == "SENSEX"


def test_sl_trails_up_with_peak_and_never_down():
    _db()
    with closing(main.get_db()) as conn:
        _insert(conn, trig=70.0, peak=100.0)
        with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value=_state(sls=[{"order_id": "S1", "trigger": 70.0, "qty": 25}])), \
             patch("main._option_ltp", return_value=150.0), \
             patch("main.kotak_real_orders_closing_session", return_value=False), \
             patch("kotak_real_fo_orders.ensure_option_trailing_sl", return_value={"ok": True, "action": "replaced", "order_id": "S2", "trigger_price": 135.0}) as ens:
            assert main._sync_real_fo_option_sl(conn, "NIFTY:PUT") == "replaced"
            assert abs(ens.call_args[0][3] - 135.0) < 1e-6  # 150 * 0.90 fallback trail
        row = conn.execute("SELECT * FROM real_fo_positions").fetchone()
        assert row["peak_price"] == 150.0 and row["sl_trigger_price"] == 135.0
        # premium falls back: peak stays, desired trigger does not drop
        with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value=_state(sls=[{"order_id": "S2", "trigger": 105.0, "qty": 25}])), \
             patch("main._option_ltp", return_value=120.0), \
             patch("main.kotak_real_orders_closing_session", return_value=False), \
             patch("kotak_real_fo_orders.ensure_option_trailing_sl", return_value={"ok": True, "action": "adopted_existing", "order_id": "S2", "trigger_price": 105.0}) as ens:
            main._sync_real_fo_option_sl(conn, "NIFTY:PUT")
            assert ens.call_args[0][3] >= 135.0 - 1e-6


def test_row_closed_when_kotak_shows_flat():
    _db()
    with closing(main.get_db()) as conn:
        _insert(conn)
        with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value=_state(net=0)):
            assert main._sync_real_fo_option_sl(conn, "NIFTY:PUT") == "closed_per_kotak"
        assert conn.execute("SELECT COUNT(*) FROM real_fo_positions").fetchone()[0] == 0
        assert conn.execute("SELECT detail FROM real_fo_trades WHERE status='closed_per_kotak'").fetchone()[0].startswith("reason:")


def test_kotak_unreadable_takes_no_action():
    _db()
    with closing(main.get_db()) as conn:
        _insert(conn)
        with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value={"ok": False, "detail": "x"}):
            assert main._sync_real_fo_option_sl(conn, "NIFTY:PUT").startswith("kotak_unreadable")
        assert conn.execute("SELECT COUNT(*) FROM real_fo_positions").fetchone()[0] == 1


def test_exit_cancels_sl_then_sells_with_reason():
    _db()
    with closing(main.get_db()) as conn:
        _insert(conn)
        with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value=_state(sls=[{"order_id": "S1", "trigger": 70.0, "qty": 25}])), \
             patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}) as canc, \
             patch("kotak_real_fo_orders.place_real_fo_exit", return_value={"ok": True, "order_id": "X1"}):
            assert main._maybe_place_real_fo_put_exit(conn, "^NSEI", reason="paper short exit") is True
            assert canc.called
        assert conn.execute("SELECT COUNT(*) FROM real_fo_positions").fetchone()[0] == 0
        d = conn.execute("SELECT detail FROM real_fo_trades WHERE status='confirmed'").fetchone()[0]
        assert "paper short exit" in d


def test_ensure_adopts_and_ratchets():
    import kotak_real_fo_orders as k
    live = [{"order_id": "S1", "trigger": 105.0, "qty": 25}]
    assert k.ensure_option_trailing_sl("SYM", "nse_fo", 25, 100.0, live)["action"] == "adopted_existing"
    with patch("kotak_real_orders.cancel_real_order", return_value={"ok": True}), \
         patch("kotak_real_fo_orders.place_real_fo_stop_loss", return_value={"ok": True, "order_id": "N", "trigger_price": 120.0}):
        assert k.ensure_option_trailing_sl("SYM", "nse_fo", 25, 120.0, live)["action"] == "replaced"


def _universe(sym="NIFTY17OCT2625000CE"):
    return {("nse_fo", "777"): {"kind": "option", "underlying": "NIFTY", "right": "call", "strike": 25000.0,
                                "expiry": "2026-10-17", "expiry_class": "weekly",
                                "kotak_trading_symbol": sym, "lot_size": 25}}


def _frame(n=40, last_age_s=60):
    import pandas as pd
    now = pd.Timestamp.now(tz="UTC")
    return pd.DataFrame({"Date": [now - pd.Timedelta(seconds=last_age_s + 300 * (n - 1 - i)) for i in range(n)],
                         "Open": [100.0] * n, "High": [102.0] * n, "Low": [98.0] * n, "Close": [100.0] * n,
                         "Volume": [10] * n})


def _scan(conn, universe, df, sig, viable=True):
    from datetime import datetime
    main._fo_strike_scan_last_ts = 0.0
    with patch("main.is_real_fo_trading_enabled", return_value=True), \
         patch("main.ist_now", return_value=datetime(2026, 10, 8, 11, 0)), \
         patch("main._is_strategy_viable_for_real_money", return_value=viable), \
         patch("main._fo_strike_setup_signals", return_value=(("order_block_delta", lambda d: sig),)), \
         patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value=universe), \
         patch("kotak_fo_candle_feed.read_fo_candles_as_df", return_value=df), \
         patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
         patch("main._real_fo_buy_contract") as buy:
        main._run_fo_strike_setup_scan(conn)
        return buy


def test_strike_scan_buys_strike_whose_candles_match_viable_setup():
    _db()
    sig = {"entry_price": 100.0, "stop_loss": 95.0, "atr_at_entry": 2.0}
    with closing(main.get_db()) as conn:
        buy = _scan(conn, _universe(), _frame(), sig)
        assert buy.call_count == 1
        a = buy.call_args
        assert a[0][3]["kotak_trading_symbol"] == "NIFTY17OCT2625000CE" and a[0][5] == "strike_setup_order_block_delta"
        assert 3.0 <= a[1]["trail_dist"] <= 30.0  # clamped 3-30% of entry


def test_strike_scan_skips_when_not_viable_stale_or_short_history():
    _db()
    sig = {"entry_price": 100.0, "stop_loss": 95.0, "atr_at_entry": 2.0}
    with closing(main.get_db()) as conn:
        assert _scan(conn, _universe(), _frame(), sig, viable=False).call_count == 0
        assert _scan(conn, _universe(), _frame(last_age_s=2000), sig).call_count == 0
        assert _scan(conn, _universe(), _frame(n=10), sig).call_count == 0
        assert _scan(conn, _universe(), _frame(), None).call_count == 0


def test_trail_uses_row_trail_dist():
    _db()
    with closing(main.get_db()) as conn:
        _insert(conn, key="X:SETUP", tag="strike_setup_order_block_delta", trig=None, peak=100.0)
        conn.execute("UPDATE real_fo_positions SET trail_dist = 6.0"); conn.commit()
        with patch("kotak_real_fo_orders.fetch_kotak_option_state", return_value=_state()), \
             patch("main._option_ltp", return_value=120.0), \
             patch("nse_fo_chain.must_force_close_before_expiry", return_value=False), \
             patch("main.kotak_real_orders_closing_session", return_value=False), \
             patch("kotak_real_fo_orders.ensure_option_trailing_sl", return_value={"ok": True, "action": "placed", "order_id": "S", "trigger_price": 114.0}) as ens:
            main._sync_real_fo_option_sl(conn, "X:SETUP")
            assert abs(ens.call_args[0][3] - 114.0) < 1e-6  # peak 120 - 6.0
