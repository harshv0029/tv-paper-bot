"""B-1615: generic daily swing exit-state rebuild for real holdings whose signal_state_swing row was lost."""
import os
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd

import main

SYM, TRD, STRAT = "UPL.NS", "UPL-EQ", "power_play"


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    main._orphan_1d_state_last_day = None


def _daily():
    days = pd.bdate_range("2026-08-03", "2026-11-16")
    close = np.linspace(600, 700, len(days))
    return pd.DataFrame({"Date": days, "Open": close, "High": close + 10, "Low": close - 10, "Close": close,
                         "Volume": 1000})


def _real_row(c, strategy=STRAT, stop=640.0, day="2026-10-20", entry=650.0):
    c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
              "stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES (?, ?, 3, ?, 1792000000, ?, ?, 'SL1', ?, ?)",
              (SYM, TRD, entry, day, stop, stop, strategy))
    c.commit()


def _rebuild(c, held=True, df=None):
    holdings = {TRD: {"qty": 3, "avg_price": 650.0, "symbol": SYM}} if held else {}
    with patch("main._kotak_holdings_open_by_trdsym", return_value=holdings), \
            patch("main._kotak_symbol_still_open", return_value=False), \
            patch("main._sync_signal_state_swing_external") as sync, \
            patch("main._maybe_place_real_swing_exit") as ex, \
            patch("main.ist_now", return_value=main.dt.datetime(2026, 11, 16, 10, 0)), \
            patch("kotak_real_orders.ensure_resting_sl") as sl:
        out = main._ensure_daily_swing_state_for_orphans(c, fetch=lambda *a, **k: (df if df is not None else _daily()))
    return out, sync, ex, sl


def test_daily_orphan_is_rebuilt_without_any_order():
    _fresh_db()
    df = _daily()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        out, sync, ex, sl = _rebuild(c, df=df)
        st = c.execute("SELECT * FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
        pos = c.execute("SELECT qty FROM positions WHERE symbol = ?", (SYM,)).fetchone()
        real = c.execute("SELECT * FROM real_positions_swing WHERE symbol = ?", (SYM,)).fetchone()
    d = df["Date"].astype(str).str[:10]
    exp_atr = main._compute_atr_value(df[(d < "2026-10-20").to_numpy()], 14)
    exp_max = float(df[((d >= "2026-10-20") & (d < "2026-11-16")).to_numpy()]["Close"].max())
    assert out[0]["derived"] is True and out[0]["entry_day"] == "2026-10-20" and out[0]["stop"] == 640.0
    assert st["strategy"] == STRAT and st["entry_day"] == "2026-10-20" and st["entry_price"] == 650.0
    assert abs(st["atr_at_entry"] - exp_atr) < 1e-9
    assert abs(st["running_max_close"] - exp_max) < 1e-9  # today's forming bar is not counted
    assert pos["qty"] == 3 and sync.called
    ex.assert_not_called()
    sl.assert_not_called()
    assert real["sl_order_id"] == "SL1" and real["stop_loss"] == 640.0


def test_entry_day_stop_preferred_and_once_per_day():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c, stop=645.0)
        main._swing_entry_stop_record(c, SYM, 640.0, "entry", replace=True)
        _rebuild(c)
        assert c.execute("SELECT initial_stop_loss FROM signal_state_swing").fetchone()[0] == 640.0
        c.execute("DELETE FROM signal_state_swing")
        c.commit()
        out, *_ = _rebuild(c)
    assert out == []  # once per IST day


def test_not_held_unknown_and_bad_stop_are_never_invented():
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        out, *_ = _rebuild(c, held=False)
        assert out == [{"symbol": SYM, "derived": False, "why": "not held at Kotak"}]
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c)
        with patch("main._kotak_holdings_open_by_trdsym", return_value=None):
            assert main._ensure_daily_swing_state_for_orphans(c, fetch=lambda *a, **k: _daily()) == []
        assert main._orphan_1d_state_last_day is None
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c, stop=0)
        out, *_ = _rebuild(c)
        assert c.execute("SELECT 1 FROM signal_state_swing").fetchone() is None
        assert out[0]["derived"] is False


def test_strategies_with_their_own_restore_are_left_alone():
    for strat in ("order_block_delta", "gap_and_go", main.MACDDIV_LONG_LIVE_CELLS[0] if isinstance(
            main.MACDDIV_LONG_LIVE_CELLS, (list, tuple)) else next(iter(main.MACDDIV_LONG_LIVE_CELLS))):
        _fresh_db()
        with main.closing(main.get_db()) as c:
            _real_row(c, strategy=strat)
            out, *_ = _rebuild(c)
            assert out == [] and c.execute("SELECT 1 FROM signal_state_swing").fetchone() is None


def test_wired_into_scheduler_after_the_1h_restore():
    import inspect
    src = inspect.getsource(main._scheduler_tick)
    assert src.index("_ensure_1h_swing_state_for_orphans") < src.index("_ensure_daily_swing_state_for_orphans")
