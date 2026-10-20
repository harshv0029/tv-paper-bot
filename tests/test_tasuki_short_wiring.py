"""tasuki gap SHORT 1d cells (ETF universe) wired into the short-swing engine (paper live; real leg behind the
fail-closed overnight-product check B-912; replay owed). Uses the real main.tasuki_short_* functions."""
import os
import tempfile
from contextlib import closing
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

import main
import strategy_registry as sr


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _bars(rows, start="2024-01-01"):
    """rows = (open, high, low, close)"""
    idx = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    df["Volume"] = 1000.0
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


# t-2 down bar (low 98), t-1 gaps below it (open 96 < 98) and closes down, t opens inside t-1's body, closes up
# above t-1's open but below t-2's low (97 < 98): bearish downside tasuki gap.
TASUKI = [(100.0, 101.0, 98.0, 99.0), (96.0, 96.5, 94.0, 94.5), (95.0, 97.5, 94.8, 97.0)]


def _series(pattern, n_prefix=30):
    base = [(100.0, 100.5, 99.5, 100.0)] * n_prefix
    return _bars(base + pattern)


def test_signal_matches_pattern_and_rejects_variants():
    assert main.tasuki_short_signal(_series(TASUKI)) is True
    bad = list(TASUKI)
    bad[2] = (95.0, 99.5, 94.8, 99.0)            # closes back above t-2's low: gap filled, not a tasuki
    assert main.tasuki_short_signal(_series(bad)) is False
    bad = list(TASUKI)
    bad[2] = (95.0, 96.0, 93.0, 93.5)            # last bar down, not up
    assert main.tasuki_short_signal(_series(bad)) is False
    assert main.tasuki_short_signal(_series(TASUKI).iloc[:2]) is False


def test_cells_tags_gate_mapping_and_registry():
    names = {s.name: s for s in sr.REGISTRY}
    for tag, mult in main.TASUKI_SHORT_CELLS.items():
        assert "__short__1d__" in tag and "atrnone" not in tag
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
        assert tag in names                                   # registered with real metrics
        assert tag in main.REPLAY_OWED_TAGS                   # no main.py-calling replay on file yet
        assert main.tasuki_short_stop(100.0, 2.0, mult) == 100.0 + mult * 2.0
    assert main.SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED is False


def test_replay_owed_closes_real_gate():
    tag = next(iter(main.TASUKI_SHORT_CELLS))
    assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is False


def test_no_stop_no_entry():
    assert main.tasuki_short_stop(100.0, None, 6.0) is None
    assert main.tasuki_short_stop(100.0, 0.0, 6.0) is None
    assert main.tasuki_short_stop(100.0, 2.0, 0) is None


def test_exit_stop_gap_aware_and_three_bar_timeout():
    flat = (100.0, 100.5, 99.5, 100.0)
    assert main.tasuki_short_exit_reason(_bars([flat] * 2), 110.0) is None
    assert main.tasuki_short_exit_reason(_bars([flat] * 3), 110.0) == ("max_hold_timeout", 100.0)
    gap = [flat, (115.0, 116.0, 114.0, 115.0), flat]
    assert main.tasuki_short_exit_reason(_bars(gap), 110.0) == ("stop_hit", 115.0)   # filled at the gap open
    wick = [flat, (100.0, 111.0, 99.5, 100.0), flat]
    assert main.tasuki_short_exit_reason(_bars(wick), 110.0) == ("stop_hit", 110.0)


def test_paper_exit_wrapper_uses_bars_after_signal_day():
    df = _series(TASUKI)
    sig_day = df["Date"].iloc[-1]
    flat = (97.0, 97.5, 96.5, 97.0)
    ext = pd.concat([df, _bars([flat] * 3, start=(pd.Timestamp(sig_day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))])
    pos = {"entry_day": sig_day, "initial_stop_loss": 120.0}
    assert main._tasuki_short_exit(ext.iloc[:-1], pos) is None
    assert main._tasuki_short_exit(ext, pos) == ("short_swing_max_hold_timeout", 97.0)


def test_entry_etf_only_stop_above_and_real_mirror_offered_with_tag(monkeypatch):
    _fresh_db()
    calls = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: calls.append(a))
    etf = sorted(main.ETF_SYMBOLS)[0] if main.ETF_SYMBOLS else "TESTETF.NS"
    monkeypatch.setattr(main, "ETF_SYMBOLS", frozenset({etf}))
    monkeypatch.setattr(main, "ETF_TRADING_ENABLED", True)
    df = _series(TASUKI)
    with closing(main.get_db()) as conn:
        assert main._tasuki_short_try_entry(conn, "RELIANCE.NS", df, 1_000_000.0, 1.0, "2024-03-01", 1.0) is None  # not an ETF
        tag = main._tasuki_short_try_entry(conn, etf, df, 1_000_000.0, 1.0, "2024-03-01", 1.0)
        assert tag == next(iter(main.TASUKI_SHORT_CELLS))          # none viable (replay owed) -> first cell, paper evidence
        row = conn.execute("SELECT * FROM signal_state_swing_short WHERE symbol=?", (etf,)).fetchone()
        assert row["initial_stop_loss"] > row["entry_price"] and row["qty"] > 0
        assert len(calls) == 1 and calls[0][5] == tag and calls[0][4] == row["initial_stop_loss"]
        assert main._tasuki_short_try_entry(conn, etf, df, 1_000_000.0, 1.0, "2024-03-01", 1.0) is None  # already open


def test_real_leg_fails_closed_overnight(monkeypatch):
    _fresh_db()
    tag = next(iter(main.TASUKI_SHORT_CELLS))
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    ko = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "kotak_real_orders", ko)
    with closing(main.get_db()) as conn:
        main._maybe_place_real_swing_short_entry(conn, "ABC.NS", 3, 100.0, 108.0, tag)
        st = conn.execute("SELECT status FROM real_trades ORDER BY id DESC LIMIT 1").fetchone()["status"]
    ko.place_real_short_entry.assert_not_called()
    assert st == "skipped_overnight_short_product_unconfirmed"


def test_pass_manages_tasuki_exit_and_entry(monkeypatch):
    _fresh_db()
    closed = []
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_entry", lambda *a, **k: None)
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_exit", lambda *a, **k: None)
    monkeypatch.setattr(main, "short_swing_entry_signal", lambda df: (None, None))
    monkeypatch.setattr(main, "sector_rotation_fade_short_picks", lambda dfs, L, N: [])
    etf = "TESTETF.NS"
    monkeypatch.setattr(main, "ETF_SYMBOLS", frozenset({etf}))
    monkeypatch.setattr(main, "ETF_TRADING_ENABLED", True)
    df = _series(TASUKI)
    with closing(main.get_db()) as conn:
        main._run_short_swing_pass(conn, {etf: df}, 1_000_000.0, "2024-03-01", set())
        assert conn.execute("SELECT strategy FROM signal_state_swing_short").fetchone()["strategy"] in main.TASUKI_SHORT_CELLS
        sig_day = df["Date"].iloc[-1]
        conn.execute("UPDATE signal_state_swing_short SET entry_day=?", (sig_day,))
        conn.commit()
        flat = (97.0, 97.5, 96.5, 97.0)
        ext = pd.concat([df, _bars([flat] * 3, start=(pd.Timestamp(sig_day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))])
        main._run_short_swing_pass(conn, {etf: ext}, 1_000_000.0, "2024-03-08", set())
        assert conn.execute("SELECT COUNT(*) FROM signal_state_swing_short").fetchone()[0] == 0
        r = conn.execute("SELECT exit_reason FROM short_trades_closed").fetchone()
        assert r["exit_reason"] == "short_swing_max_hold_timeout"
