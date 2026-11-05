"""B-1467: sector rotation momentum N=3 cell (main replay run 41861798852) cascades ahead of the live N=5 cell."""
import sqlite3

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

N3 = main.SECTOR_ROT_N3_TAG


def test_registry_gate_and_order():
    names = {s.name: s for s in sr.REGISTRY}
    m = names[N3].metrics
    assert m.pfnet > 1.0 and m.n_trades >= 30 and m.avg_held_bars <= 30
    assert names[N3[:-4] + "_segoos__v1"].metrics.pfnet > 1.0
    assert list(main.SECTOR_ROT_CELLS)[:2] == [N3, main.SECTOR_ROT_TAG]  # B-1471: L5/L3 cells appended
    assert main.SECTOR_ROT_CELLS[N3] == 3 and main.SECTOR_ROT_CELLS[main.SECTOR_ROT_TAG] == 5
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[N3] == N3 and N3 not in main.REPLAY_OWED_TAGS
    assert main._is_strategy_viable_for_real_money(N3, check_switch=False) is True
    assert main._strategy_hold_spec(N3) == (main.SECTOR_ROT_HOLD_DAYS, "1d")


def test_top3_enter_under_n3_and_4_5_under_n5(monkeypatch):
    syms = [f"S{k}.NS" for k in range(7)]
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {s: "IT" for s in syms})
    dfs = {}
    for k, s in enumerate(syms):
        c = np.linspace(100, 100, 40)
        c[-1] = 100 + (k + 1)  # every stock up on the last bar; S6 strongest
        dfs[s] = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e5,
                               "Date": [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-10-30", periods=40)]})
    monkeypatch.setattr(main, "_swing_position_size", lambda *a: 1)
    monkeypatch.setattr(main, "apply_paper_trade", lambda *a: None)
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda *a: None)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE signal_state_swing (symbol TEXT, strategy TEXT, entry_day TEXT, entry_price REAL, "
                 "initial_stop_loss REAL, gap_low REAL, qty REAL, entry_ts REAL, fx_to_inr REAL, atr_at_entry REAL, "
                 "running_max_close REAL)")
    conn.execute("CREATE TABLE trades (ts REAL, symbol TEXT, action TEXT, qty REAL, price REAL, fx_to_inr REAL, "
                 "strategy TEXT, raw_payload TEXT)")
    main._run_sector_rotation_entries(conn, dfs, 100000, "2026-11-02")
    got = dict(conn.execute("SELECT symbol, strategy FROM signal_state_swing").fetchall())
    assert {s for s, t in got.items() if t == N3} == {"S6.NS", "S5.NS", "S4.NS"}
    assert {s for s, t in got.items() if t == main.SECTOR_ROT_TAG} == {"S3.NS", "S2.NS"}
    for s, t in got.items():
        stop = conn.execute("SELECT initial_stop_loss, entry_price FROM signal_state_swing WHERE symbol=?", (s,)).fetchone()
        assert 0 < stop[0] < stop[1]
