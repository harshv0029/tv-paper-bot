"""B-320: a real single-strike option entry without a protective SL is unwound at once
(no trade without SL, 2026-10-11), and real_fo_positions survives a simulated Render wipe."""
import os
import tempfile
import time
from contextlib import ExitStack, closing
from unittest.mock import patch

import main

CONTRACT = {"kotak_trading_symbol": "NIFTY17OCT26C25000PE", "instrument_token": "999",
            "exchange_segment": "nse_fo", "expiry": "2026-10-17", "strike": 25000.0,
            "dte": 5, "iv": 0.2, "atm_iv": 0.2, "delta": 0.5, "lot_size": 25, "premium": 100.0}


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _buy_patches():
    return [patch("main.is_real_fo_trading_enabled", return_value=True),
            patch("main._is_strategy_viable_for_real_money", return_value=True),
            patch("main._day_open_capital_inr", return_value=1e6),
            patch("main._real_loss_budget", return_value={"ok": True, "real_pnl_today": 0, "detail": ""}),
            patch("nse_fo_chain.select_nse_option_contract", return_value=(CONTRACT, None)),
            patch("kotak_real_fo_orders.check_margin_affordable", return_value={"ok": True}),
            patch("kotak_real_fo_orders.place_real_fo_entry", return_value={"ok": True, "order_id": "E1"})]


def _run(sync_result):
    _db()
    with ExitStack() as es:
        for p in _buy_patches():
            es.enter_context(p)
        es.enter_context(patch("main._sync_real_fo_option_sl", return_value=sync_result))
        close = es.enter_context(patch("main._close_real_fo_option_leg", return_value=True))
        conn = es.enter_context(closing(main.get_db()))
        main._maybe_place_real_fo_put_entry(conn, "^NSEI", 25000.0, "x")
        return close


def test_entry_without_sl_is_unwound_immediately():
    close = _run("sl_failed")
    assert close.called
    reason = close.call_args[0][2]
    assert "unwound" in reason and "SL could not be placed" in reason


def test_entry_with_sl_is_not_unwound():
    assert not _run("placed").called


def test_real_fo_positions_restored_after_simulated_wipe(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    _db()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        c.execute(
            "INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, instrument_token, "
            "exchange_segment, expiry, strike, lot_size, qty, entry_price, entry_order_id, opened_at, day, peak_price) "
            "VALUES ('NIFTY:PUT','NIFTY','single_leg_put','NIFTY17OCT26C25000PE','999','nse_fo','2026-10-17',25000.0,25,25,"
            "100.0,'o1',?, '2026-10-08',100.0)", (time.time(),))
        c.commit()
    main.sync_generic_tables_external()
    _db()  # Render restart wipes SQLite
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        r = c.execute("SELECT leg_key, qty FROM real_fo_positions").fetchall()
    assert [(x["leg_key"], x["qty"]) for x in r] == [("NIFTY:PUT", 25)]
