"""sector_rotation fade SHORT 1d cells wired into the short-swing engine (paper live; real leg behind the fail-closed
overnight-product check B-912). Uses the real main.sector_rotation_fade_short_* functions."""
import os
import re
import tempfile
from contextlib import closing
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

import main
import strategy_registry as sr

WANT = ["atr1d5_h10_l5_n1", "atr1d5_h5_l5_n1", "atr4d0_h5_l5_n1", "atr6d0_h5_l5_n1", "atr6d0_h10_l5_n1", "atr2d5_h5_l5_n1",
        "atr1d5_h20_l5_n1", "atr2d5_h10_l5_n1", "atr4d0_h10_l5_n1", "atr2d5_h20_l5_n1", "atr4d0_h20_l5_n1", "atr6d0_h20_l5_n1",
        "atr6d0_h1_l5_n1", "atr4d0_h1_l5_n1", "atr2d5_h1_l5_n1", "atr1d5_h1_l5_n1"]


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _frame(close, open_=None, high=None, start="2024-01-01"):
    close = np.asarray(close, float)
    o = close.copy() if open_ is None else np.asarray(open_, float)
    h = np.maximum(close, o) + 0.3 if high is None else np.asarray(high, float)
    idx = pd.bdate_range(start, periods=len(close))
    df = pd.DataFrame({"Open": o, "High": h, "Low": np.minimum(close, o) - 0.3, "Close": close, "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def test_cells_tags_and_gate_mapping():
    assert [t.split("__")[4] for t in main.SECTOR_FADE_SHORT_CELLS] == WANT
    names = {s.name for s in sr.REGISTRY}
    for tag, (atr, hold) in main.SECTOR_FADE_SHORT_CELLS.items():
        assert re.match(r"^sector_rotation__fade__short__1d__atr\dd\d_h\d+_l5_n1__v1$", tag)
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
        assert tag in names                      # registered with real metrics
        assert tag not in main.REPLAY_OWED_TAGS
        assert hold >= 1                         # every cell is an overnight hold (entry at the close)
        assert main.sector_rotation_fade_short_stop(100.0, 2.0, atr) == 100.0 + atr * 2.0


def test_registry_cells_clear_floor_with_real_sample():
    for tag in main.SECTOR_FADE_SHORT_CELLS:
        s = next(x for x in sr.REGISTRY if x.name == tag)
        assert s.metrics.n_trades > 600 and s.is_viable() is True


def test_no_stop_no_entry():
    assert main.sector_rotation_fade_short_stop(100.0, 0.0, 1.5) is None
    assert main.sector_rotation_fade_short_stop(100.0, 2.0, 0) is None


def _pos(tag, entry_day, entry, stop):
    return {"strategy": tag, "entry_day": entry_day, "entry_price": entry, "initial_stop_loss": stop}


def test_exit_stop_gap_aware_and_hold_timeout():
    tag = main._sector_fade_short_cell_tag(1.5, 5)
    df = _frame([100.0] * 12, start="2024-01-01")
    day0 = df["Date"].iloc[2]
    assert main._sector_fade_short_exit(df.iloc[:7], _pos(tag, day0, 100.0, 110.0)) is None      # only 4 bars after
    r = main._sector_fade_short_exit(df.iloc[:8], _pos(tag, day0, 100.0, 110.0))                 # 5 bars after
    assert r == ("short_swing_max_hold_timeout", 100.0)
    o = [100.0] * 12
    o[4] = 115.0
    h = [100.3] * 12
    h[4] = 116.0
    g = _frame([100.0] * 12, open_=o, high=h)
    r = main._sector_fade_short_exit(g.iloc[:5], _pos(tag, day0, 100.0, 110.0))
    assert r == ("short_swing_stop_hit", 115.0)


def test_entry_writes_row_with_stop_and_blocks_other_open_positions(monkeypatch):
    _fresh_db()
    calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    rng = np.random.default_rng(1)
    df = _frame(100 + np.cumsum(rng.normal(0, 1, 60)))
    with closing(main.get_db()) as conn:
        tag = main._sector_fade_short_try_entry(conn, "ABC.NS", df, 100000.0, 1.0, "2024-03-01", 1.0)
        assert tag == next(iter(main.SECTOR_FADE_SHORT_CELLS))          # first viable cell wins
        row = conn.execute("SELECT * FROM signal_state_swing_short WHERE symbol='ABC.NS'").fetchone()
        assert row["initial_stop_loss"] > row["entry_price"] and row["qty"] > 0
        assert len(calls) == 1 and calls[0][5] == tag
        assert main._sector_fade_short_try_entry(conn, "ABC.NS", df, 100000.0, 1.0, "2024-03-01", 1.0) is None
        conn.execute("INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
                     "VALUES ('XYZ.NS','2024-03-01','long',100,95,110,5,1,1,'5m')")
        conn.commit()
        assert main._sector_fade_short_try_entry(conn, "XYZ.NS", df, 100000.0, 1.0, "2024-03-01", 1.0) is None


def test_entry_skipped_when_no_cell_viable(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: False)
    df = _frame(100 + np.arange(60) * 0.1)
    with closing(main.get_db()) as conn:
        assert main._sector_fade_short_try_entry(conn, "ABC.NS", df, 100000.0, 1.0, "2024-03-01", 1.0) is None
        assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 0


def test_real_leg_fails_closed_overnight(monkeypatch):
    _fresh_db()
    tag = next(iter(main.SECTOR_FADE_SHORT_CELLS))
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    ko = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "kotak_real_orders", ko)
    assert main.SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED is False
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, tag)
        st = conn.execute("SELECT status FROM real_trades ORDER BY id DESC LIMIT 1").fetchone()["status"]
    ko.place_real_short_entry.assert_not_called()
    assert st == "skipped_overnight_short_product_unconfirmed"


def test_pass_enters_only_the_sector_pick(monkeypatch):
    _fresh_db()
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: None)
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_exit", lambda *a, **k: None)
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    monkeypatch.setattr(main, "short_swing_entry_signal", lambda df: (None, None))
    monkeypatch.setattr(main, "sector_rotation_fade_short_picks", lambda dfs, L, N: ["AAA.NS"])
    rng = np.random.default_rng(2)
    dfs = {s: _frame(100 + np.cumsum(rng.normal(0, 1, 60))) for s in ("AAA.NS", "BBB.NS")}
    with closing(main.get_db()) as conn:
        main._run_short_swing_pass(conn, dfs, 100000.0, "2024-03-01", set())
        rows = [r["symbol"] for r in conn.execute("SELECT symbol FROM signal_state_swing_short")]
    assert rows == ["AAA.NS"]
