"""B-1600 (e): the island turn1cr LONG 1h _tfs cells that clear pooled PFnet > 1.00 (main.py-function sweep run
43692422951: atr4 1.012, atr2d5 1.004; atr1d5 0.962 is NOT wired) on the long swing engine's 1h leg."""
import inspect

import main

ATR1D5 = "reversal__island_turn1cr_tfs__long__1h__atr1d5_within8__nonovl__v2"


def test_only_qualifying_cells_wired_in_pfnet_order():
    rows = {t: (n, pf) for t, n, pf in main._replay_rows()}
    tags = main.ISLAND_TFS_LONG_1H_TAGS
    assert len(tags) == 2 and all("__long__1h__" in t and "turn1cr_tfs__" in t for t in tags)
    pfs = [rows[t][1] for t in tags]
    assert all(p > 1.0 for p in pfs) and pfs == sorted(pfs, reverse=True)
    assert ATR1D5 not in tags and rows[ATR1D5][1] <= 1.0
    for t, sel, k in main.ISLAND_LONG_1H_CELLS:
        assert sel == main.ISLAND_TURN1CR_TAG and main._ISLAND_ATR_OF_TAG[t] == k
        assert t not in main.REPLAY_FAILED_TAGS and main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert main._registry_entry(t).metrics.pfnet > 1.0 and main._is_strategy_wired(t)


def test_signal_restops_with_cell_k(monkeypatch):
    seen = []

    def fake(df, sel, entry_price=None):
        seen.append(sel)
        return {"signal_close": 100.0, "entry_price": 100.0, "stop_loss": 98.5, "atr_at_entry": 2.0, "risk": 1.5}

    monkeypatch.setattr(main, "island_swing_entry_signal", fake)
    import pandas as pd
    df = pd.DataFrame({"Date": [f"2026-11-1{i // 7} {9 + i % 7:02d}:15" for i in range(30)], "Close": [100.0] * 30})
    a = main._island_long_1h_signal(df, main.ISLAND_TFS_LONG_1H_TAGS[0])
    b = main._island_long_1h_signal(df, main.ISLAND_TFS_LONG_1H_TAGS[1])
    assert a["tf"] == b["tf"] == "1h" and a["entry_price"] == 100.0
    assert abs(a["stop_loss"] - main.brk20_stop_price(100.0, 2.0, 4.0, "long")) < 1e-9
    assert abs(b["stop_loss"] - main.brk20_stop_price(100.0, 2.0, 2.5, "long")) < 1e-9
    assert seen == [main.ISLAND_TURN1CR_TAG] * 2
    assert main._island_long_1h_signal(df, ATR1D5) is None


def test_wired_into_every_1h_leg_path():
    src = inspect.getsource(main._run_long_swing_1h_pass)
    assert "ISLAND_TFS_LONG_1H_TAGS" in src and "_island_long_1h_try_entry" in src
    assert "_island_long_1h_signal" in inspect.getsource(main._scan_only_1h_long_cells)
    assert "ISLAND_TFS_LONG_1H_TAGS" in inspect.getsource(main._with_held_1h_long_symbols)
    assert not set(main.ISLAND_TFS_LONG_1H_TAGS) & main.REPLAY_OWED_TAGS  # owed until replay-verified; the sweep verifies them
    for t in main.ISLAND_TFS_LONG_1H_TAGS:
        assert main._strategy_hold_spec(t)[0] == main.BRK20_MAX_HOLD_BARS
        assert t in main._SWING_SL_RULES


def test_entry_records_sl_first_cell_and_exit_on_1h_bars(monkeypatch):
    from contextlib import closing
    import numpy as np
    import pandas as pd
    placed = []
    monkeypatch.setattr(main, "island_swing_entry_signal", lambda df, tag, entry_price=None: {
        "entry_price": 100.0, "stop_loss": 98.0, "atr_at_entry": 2.0, "risk": 2.0, "signal_close": 100.0,
        "direction": "long", "filter": "turn1cr"})
    monkeypatch.setattr(main, "_swing_position_size", lambda *a, **k: 3)
    monkeypatch.setattr(main, "_sync_signal_state_swing_external", lambda c: None)
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda c, s, q, p, sl, t: placed.append((s, q, p, sl, t)))
    main.init_db()
    n = 80
    dates = [f"2026-10-{1 + i // 7:02d} {9 + i % 7:02d}:15" for i in range(n)]
    c = 100.0 + np.sin(np.arange(n) / 3.0)
    df = pd.DataFrame({"Date": dates, "Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c + 0.1, "Volume": 1e6})
    with closing(main.get_db()) as conn:
        conn.execute("DELETE FROM signal_state_swing WHERE symbol = 'ZZ1H.NS'")
        conn.commit()
        tag = main._island_long_1h_try_entry(conn, "ZZ1H.NS", df, 1e6, 1.0)
        assert tag == main.ISLAND_TFS_LONG_1H_TAGS[0]
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'ZZ1H.NS'").fetchone()
        stop = main.brk20_stop_price(100.0, 2.0, 4.0, "long")
        assert row["strategy"] == tag and row["entry_day"] == dates[-1] and row["initial_stop_loss"] == stop
        assert placed == [("ZZ1H.NS", 3, 100.0, stop, tag)]  # real mirror always carries the SL
        conn.execute("DELETE FROM signal_state_swing WHERE symbol = 'ZZ1H.NS'")
        conn.commit()
    pos = {"strategy": tag, "entry_day": dates[-6], "entry_price": 100.0, "initial_stop_loss": float(df["Low"].iloc[-5]) + 0.01}
    assert main._island_long_4h_exit(df, pos) == ("island_stop_loss", pos["initial_stop_loss"])  # fill bar = next 1h bar
    pos["entry_day"] = dates[-1]
    assert main._island_long_4h_exit(df, pos) is None
