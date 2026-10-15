"""B-1274 stage 2 / B-1275: a symbol with an open position, or entered/exited today, is still scanned for every applicable
cell (per-symbol set + counter + trigger evaluation), and no second entry / order is produced."""
import sqlite3

import numpy as np
import pandas as pd

import main


def _reset():
    main._symbol_strategy_scans.clear()
    main._symbol_strategy_scans_day = ""
    main._current_scan_symbol.set(None)
    main._strategy_scan_counts.clear()


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE signal_state_swing (symbol PRIMARY KEY, strategy, entry_day, entry_price, initial_stop_loss, gap_low, qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close)")
    conn.execute("CREATE TABLE signal_state_swing_short (symbol PRIMARY KEY, strategy, entry_day, entry_price, initial_stop_loss, qty, entry_ts, fx_to_inr, atr_at_entry)")
    conn.execute("CREATE TABLE trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload)")
    return conn


def _df1h(n=80):
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.2, n))
    c[-1] = c[-21:].mean() * 0.90  # a drop so the envelope fade fires on the last bar
    idx = pd.date_range("2026-01-01 09:15", periods=n, freq="h")
    return pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": 1000.0,
                         "Date": idx.strftime("%Y-%m-%d %H:%M")})


ONE_H_LONG = set(main.MACDDIV_LONG_LIVE_CELLS) | set(main.ENVELOPE_LONG_LIVE_CELLS) | set(main.CUP_CHEAT_LONG_LIVE_CELLS)


def _no_orders(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda *a, **k: calls.append(("entry", a)))
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: calls.append(("sentry", a)))
    monkeypatch.setattr(main, "_maybe_place_real_swing_exit", lambda *a, **k: calls.append(("exit", a)))
    monkeypatch.setattr(main, "apply_paper_trade", lambda *a, **k: calls.append(("paper", a)))
    return calls


def test_1h_long_pass_open_position_of_other_engine_still_scanned(monkeypatch):
    _reset()
    calls = _no_orders(monkeypatch)
    conn = _conn()
    conn.execute("INSERT INTO signal_state_swing VALUES ('HELD.NS','gap_and_go','2026-01-01',100,90,95,5,1,1.0,2.0,100)")
    conn.commit()
    main._run_long_swing_1h_pass(conn, ["HELD.NS"], 100000, "2026-01-02", set(), fetch=lambda s, p, i: _df1h())
    assert main._symbol_strategy_scans["HELD.NS"] >= ONE_H_LONG
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing").fetchone()[0] == 1
    assert conn.execute("SELECT strategy FROM signal_state_swing").fetchone()[0] == "gap_and_go"
    assert calls == []  # no order, no paper trade


def test_1h_long_pass_done_today_symbol_still_scanned_no_entry(monkeypatch):
    _reset()
    calls = _no_orders(monkeypatch)
    conn = _conn()
    main._run_long_swing_1h_pass(conn, ["DONE.NS"], 100000, "2026-01-02", {"DONE.NS"}, fetch=lambda s, p, i: _df1h())
    assert main._symbol_strategy_scans["DONE.NS"] >= ONE_H_LONG
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing").fetchone()[0] == 0
    assert calls == []
    # the trigger fired (envelope drop) on a blocked symbol: counted as blocked-by-position, not entered
    assert any(v for k, v in main._strategy_entry_blocked_by_position.items() if k != "_day")


def test_1h_long_pass_managed_1h_position_still_scanned(monkeypatch):
    _reset()
    _no_orders(monkeypatch)
    conn = _conn()
    tag = main.ENVELOPE_LONG_LIVE_CELLS[0]
    conn.execute("INSERT INTO signal_state_swing VALUES ('MAN.NS',?,'2099-01-01 09:15',100,1.0,NULL,5,1,1.0,2.0,100)", (tag,))
    conn.commit()
    main._run_long_swing_1h_pass(conn, ["MAN.NS"], 100000, "2026-01-02", set(), fetch=lambda s, p, i: _df1h())
    assert main._symbol_strategy_scans["MAN.NS"] >= ONE_H_LONG
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing").fetchone()[0] == 1


def test_1h_short_pass_blocked_symbols_marked(monkeypatch):
    _reset()
    calls = _no_orders(monkeypatch)
    conn = _conn()
    conn.execute("INSERT INTO signal_state_swing_short VALUES ('OWN.NS','brk20_min_rr__main_replay__short__1d__atr4_rr4__v1','2026-01-01',100,110,5,1,1.0,2.0)")
    conn.commit()
    main._run_short_swing_1h_pass(conn, ["OWN.NS", "DONE.NS"], 100000, "2026-01-02", {"DONE.NS"}, fetch=lambda s, p, i: _df1h())
    for s in ("OWN.NS", "DONE.NS"):
        assert main._symbol_strategy_scans[s] >= set(main.SWINGMINRR_SHORT_1H_CELLS)
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 1
    assert not any(c[0] in ("sentry", "paper") for c in calls)


def test_scan_only_swing_long_cells_cover_every_chain_tag(monkeypatch):
    _reset()
    d = _df1h(300).rename(columns={})
    d["Date"] = pd.date_range("2025-01-01", periods=300, freq="D").strftime("%Y-%m-%d")
    for _ in main._scan_visit(["X.NS"]):
        main._scan_only_swing_long_cells(d, 50.0, count=True, evaluate=True)
    got = main._symbol_strategy_scans["X.NS"]
    want = ({"power_play", "primary_base", "gap_and_go", "minervini_vcp_livermore", "minervini_vcp", "minervini_vcp_be3r",
             main.SWING_EXITINVAL_VP_TAG, main.SWING_EXITINVAL_OB_TAG, main.BRK20_SWING_TAG}
            | set(main.ISLAND_ALL_TAGS) | set(main.SWINGMINRR_TAGS) | set(main.CHAN_SHAPE_CELLS) | set(main.PL1D_CELLS)
            | set(main.GAPFADE_TAGS) | set(main.ONEIL_SWING_CELLS))
    assert got == want
    assert all(main._strategy_scan_counts[t] == 1 for t in want)
    # flat symbol: marks only, the counter is left to the real chain
    _reset()
    for _ in main._scan_visit(["Y.NS"]):
        main._scan_only_swing_long_cells(d, 50.0, count=False, evaluate=False)
    assert main._symbol_strategy_scans["Y.NS"] == want and not main._strategy_scan_counts


def test_daily_swing_pass_open_and_done_symbols_scanned_no_second_entry(monkeypatch):
    _reset()
    calls = _no_orders(monkeypatch)
    conn = _conn()
    conn.execute("CREATE TABLE swing_done_today (day, symbol)")
    conn.execute("INSERT INTO swing_done_today VALUES ('%s','DONE.NS')" % main.ist_now().strftime("%Y-%m-%d"))
    conn.execute("INSERT INTO signal_state_swing VALUES ('HELD.NS','gap_and_go','2099-01-01',100,1.0,1.0,5,1,1.0,2.0,100)")
    conn.commit()
    d = _df1h(300)
    d["Date"] = pd.date_range("2025-01-01", periods=300, freq="D").strftime("%Y-%m-%d")
    monkeypatch.setattr(main, "SWING_WATCHLIST", ["HELD.NS", "DONE.NS"])
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: d.copy())
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: False)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 100000)
    monkeypatch.setattr(main, "_record_swing_check", lambda *a, **k: None)
    for name in ("_run_sector_rotation_entries", "_run_pattern_cell_entries", "_run_short_swing_pass",
                 "_run_short_swing_1h_pass", "_run_long_swing_1h_pass"):
        monkeypatch.setattr(main, name, lambda *a, **k: None)
    main._run_swing_scan_pass(conn)
    for s in ("HELD.NS", "DONE.NS"):
        assert main._symbol_strategies_tested_today(s) >= 20, s
        assert "power_play" in main._symbol_strategy_scans[s] and main.BRK20_SWING_TAG in main._symbol_strategy_scans[s]
    assert [r[0] for r in conn.execute("SELECT symbol FROM signal_state_swing")] == ["HELD.NS"]
    assert not any(c[0] in ("entry", "sentry") for c in calls)


def test_short_swing_pass_blocked_symbol_scanned_no_entry(monkeypatch):
    _reset()
    calls = _no_orders(monkeypatch)
    conn = _conn()
    conn.execute("INSERT INTO signal_state_swing VALUES ('LNG.NS','gap_and_go','2099-01-01',100,1.0,1.0,5,1,1.0,2.0,100)")
    conn.commit()
    d = _df1h(300)
    d["Date"] = pd.date_range("2025-01-01", periods=300, freq="D").strftime("%Y-%m-%d")
    main._run_short_swing_pass(conn, {"LNG.NS": d, "DONE.NS": d.copy()}, 100000, "2099-01-02", {"DONE.NS"})
    for s in ("LNG.NS", "DONE.NS"):
        assert set(main.SHORT_SWING_TAGS) <= main._symbol_strategy_scans[s], s
        assert set(main.SECTOR_FADE_SHORT_CELLS) <= main._symbol_strategy_scans[s]
        assert set(main.MONTH_EFFECT_SHORT_CELLS) <= main._symbol_strategy_scans[s]
    assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 0
    assert not any(c[0] in ("sentry", "paper") for c in calls)


def test_intraday_scan_only_records_chan_cells():
    _reset()
    for _ in main._scan_visit(["AAA.NS"]):
        main._scan_only_intraday_cells("AAA.NS", "long")
        main._scan_only_intraday_cells("AAA.NS", "short")
    got = main._symbol_strategy_scans["AAA.NS"]
    assert set(main.CHAN_LONG_CELLS) | set(main.CHAN_GAP_LONG_CELLS) | set(main.CHAN_SHORT_CELLS) <= got


def test_scan_activity_result_is_cached_30s(monkeypatch):
    import main
    calls = []
    monkeypatch.setattr(main, "_strategy_scan_activity_compute", lambda inc=False: calls.append(1) or {"strategies": []})
    main._SCAN_ACTIVITY_CACHE.clear()
    main.strategy_scan_activity()
    main.strategy_scan_activity()
    assert len(calls) == 1
