"""B-842 audit lock: the swing SHORT path (signal_state_swing_short / real_positions_swing_short) carries
(a) a minimum reward:risk rule and (b) a protective BUY stop placed with the entry and healed every 5 minutes.

Audit result (2026-10-27): nothing was missing, so these tests pin the existing guarantees:
  * min R:R: brk20 1d/1h short cells refuse an entry whose room to the prior 60-bar low is < rr x risk (entry gate,
    the validated design); the 1h gatetarget cell also exits at a BUY target = entry - 4 x risk (stop tested first);
  * every code path that opens a paper short-swing row has a stop ABOVE the entry, and only the short-swing real
    entry (which places the BUY SL or unwinds) mirrors it to Kotak;
  * the 5-minute reconcile calls the short-swing heal, the heal protects rows of every family, and the real table
    is in the Upstash generic mirror.
"""
import inspect
import os
import re
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _daily(close, low=None):
    close = np.asarray(close, float)
    idx = pd.bdate_range("2024-01-01", periods=len(close))
    lo = close - 0.3 if low is None else np.asarray(low, float)
    df = pd.DataFrame({"Open": close, "High": close + 0.3, "Low": lo, "Close": close, "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _breakdown(room_low):
    c = np.full(100, 100.0)
    c[-1] = 99.0                      # closes below the prior 20-bar low (99.7)
    lo = c - 0.3
    lo[40] = room_low                 # prior 60-bar low sets the room
    return _daily(c, low=lo)


def test_min_rr_gate_admits_only_when_room_covers_rr_times_risk():
    sig = main.brk20_min_rr_entry_signal(_breakdown(40.0), "short", 3.0, 4.0)
    assert sig is not None and sig["stop_loss"] > sig["entry_price"]
    assert sig["room"] >= 4.0 * sig["risk"] and sig["rr"] >= 4.0
    tight = sig["entry_price"] - 2.0 * sig["risk"]          # room only 2R
    assert main.brk20_min_rr_entry_signal(_breakdown(tight), "short", 3.0, 4.0) is None


def test_every_live_brk20_short_cell_carries_a_min_rr_of_at_least_3():
    assert main.BRK20_SHORT_SWING_CELLS
    for tag, atr, rr in main.BRK20_SHORT_SWING_CELLS:
        assert rr >= 3.0 and atr > 0, tag
    tag, sig = main.short_swing_entry_signal(_breakdown(40.0))
    assert tag in main.SHORT_SWING_TAGS and sig["stop_loss"] > sig["entry_price"]
    assert main.short_swing_entry_signal(_breakdown(98.0)) == (None, None)


def _bars(rows):
    idx = pd.date_range("2024-02-01 09:15", periods=len(rows), freq="h")
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d %H:%M") for d in idx]
    return df


def test_gatetarget_cell_exits_at_entry_minus_rr_risk_and_stop_wins_inside_a_bar():
    tag = main.SWINGMINRR_GATETARGET_SHORT_1H_TAG
    assert main.SWINGMINRR_SHORT_1H_CELLS[tag] == 4.0
    pos = {"strategy": tag, "entry_day": "2024-01-31 15:15", "entry_price": 100.0, "initial_stop_loss": 105.0}
    # target = 100 - 4 x 5 = 80
    assert main._swingminrr_gate_short_exit(_bars([(99, 100, 79.5, 80)]), pos) == ("short_swing_target_hit", 80.0)
    assert main._swingminrr_gate_short_exit(_bars([(99, 106, 79.0, 80)]), pos)[0] == "short_swing_stop_hit"
    assert main._swingminrr_gate_short_exit(_bars([(99, 100, 85, 90)]), pos) is None
    gate = dict(pos, strategy=main.SWINGMINRR_GATE_SHORT_1H_TAG)      # gate cell: no target by design
    assert main._swingminrr_gate_short_exit(_bars([(99, 100, 79.5, 80)]), gate) is None


def test_every_paper_short_swing_insert_has_stop_check_and_mirrors_only_via_real_short_entry():
    src = inspect.getsource(main)
    funcs = [f for _n, f in inspect.getmembers(main, inspect.isfunction)
             if f.__module__ == "main" and "INSERT INTO signal_state_swing_short" in inspect.getsource(f)]
    assert len(funcs) >= 5, [f.__name__ for f in funcs]
    for f in funcs:
        body = inspect.getsource(f)
        assert "_maybe_place_real_swing_short_entry(" in body, f.__name__
        assert "place_real_short_entry(" not in body, f.__name__          # never a direct Kotak order
        assert re.search(r"stop_loss\s*(<=|>)\s*entry_price|stop_loss\"\]\s*>\s*sig\[\"entry_price\"\]|"
                         r"swingminrr_gate_short_entry_signal|short_swing_entry_signal", body), f.__name__
    assert "real_positions_swing_short" in src


def test_real_entry_places_buy_sl_or_unwinds_and_reconcile_heals_every_5_min():
    entry = inspect.getsource(main._maybe_place_real_swing_short_entry)
    assert "_ensure_resting_short_sl(" in entry and "place_real_short_cover(" in entry
    assert "SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED" in entry and "is_real_swing_trading_enabled" in entry
    assert "_heal_real_swing_short_sl(conn, order_rows)" in inspect.getsource(main._reconcile_real_positions_core)
    assert "real_positions_swing_short" in main._GENERIC_MIRROR_TABLES
    assert "signal_state_swing_short" in main._GENERIC_MIRROR_TABLES


def test_heal_protects_rows_of_every_short_swing_family(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_nse_equity_market_open_now", lambda: True)
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda *a, **k: 0)
    placed = []
    monkeypatch.setattr(main, "_ensure_resting_short_sl",
                        lambda sym, qty, trg, product=None: placed.append((sym, qty, trg)) or
                        {"ok": True, "order_id": f"N{len(placed)}", "trigger_price": trg})
    tags = [main.SHORT_SWING_TAGS[0], main.SWINGMINRR_GATETARGET_SHORT_1H_TAG, next(iter(main.SECTOR_FADE_SHORT_CELLS))]
    with closing(main.get_db()) as conn:
        for i, tag in enumerate(tags):
            conn.execute(
                "INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, "
                "opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"S{i}.NS", f"S{i}-EQ", 2, 100.0, "E", 0.0, "2026-10-27", 110.0 + i, None, None, tag))
        conn.commit()
        out = main._heal_real_swing_short_sl(conn, [])
        rows = conn.execute("SELECT sl_order_id FROM real_positions_swing_short").fetchall()
    assert sorted(placed) == [(f"S{i}-EQ", 2, 110.0 + i) for i in range(3)]
    assert all(r["sl_order_id"] for r in rows) and all(e["sl_placed"] for e in out)
