"""B-1427 live wiring: new gap_and_go entries open under the xroc exhaustion-exit tag (main.py replay run 41013761661,
band-live PFnet 1.209), exit via exitfamily_exit_reason, rest the cell's chandelier stop (band floor applied at Kotak
placement), and pass the real-money gate; positions under the old "gap_and_go" tag keep the old exit."""
import json
import os
import sys
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import main  # noqa: E402
import swing_bandcap as bc  # noqa: E402

TAG = main.GAP_AND_GO_XROC_LIVE_TAG
CELL = main.GAP_AND_GO_EXITFAMILY_LIVE_CELLS[TAG]


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


def _frame(n=120, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    o = c * np.exp(rng.normal(0, 0.005, n))
    hi = np.maximum(o, c) * 1.01
    lo = np.minimum(o, c) * 0.99
    d = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c,
                         "Volume": np.full(n, 1e5)}, index=d)


def test_tags_follow_band_grammar_and_cell():
    assert TAG == bc.band_tag(main.GAP_AND_GO_XROC_RESEARCH_TAG, "live")
    assert CELL == {"kind": "exhaust", "atr": 2.5, "trail": 6.0, "x": "roc", "hold": 30}
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[TAG] == TAG
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["gap_and_go"] == "gap_and_go__swing__long__1d__hold30__v1"  # old tag unchanged


def test_registry_rows_and_raw_json():
    import strategy_registry as sr
    by = {d.name: d for d in sr.REGISTRY}
    d = json.load(open(os.path.join(ROOT, "docs", "backtest_data", "gap_and_go_exitfamily_replay_41013761661.json")))
    assert d["run_id"] == "41013761661" and d["n_symbols"] == 2678 and d["cost_round_trip_pct"] == 0.8
    cells = [r for r in d["rows"] if not r["control"]]
    assert len(cells) == 5
    for r in cells:
        for mode, name in (("off", r["off_tag"]), ("live", r["band_tag"])):
            e = by[name]
            assert abs(e.metrics.pfnet - r[mode]["pfnet"]) < 1e-9 and e.metrics.n_trades == r[mode]["n"]
            assert abs(e.metrics.avg_held_hrs - r[mode]["avg_held_bars"] * sr.TRADING_HOURS_PER_DAY) < 1e-9
            assert "41013761661" in e.metrics.run_ref and "exitfamily" in e.source
        # the research-sim row of the bare tag is never overwritten
        assert "41013761661" not in (by[r["tag"]].metrics.run_ref or "")
    live = by[TAG].metrics
    assert abs(live.pfnet - 1.209) < 1e-9 and live.n_trades == 11961


def test_gate_verdict_open_for_live_tag(monkeypatch):
    import strategy_registry as sr
    monkeypatch.setattr(main, "is_trading_enabled", lambda c: True)
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: None)
    monkeypatch.setattr(main, "REAL_ENTRY_REQUIRES_EXPLORER_STACK", False)
    monkeypatch.setattr(sr, "VIABLE_STACK_ACTIVE", False)
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", set())
    assert TAG not in main.REPLAY_OWED_TAGS and TAG not in main.REPLAY_FAILED_TAGS
    assert main._viability_verdict(TAG) == (True, "viable")
    assert main._is_strategy_wired(TAG) is True
    # a floor above the band-live PFnet closes it (derived at read time)
    assert main._registry_entry(TAG).is_viable(1.3) is False


def test_entry_signal_uses_cell_stop_and_entry_bar_atr(monkeypatch):
    df = _frame()
    monkeypatch.setattr(main, "gap_and_go_entry_signal", lambda d: {"entry_price": float(d["Close"].iloc[-1]),
                                                                     "stop_loss": 1.0, "gap_low": 95.0})
    sig = main.gap_and_go_exitfamily_entry_signal(df, TAG)
    atr = main.exitfamily_atr_at_entry(df)
    assert abs(sig["atr_at_entry"] - atr) < 1e-12
    assert abs(sig["stop_loss"] - (sig["entry_price"] - 2.5 * atr)) < 1e-9 and sig["gap_low"] == 95.0
    assert main.gap_and_go_exitfamily_entry_signal(df, "gap_and_go") is None
    monkeypatch.setattr(main, "gap_and_go_entry_signal", lambda d: None)
    assert main.gap_and_go_exitfamily_entry_signal(df, TAG) is None


def test_stop_level_trails_chandelier_and_band_floor_parity():
    init, atr = 90.0, 4.0
    assert main._swing_strategy_stop_level(TAG, init, atr, 100.0) == 90.0  # 100 - 24 = 76 < initial
    assert main._swing_strategy_stop_level(TAG, init, atr, 130.0) == 106.0  # 130 - 6 x 4
    assert main._swing_strategy_stop_level(TAG, init, None, 130.0) == 90.0  # no ATR: never guesses a trail
    assert main._swing_strategy_stop_level("gap_and_go", init, atr, 130.0) == 90.0  # old tag: frozen, unchanged
    # the replay's live model rests max(cell stop, prev close x 0.9 x 1.003); Kotak's pre-send clamp is that same floor
    strat = main._swing_strategy_stop_level(TAG, init, atr, 130.0)
    trig, banded = bc.resting_trigger(strat, 125.0, "long")
    assert banded and abs(trig - 125.0 * 0.9 * 1.003) < 1e-9
    import kotak_real_orders as kro
    orig = kro._band_reference
    try:
        kro._band_reference = lambda s: (125.0, 124.0)
        clamped, frm = kro._preclamp_long_stop("ABC-EQ", strat)
        assert frm == strat and abs(clamped - 125.0 * 0.9 * 1.003) < 0.051
    finally:
        kro._band_reference = orig


def test_replace_stop_after_overnight_cancel_comes_back_trailed():
    _fresh_db()
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                     "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES "
                     "('XR.NS', ?, '2026-10-01', 100, 90, 95, 5, 1, 1.0, 4.0, 130)", (TAG,))
        conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                     "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES "
                     "('OLD.NS', 'gap_and_go', '2026-10-01', 100, 90, 95, 5, 1, 1.0, 4.0, 130)")
        conn.commit()
        assert main._swing_stop_floored(conn, "XR.NS", 90.0) == 106.0
        assert main._swing_stop_floored(conn, "OLD.NS", 90.0) == 90.0  # other tags unchanged
        # missing ATR column: recovered from (entry - initial stop) / 2.5
        conn.execute("UPDATE signal_state_swing SET atr_at_entry = NULL WHERE symbol = 'XR.NS'")
        assert main._swing_stop_floored(conn, "XR.NS", 90.0) == 106.0


def test_exit_adapter_matches_exitfamily_walk_and_ratchets_running_max():
    df = _frame(200, seed=7)
    i0 = 60
    ep = float(df["Close"].iloc[i0])
    atr = main.exitfamily_atr_at_entry(df.iloc[:i0 + 1])
    init = main.exitfamily_initial_stop(ep, atr, CELL)
    day = df["Date"].iloc[i0]
    for k in range(i0 + 1, len(df)):
        part = df.iloc[:k + 1]
        reason, rmc = main._gap_and_go_exitfamily_exit_adapter(part, day, init, atr, ep, TAG, ep)
        w = main.exitfamily_walk(part, day, ep, atr, CELL)
        assert reason == w["reason"]
        if reason:
            break
        assert rmc == max(ep, w["running_max"])
    assert main._gap_and_go_exitfamily_exit_adapter(df.iloc[:0], day, init, atr, ep, TAG, ep) == (None, ep)


def _scan(monkeypatch, df, sym):
    monkeypatch.setattr(main, "SWING_WATCHLIST", [sym])
    monkeypatch.setattr(main, "fetch_ohlc", lambda symbol, period, interval: df)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 400000.0)
    for fn in ("power_play_entry_signal", "primary_base_entry_signal"):
        monkeypatch.setattr(main, fn, lambda d: None)


def test_scan_entry_records_xroc_tag_with_atr_and_real_mirror(monkeypatch):
    _fresh_db()
    df = _frame(300)
    _scan(monkeypatch, df, "NEWGG.NS")
    monkeypatch.setattr(main, "gap_and_go_entry_signal",
                        lambda d: {"entry_price": float(d["Close"].iloc[-1]), "stop_loss": 1.0, "gap_low": 95.0})
    calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_entry", lambda *a, **k: calls.append(a))
    with closing(main.get_db()) as conn:
        main._run_swing_scan(conn)
        row = conn.execute("SELECT * FROM signal_state_swing WHERE symbol = 'NEWGG.NS'").fetchone()
        assert row["strategy"] == TAG
        assert row["atr_at_entry"] and row["atr_at_entry"] > 0
        assert abs(row["initial_stop_loss"] - (row["entry_price"] - 2.5 * row["atr_at_entry"])) < 1e-9
        assert row["running_max_close"] == row["entry_price"] and row["gap_low"] == 95.0
        n = conn.execute("SELECT COUNT(*) FROM signal_state_swing").fetchone()[0]
        assert n == 1  # one entry, never a second competing gap_and_go row
    assert calls and calls[0][-1] == TAG and abs(calls[0][4] - row["initial_stop_loss"]) < 1e-9


def test_scan_exit_dispatch_old_tag_unaffected_new_tag_exitfamily(monkeypatch):
    _fresh_db()
    df = _frame(300)
    _scan(monkeypatch, df, "OLDGG.NS")
    seen = {"old": 0, "new": 0}
    monkeypatch.setattr(main, "gap_and_go_exit_reason", lambda *a, **k: seen.__setitem__("old", seen["old"] + 1))
    monkeypatch.setattr(main, "_gap_and_go_exitfamily_exit_adapter",
                        lambda *a, **k: (seen.__setitem__("new", seen["new"] + 1), (None, 123.0))[1])
    monkeypatch.setattr(main, "_maybe_place_real_swing_exit", lambda *a, **k: None)
    day = df["Date"].iloc[-30]
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                     "qty, entry_ts, fx_to_inr) VALUES ('OLDGG.NS', 'gap_and_go', ?, 100, 1, 1, 5, 1, 1.0)", (day,))
        conn.commit()
        main._run_swing_scan(conn)
        assert seen == {"old": 1, "new": 0}
    _fresh_db()
    _scan(monkeypatch, df, "NEWGG.NS")
    with closing(main.get_db()) as conn:
        conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                     "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES "
                     "('NEWGG.NS', ?, ?, 100, 90, 95, 5, 1, 1.0, 4.0, 100)", (TAG, day))
        conn.commit()
        main._run_swing_scan(conn)
        assert seen == {"old": 1, "new": 1}
        assert conn.execute("SELECT running_max_close FROM signal_state_swing WHERE symbol='NEWGG.NS'").fetchone()[0] == 123.0


def test_dashboard_rules_hold_spec_and_time_limit():
    assert main._sl_kind("swing", TAG) == "trail"
    assert main._strategy_hold_spec(TAG) == (30, "1d")
    assert main._swing_time_limit_calendar_days(TAG) == main._swing_time_limit_calendar_days("gap_and_go")
