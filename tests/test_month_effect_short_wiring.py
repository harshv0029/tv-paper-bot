"""B-965: month-effect SHORT 15m cells wired into the short-swing engine (paper live; real leg fail-closed on the overnight
product; PFnet gate closed by REPLAY_OWED_TAGS until a main.py-calling replay is on file). Real main.month_effect_* fns."""
import os
import re
import sys
import tempfile

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import month_effect_main_replay as R  # noqa: E402

WANT = ["atr6_h25", "atr4_h25", "atr2d5_h25", "atr6_h125"]


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _frame15(n=60, start="2026-08-31 09:15"):
    """15m bars spanning an Aug->Sep month change (25 bars/session)."""
    idx = []
    day = pd.Timestamp(start)
    while len(idx) < n:
        if day.weekday() < 5:
            idx += [day + pd.Timedelta(minutes=15 * k) for k in range(25)]
        day = (day + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=9, minutes=15)
    idx = pd.DatetimeIndex(idx[:n])
    c = np.full(n, 100.0)
    return pd.DataFrame({"Open": c, "High": c + 1.0, "Low": c - 1.0, "Close": c, "Volume": 1000.0}, index=idx)


def test_cells_tags_and_gate_mapping():
    assert [t.split("__")[4] for t in main.MONTH_EFFECT_SHORT_CELLS] == WANT
    names = {s.name for s in sr.REGISTRY}
    for tag in main.MONTH_EFFECT_SHORT_CELLS:
        assert re.match(r"^month__effect__short__15m__atr\d(d\d)?_h\d+__v1$", tag)
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
        assert tag in names                       # registered with real metrics (never merged with atrnone cells)
        assert "atrnone" not in tag               # no-stop cells are not wired (no trade without SL)
        assert tag in main.REPLAY_OWED_TAGS       # gate closed until a main.py-calling replay is on file


def test_gate_closed_for_real_money_while_replay_owed():
    for tag in main.MONTH_EFFECT_SHORT_CELLS:
        assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is False


def test_signal_only_on_first_bar_of_september():
    df = _frame15()
    idx = pd.DatetimeIndex(df.index)
    first = [i for i in range(1, len(idx)) if idx[i].month != idx[i - 1].month][0]
    assert idx[first].month == 9
    assert main.month_effect_short_entry_signal(df.iloc[:first + 1], 6.0) is not None
    assert main.month_effect_short_entry_signal(df.iloc[:first], 6.0) is None          # still August
    assert main.month_effect_short_entry_signal(df.iloc[:first + 2], 6.0) is None      # second Sept bar
    assert main.month_effect_short_entry_signal(df.iloc[:first + 1], 0) is None


def test_stop_and_no_stop_no_entry():
    assert main.month_effect_short_stop(100.0, 2.0, 2.5) == 105.0
    assert main.month_effect_short_stop(100.0, 0.0, 2.5) is None
    assert main.month_effect_short_stop(100.0, 2.0, 0) is None


def test_exit_gap_aware_stop_then_timeout():
    df = _frame15(40)
    assert main.month_effect_short_exit_reason(df.iloc[:12], 10, 105.0, 25) is None
    r = main.month_effect_short_exit_reason(df.iloc[:35], 10, 105.0, 25)               # 25th bar from fill
    assert r == ("max_hold", 100.0)
    g = df.copy()
    g.iloc[12, g.columns.get_loc("Open")] = 110.0
    g.iloc[12, g.columns.get_loc("High")] = 111.0
    assert main.month_effect_short_exit_reason(g.iloc[:13], 10, 105.0, 25) == ("stop", 110.0)   # gap above stop


def test_daily_exit_stop_and_hold_days():
    tag = main._month_effect_short_cell_tag(6.0, 25)
    d = pd.DataFrame({"Open": [100.0] * 6, "High": [100.5] * 6, "Low": [99.0] * 6, "Close": [100.0] * 6,
                      "Date": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08"]})
    pos = {"strategy": tag, "entry_day": "2026-09-01", "initial_stop_loss": 106.0}
    assert main._month_effect_short_exit_daily(d.iloc[:1], pos) is None
    assert main._month_effect_short_exit_daily(d.iloc[:2], pos) == ("short_swing_max_hold_timeout", 100.0)   # 1 session
    d.loc[1, "High"], d.loc[1, "Open"] = 108.0, 107.0
    assert main._month_effect_short_exit_daily(d.iloc[:2], pos) == ("short_swing_stop_hit", 107.0)
    tag5 = main._month_effect_short_cell_tag(6.0, 125)
    p5 = {"strategy": tag5, "entry_day": "2026-09-01", "initial_stop_loss": 120.0}
    d2 = d.copy()
    d2.loc[1, ["High", "Open"]] = 100.5, 100.0
    assert main._month_effect_short_exit_daily(d2.iloc[:5], p5) is None
    assert main._month_effect_short_exit_daily(d2.iloc[:6], p5) == ("short_swing_max_hold_timeout", 100.0)


def test_entry_writes_row_with_stop_and_mirrors_real(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda tag, check_switch=True: True)
    calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: calls.append(a))
    df = _frame15()
    idx = pd.DatetimeIndex(df.index)
    first = [i for i in range(1, len(idx)) if idx[i].month != idx[i - 1].month][0]
    sub = df.iloc[:first + 2]                       # first Sept bar + the fill bar
    with _conn() as conn:
        tag = main._month_effect_short_try_entry(conn, "ABC.NS", sub, 400000, 1.0, "2026-09-01", 1.0)
        assert tag == main._month_effect_short_cell_tag(6.0, 25)            # first (best PFnet) cell owns the symbol
        row = conn.execute("SELECT * FROM signal_state_swing_short WHERE symbol='ABC.NS'").fetchone()
        assert row["initial_stop_loss"] > row["entry_price"]                # protective BUY-stop above the short
        assert calls and calls[0][-1] == tag
        assert main._month_effect_short_try_entry(conn, "ABC.NS", sub, 400000, 1.0, "2026-09-01", 1.0) is None  # one row


def _conn():
    import sqlite3
    from contextlib import closing
    c = sqlite3.connect(main.DB_PATH)
    c.row_factory = sqlite3.Row
    return closing(c)


def test_pass_only_scans_15m_on_first_trading_day_of_september(monkeypatch):
    _fresh_db()
    fetched = []
    dfs = {"A.NS": pd.DataFrame({"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0], "Close": [1.0, 1.0],
                                 "Date": ["2026-08-31", "2026-09-01"]})}
    with _conn() as conn:
        main._run_month_effect_short_pass(conn, dfs, 400000, "2026-09-02", fetch15=lambda s: fetched.append(s))
        assert fetched == []                                              # not the first trading day
        main._run_month_effect_short_pass(conn, dfs, 400000, "2026-09-01", fetch15=lambda s: fetched.append(s))
        assert fetched == ["A.NS"]


def test_replay_driver_calls_real_main_functions():
    specs = R.cell_specs(main, "15m")
    assert set(specs) == set(main.MONTH_EFFECT_SHORT_CELLS)
    df = _frame15(260, start="2026-08-24 09:15")
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    tr = R.replay_symbol(main, df, next(iter(specs.values())), cost)
    assert len(tr) == 1 and tr[0]["reason"] in ("max_hold", "stop")
    assert abs(tr[0]["net"] - (tr[0]["gross"] - cost)) < 1e-12
    d1 = R.cell_specs(main, "1d")
    assert all("__1d__" in t for t in d1) and "month__effect__short__1d__atr6_h1__v1" in d1
    assert R.plan({"NSHARDS": "2", "INTERVALS": "1d,15m"})["include"][0] == {"interval": "1d", "shard": 0, "nshards": 2}
