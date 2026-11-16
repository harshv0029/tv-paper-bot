"""B-1485: brk20 1h cells exit on the peak-HIGH 0.5R trail (run 43803665426), checked from the bar after the fill bar."""
import sqlite3

import pandas as pd

import main

TAG = main.BRK20_1H_LONG_TAG


def _df(rows):
    return pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close"])


def _rows(n_up=3):
    # bar0 = signal, bar1 = fill (its high must NOT join the peak), then rising bars, then a drop through the trail
    r = [["2026-11-16 09:15:00", 100, 101, 99, 100], ["2026-11-16 10:15:00", 100, 130, 99.5, 100.5]]
    px = 100.5
    for i in range(n_up):
        r.append([f"2026-11-16 {11 + i}:15:00", px, px + 2, px - 0.2, px + 1.5])
        px += 1.5
    return r, px


def test_cells_and_rule():
    assert set(main.SWING_1H_PEAK_LTP_TRAIL_CELLS) == set(main.BRK20_1H_LONG_CELLS)
    for _t, (n, reg) in main.SWING_1H_PEAK_LTP_TRAIL_CELLS.items():
        assert n == 0.5 and "trailltp0d5r" in reg and "__1h__" in reg
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE swing_exit_variant (symbol, entry_day, strategy, mode, registry_tag, updated_at)")
    assert main._swing_long_trail_rule(conn, "X", TAG, "2026-11-16 09:15:00") == ("ltp", 0.5)
    assert TAG in main._SWING_SL_RULES and "1h" in main._SWING_SL_RULES[TAG]


def test_trail_hit_before_strategy_exit_and_fill_high_excluded():
    rows, px = _rows()
    # R = 100 - 90 = 10; peak of bars after fill = 100.5+3*1.5+... highs: 102.5, 104, 105.5 -> level 105.5 - 5 = 100.5
    rows.append(["2026-11-16 14:15:00", px, px + 0.1, 99.0, 99.5])
    pos = {"strategy": TAG, "entry_day": "2026-11-16 09:15:00", "entry_price": 100.0, "initial_stop_loss": 90.0}
    ex = main._brk20_long_1h_exit(_df(rows), pos)
    assert ex is not None and ex[0] == "brk20_trail_stop_hit"
    assert abs(ex[1] - 100.5) < 1e-9  # not 130 - 5 (the fill bar's 130 high never joins the peak)


def test_peak_stored_and_replaced():
    rows, _px = _rows()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE swing_exit_variant (symbol, entry_day, strategy, mode, registry_tag, updated_at)")
    conn.execute("CREATE TABLE swing_trail_peak (symbol TEXT, side TEXT, entry_day TEXT, peak REAL, updated_at REAL,"
                 " PRIMARY KEY (symbol, side))")
    conn.execute("INSERT INTO swing_trail_peak VALUES ('X', 'long', '2026-11-16', 999.0, 0)")  # stale same-day row
    pos = {"strategy": TAG, "entry_day": "2026-11-16 09:15:00", "entry_price": 100.0, "initial_stop_loss": 90.0}
    main._brk20_long_1h_exit(_df(rows), pos, conn, "X")
    assert abs(main._swing_trail_peak_get(conn, "X", "long", pos["entry_day"]) - 105.5) < 1e-9


def test_non_trail_tag_unchanged(monkeypatch):
    rows, px = _rows()
    rows.append(["2026-11-16 14:15:00", px, px + 0.1, 99.0, 99.5])
    pos = {"strategy": TAG, "entry_day": "2026-11-16 09:15:00", "entry_price": 100.0, "initial_stop_loss": 90.0}
    monkeypatch.setattr(main, "SWING_1H_PEAK_LTP_TRAIL_CELLS", {})
    ex = main._brk20_long_1h_exit(_df(rows), pos)
    assert ex is None or ex[0] != "brk20_trail_stop_hit"
