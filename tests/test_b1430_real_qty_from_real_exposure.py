"""B-1430: a real intraday entry is sized from REAL exposure only (Kotak's Net already nets real margin), never
from the paper qty shrunk by paper-only notional. DABUR short, 2026-10-30 IST: Kotak Net Rs9,621.06, Rs6,500 of
paper-only notional open, entry 365.50, stop 383.03 -> 2 shares by the 1%-of-half-capital formula, 1 was sold.
"""
import math
import os
import tempfile
from contextlib import closing
from unittest.mock import patch

import main

CAPITAL = 9621.06
ENTRY, STOP = 365.50, 383.03


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _seed(conn, short=True, strategy=None, paper_stop=STOP):
    today = main.ist_now().strftime("%Y-%m-%d")
    # Rs 6,500 paper-only notional: a paper long with no real row behind it (the real gate refused it).
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, "
        "entry_ts, fx_to_inr, interval) VALUES ('PAPERONLY.NS', ?, 'long', 650.0, 640.0, 640.0, 700.0, 10, ?, 1.0, '5m')",
        (today, main.time.time()))
    conn.commit()
    deployed = main.deployed_notional(conn)
    assert abs(deployed - 6500.0) < 1e-6
    # Paper sizing exactly as the chan_gap short batch does it -> 1 share.
    usable = min(max(0.0, CAPITAL - deployed), CAPITAL / main.CAPITAL_TRANCHES)
    paper_qty = float(math.floor(min(usable * 1.0 / 100 / abs(paper_stop - ENTRY), usable / ENTRY)))
    assert paper_qty == 1.0
    if short:
        conn.execute(
            "INSERT INTO signal_state_short (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, "
            "entry_ts, fx_to_inr, interval, strategy) VALUES ('DABUR.NS', ?, 'short', ?, ?, ?, 3.66, ?, ?, 1.0, '5m', ?)",
            (today, ENTRY, paper_stop, paper_stop, paper_qty, main.time.time(), strategy or main.CHAN_GAP_SHORT_TAG))
    else:
        conn.execute(
            "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, "
            "entry_ts, fx_to_inr, interval, strategy) VALUES ('DABUR.NS', ?, 'long', ?, ?, ?, 999.0, ?, ?, 1.0, '5m', ?)",
            (today, ENTRY, paper_stop, paper_stop, paper_qty, main.time.time(), strategy))
    conn.commit()


def _common_patches():
    return [
        patch.object(main, "is_real_trading_enabled", return_value=True),
        patch.object(main, "_etf_entry_range_ok", return_value=(True, "")),
        patch("kotak_live_feed.get_live_ticks",
              return_value={"DABUR.NS": {"ltp": ENTRY, "trading_symbol": "DABUR-EQ"}}),
        patch.object(main, "_kotak_bought_today", return_value=False),
        patch.object(main, "_is_strategy_viable_for_real_money", return_value=True),
        patch.object(main, "_load_viable_overrides", return_value=None),
        patch.object(main, "_real_loss_budget", return_value={"real_pnl_today": 0.0, "ok": True, "detail": None}),
        patch.object(main, "_real_today_spent_inr", return_value=0.0),
        patch.object(main, "_effective_real_daily_cap_inr", return_value=CAPITAL),
        patch.object(main, "_refresh_real_capital_cache", return_value=None),
        patch.object(main, "get_scheduler_capital_inr", return_value=CAPITAL),
        patch.object(main, "_real_entry_stop_too_close", return_value=None),
        patch.object(main, "ist_now", return_value=main.ist_now().replace(hour=9, minute=25)),
    ]


def _run_short(strategy=None):
    _fresh_db()
    with closing(main.get_db()) as conn:
        _seed(conn, short=True, strategy=strategy)
        ps = _common_patches()
        for p in ps:
            p.start()
        try:
            with patch("kotak_real_orders.place_real_short_entry",
                       return_value={"ok": False, "detail": "test stop"}) as place:
                main._maybe_place_real_short_entry(conn, "DABUR.NS")
        finally:
            for p in ps:
                p.stop()
        return place


def test_dabur_short_real_qty_is_two_not_one():
    place = _run_short()
    place.assert_called_once()
    assert place.call_args[0][1] == 2


def test_confidence_sized_orb_tag_still_mirrors_paper_qty():
    place = _run_short(strategy="orb-range-short")
    place.assert_called_once()
    assert place.call_args[0][1] == 1


def test_formula_helper_numbers():
    with patch.object(main, "_refresh_real_capital_cache", return_value=None), \
         patch.object(main, "get_scheduler_capital_inr", return_value=CAPITAL):
        # usable 4,810.53; 1% risk 48.11; stop distance 17.53 -> 2.74 -> 2
        assert main._real_qty_by_risk(ENTRY, STOP, 1.0, short=True) == 2
        assert main._real_qty_by_risk(ENTRY, STOP, 1.0, short=False) == 0  # stop on the wrong side
        assert main._real_qty_by_risk(ENTRY, None, 1.0, short=True) == 0
    with patch.object(main, "_refresh_real_capital_cache", return_value=None), \
         patch.object(main, "get_scheduler_capital_inr", return_value=600.0):
        assert main._real_qty_by_risk(ENTRY, 365.0, 1.0) == 0  # usable 300 < one share: capital cap binds


def test_daily_cap_still_binds():
    _fresh_db()
    with closing(main.get_db()) as conn:
        _seed(conn, short=True)
        ps = _common_patches()
        for p in ps:
            p.start()
        try:
            with patch.object(main, "_effective_real_daily_cap_inr", return_value=400.0), \
                 patch("kotak_real_orders.place_real_short_entry",
                       return_value={"ok": False, "detail": "test stop"}) as place:
                main._maybe_place_real_short_entry(conn, "DABUR.NS")
        finally:
            for p in ps:
                p.stop()
        place.assert_called_once()
        assert place.call_args[0][1] == 1  # floor(400 / 365.50)


def test_long_entry_uses_real_capital_basis():
    import inspect
    src = inspect.getsource(main._maybe_place_real_entry)
    assert "_real_intraday_qty_basis(" in src and "min(paper_qty" not in src
    src = inspect.getsource(main._maybe_place_real_short_entry)
    assert "_real_intraday_qty_basis(" in src and "min(paper_qty" not in src
