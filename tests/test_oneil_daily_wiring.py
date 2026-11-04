"""B-1463: O'Neil ext 1d LONG leaders cell in the live swing scan (main.py replay run 41847222200): mapping, gate,
entry with stop < entry, first-session-only guard, frozen-stop / 40-bar exit, missing index fails closed."""
import dataclasses
import inspect
import sqlite3

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

LEAD = main.ONEIL_LEADERS_1D_TAG
RSS = main.ONEIL_RSSCREEN_1D_TAG
END = "2026-10-30"  # Friday; signal bar


def _leaders_fixture(n=330):
    """Stock flat at 100 with one older 120 high, closes at a fresh 252-bar high (125) on the last bar; ^NSEI dips 10%
    30 bars ago and recovers -> the first new high after the index low."""
    dates = pd.bdate_range(end=END, periods=n)
    c = np.full(n, 100.0)
    c[n - 200] = 120.0
    c[-1] = 125.0
    df = pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": np.full(n, 1000.0)}, index=dates)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in dates]
    ix = np.full(n, 1000.0)
    ix[n - 31] = 900.0
    idx = pd.Series(ix, index=df["Date"].tolist())
    return df, idx


def _today():
    return main._add_nse_trading_days(END, 1)


def test_mapping_registry_gate_per_tag():
    names = {s.name: s for s in sr.REGISTRY}
    m = names[LEAD].metrics
    assert m.pfnet == pytest.approx(1.593) and m.n_trades == 1606 and m.avg_held_bars <= 30
    assert names[LEAD.replace("__nonovl__v2", "_nonovl_segoos__v2")].metrics.pfnet > 1.0
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[LEAD] == LEAD
    assert LEAD not in main.REPLAY_OWED_TAGS
    assert main._is_strategy_viable_for_real_money(LEAD, check_switch=False) is True
    strat = names[LEAD]
    orig = strat.metrics
    object.__setattr__(strat, "metrics", dataclasses.replace(orig, pfnet=0.95))
    try:
        assert main._is_strategy_viable_for_real_money(LEAD, check_switch=False) is False
    finally:
        object.__setattr__(strat, "metrics", orig)
    # rsscreen: registered, deliberately NOT wired (RS population differs from the replay's)
    assert RSS in names and RSS not in main.ONEIL_DAILY_CELLS and RSS not in main._STRATEGY_TAG_TO_REGISTRY_NAME
    assert main._strategy_hold_spec(LEAD) == (40, "1d")
    assert "2xATR14" in main._SWING_SL_RULES[LEAD]


def test_signal_fires_with_stop_below_entry():
    main._ONEIL_DAILY_SIG_CACHE.clear()
    df, idx = _leaders_fixture()
    sig = main.oneil_daily_entry_signal(df, LEAD, idx_close=idx, today=_today())
    assert sig is not None
    assert 0 < sig["stop_loss"] < sig["entry_price"] == 125.0
    atr = main.oneil_atr14(df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float))[-1]
    assert sig["stop_loss"] == pytest.approx(125.0 - 2.0 * atr)
    assert sig["signal_day"] == END
    live = main.oneil_daily_entry_signal(df, LEAD, idx_close=idx, live_px=126.0, today=_today())
    assert live["entry_price"] == 126.0 and live["stop_loss"] == pytest.approx(126.0 - 2.0 * atr)
    # no index fluctuation -> no "first high after the index low"
    flat_idx = pd.Series(1000.0, index=idx.index)
    assert main.oneil_daily_entry_signal(df, LEAD, idx_close=flat_idx, today=_today()) is None


def test_first_session_only():
    main._ONEIL_DAILY_SIG_CACHE.clear()
    df, idx = _leaders_fixture()
    assert main.oneil_daily_entry_signal(df, LEAD, idx_close=idx, today=END) is None  # same day as the signal bar
    later = main._add_nse_trading_days(END, 2)
    assert main.oneil_daily_entry_signal(df, LEAD, idx_close=idx, today=later) is None  # stale signal


def test_missing_index_fails_closed(monkeypatch):
    main._ONEIL_DAILY_SIG_CACHE.clear()
    df, _idx = _leaders_fixture()
    monkeypatch.setitem(main._ONEIL_DAILY_IDX, "close", None)
    assert main.oneil_daily_entry_signal(df, LEAD, today=_today()) is None
    other = pd.Series(1000.0, index=["2001-01-01", "2001-01-02"])  # no overlap with the symbol's dates
    assert main.oneil_daily_entry_signal(df, LEAD, idx_close=other, today=_today()) is None

    def boom(*a, **k):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(main, "fetch_ohlc", boom)
    main._oneil_daily_fetch_index()
    assert main._ONEIL_DAILY_IDX["close"] is None


def test_exit_frozen_stop_and_40_bar_timeout():
    dates = pd.bdate_range(start="2026-11-02", periods=45)
    c = np.full(45, 100.0)
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1.0}, index=dates)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in dates]
    ed = df["Date"].iloc[0]
    assert main.oneil_daily_exit_reason(df.iloc[:39], ed, 95.0, 100.0)[0] is None  # 39 bars incl. entry bar
    assert main.oneil_daily_exit_reason(df.iloc[:40], ed, 95.0, 100.0)[0] == "oneil_max_hold_timeout"
    # entry-session low at the stop is not re-judged by the daily pass (the resting SL covers it)
    hit0 = df.iloc[:5].copy()
    hit0.iloc[0, hit0.columns.get_loc("Low")] = 90.0
    assert main.oneil_daily_exit_reason(hit0, ed, 95.0, 100.0)[0] is None
    hit = df.iloc[:5].copy()
    hit.iloc[3, hit.columns.get_loc("Low")] = 95.0
    assert main.oneil_daily_exit_reason(hit, ed, 95.0, 100.0)[0] == "oneil_stop_hit"
    gap = df.iloc[:5].copy()
    gap.iloc[2, gap.columns.get_loc("Open")] = 94.0
    assert main._oneil_daily_exit_adapter(gap, ed, 95.0, 2.5, 100.0, tag=LEAD)[0] == "oneil_stop_hit"


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE trades (ts REAL, symbol TEXT, action TEXT, qty REAL, price REAL, fx_to_inr REAL, "
                 "strategy TEXT, raw_payload TEXT)")
    return conn


def test_same_signal_never_reentered(monkeypatch):
    sig = {"entry_price": 125.0, "stop_loss": 120.0, "atr_at_entry": 2.5, "signal_day": END}
    monkeypatch.setattr(main, "oneil_daily_entry_signal", lambda *a, **k: dict(sig))
    monkeypatch.setattr(main, "_is_strategy_wired", lambda t: True)
    sized = []
    monkeypatch.setattr(main, "_swing_position_size", lambda *a: sized.append(1) or 0)
    conn = _conn()
    conn.execute("INSERT INTO trades VALUES (1, 'X.NS', 'buy', 1, 125, 1, 'swing', ?)",
                 ('{"entry_reason": "%s", "stop_loss": 120.0, "signal_day": "%s"}' % (LEAD, END),))
    assert main._oneil_daily_try_entry(conn, "X.NS", None, 100000, 0.01, _today(), 1.0) is False
    assert not sized  # returned before sizing: the prior buy of this signal bar blocks it
    conn.execute("DELETE FROM trades")
    assert main._oneil_daily_try_entry(conn, "X.NS", None, 100000, 0.01, _today(), 1.0) is False
    assert sized  # no prior buy -> reached sizing (qty 0 here)


def test_scan_wiring_last_with_real_mirror_exit_branch_and_single_index_fetch():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert src.index("_oneil_swing_try_entry(conn") < src.index("_oneil_daily_try_entry(conn")  # LAST of the chain
    assert 'pos["strategy"] in ONEIL_DAILY_CELLS' in src
    assert src.count("_oneil_daily_fetch_index()") == 1
    assert src.index("_oneil_daily_fetch_index()") < src.index("for symbol in _scan_visit(SWING_WATCHLIST)")
    ent = inspect.getsource(main._oneil_daily_try_entry)
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in ent
    assert "_is_strategy_wired(tag" in ent
    assert "ONEIL_DAILY_CELLS" in inspect.getsource(main._scan_only_swing_long_cells)
    assert not any("ONEIL" in n.upper() and "TRADING_ENABLED" in n.upper() for n in dir(main))  # no new kill switch


def test_signals_computed_once_per_df(monkeypatch):
    main._ONEIL_DAILY_SIG_CACHE.clear()
    df, idx = _leaders_fixture()
    calls = []
    real = main.oneil_ext_signals
    monkeypatch.setattr(main, "oneil_ext_signals", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(3):
        assert main.oneil_daily_entry_signal(df, LEAD, idx_close=idx, today=_today())
    assert len(calls) == 1


# ---- B-1463 scope extension: 13 O'Neil ext 1w LONG cells in the existing weekly path (run 41847932950) ----
W_LEAD = "oneil_leaders__firsthigh__long__1w__atr3_h26_srcmain__nonovl__v2"
EXT_1W = [t for t, cell in main.ONEIL_SWING_CELLS.items() if cell[2] is not None and cell[2][0] == "ext"]


def _weekly_leaders_fixture(weeks=110):
    """Daily bars ending Monday 2026-11-02 (first session of the week). Weekly closes flat 100, one 120 high 40 weeks
    back, the last completed week closes at 125 (a new 52-week high); ^NSEI dips 10% 8 weeks back."""
    dates = pd.bdate_range(end="2026-11-02", periods=5 * weeks + 1)
    c = np.full(len(dates), 100.0)
    c[-1 - 5 * 40] = 120.0
    c[-2] = 125.0  # Friday 2026-10-30 close
    df = pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": np.full(len(c), 1000.0)},
                      index=dates)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in dates]
    ix = np.full(len(c), 1000.0)
    ix[-1 - 5 * 8 - 5:-1 - 5 * 8] = 900.0
    return df, pd.Series(ix, index=df["Date"].tolist())


def test_weekly_ext_cells_mapped_viable_ordered():
    names = {s.name: s for s in sr.REGISTRY}
    assert len(EXT_1W) == 13
    assert main.ONEIL_EXT_1W_RSSCREEN_TAG not in main.ONEIL_SWING_CELLS
    assert not any("__short__" in t for t in main.ONEIL_SWING_CELLS)
    pfs = [names[t].metrics.pfnet for t in main.ONEIL_SWING_CELLS]
    assert pfs == sorted(pfs, reverse=True)  # cascade = PFnet descending, classic cells at their PFnet place
    for t in EXT_1W:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t and t not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is True
        assert names[t.replace("__nonovl__v2", "_nonovl_segoos__v2")].metrics.pfnet > 1.0
        assert main._strategy_hold_spec(t) == (26, "1w")
        fam, _chase, det = main.ONEIL_SWING_CELLS[t]
        assert t.startswith(fam + "__" + det[1] + "__long__1w__atr3_h26")


def test_weekly_leaders_fires_with_stop_and_fails_closed_without_index(monkeypatch):
    main._ONEIL_DAILY_SIG_CACHE.clear()
    df, ix = _weekly_leaders_fixture()
    main._oneil_daily_set_index(ix)
    try:
        sig = main.oneil_swing_entry_signal(df, W_LEAD)
        assert sig is not None and 0 < sig["stop_loss"] < sig["entry_price"]
        w = main.oneil_weekly_from_daily(df).iloc[:-1]
        atr = main.oneil_atr14(w["High"].to_numpy(float), w["Low"].to_numpy(float), w["Close"].to_numpy(float))[-1]
        assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 3.0 * atr)
        late = pd.concat([df, df.iloc[[-1, -1]].assign(Date=["2026-11-03", "2026-11-04"])])
        late.index = pd.to_datetime(late["Date"])
        assert main.oneil_swing_entry_signal(late, W_LEAD) is None  # 3rd session: entry window passed
        main._oneil_daily_set_index(pd.Series(1000.0, index=ix.index))  # no index dip -> no signal
        assert main.oneil_swing_entry_signal(df, W_LEAD) is None
        monkeypatch.setitem(main._ONEIL_DAILY_IDX, "close", None)
        assert main.oneil_swing_entry_signal(df, W_LEAD) is None  # fail closed
    finally:
        main._ONEIL_DAILY_IDX["close"] = None
        main._ONEIL_DAILY_SIG_CACHE.clear()


def test_weekly_ext_signals_computed_once_per_symbol(monkeypatch):
    main._ONEIL_DAILY_SIG_CACHE.clear()
    df, ix = _weekly_leaders_fixture()
    main._oneil_daily_set_index(ix)
    calls = []
    real = main.oneil_ext_signals
    monkeypatch.setattr(main, "oneil_ext_signals", lambda *a, **k: calls.append(1) or real(*a, **k))
    try:
        for t in EXT_1W:
            main.oneil_swing_entry_signal(df, t)
        assert len(calls) == 1
    finally:
        main._ONEIL_DAILY_IDX["close"] = None
        main._ONEIL_DAILY_SIG_CACHE.clear()


def test_weekly_cascade_blocks_same_week_reentry_through_a_sibling_cell(monkeypatch):
    """B-1463: a same-week buy under ANY weekly O'Neil cell blocks every other weekly cell for that symbol."""
    import time as _t
    tags = list(main.ONEIL_SWING_CELLS)
    first, other = tags[0], tags[-1]
    monkeypatch.setattr(main, "oneil_swing_entry_signal",
                        lambda df, tag, *a: {"entry_price": 100.0, "stop_loss": 90.0, "atr_at_entry": 3.0} if tag == other else None)
    monkeypatch.setattr(main, "_is_strategy_wired", lambda t: True)
    sized = []
    monkeypatch.setattr(main, "_swing_position_size", lambda *a: sized.append(1) or 0)
    today = main.dt.datetime.now(main.dt.timezone.utc).strftime("%Y-%m-%d")
    conn = _conn()
    conn.execute("INSERT INTO trades VALUES (?, 'X.NS', 'buy', 1, 100, 1, 'swing', ?)",
                 (_t.time(), '{"entry_reason": "%s", "stop_loss": 90.0}' % first))
    assert main._oneil_swing_try_entry(conn, "X.NS", None, 100000, 0.01, today, 1.0) is False
    assert not sized
    conn.execute("DELETE FROM trades")
    main._oneil_swing_try_entry(conn, "X.NS", None, 100000, 0.01, today, 1.0)
    assert sized
