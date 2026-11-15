"""B-1605: pl1d LONG 4h bar-0 cells (run 43714020903, PFnet > 1.00) wired on the long swing engine's 4h leg."""
import numpy as np
import pandas as pd

import main
import strategy_registry as sr


def test_cells_pass_floor_registered_and_wired():
    rows = {t: pf for t, n, pf in main._replay_rows() if n >= 1}
    names = {x.name for x in sr.REGISTRY}
    assert len(main.PL1D_LONG_4H_CELLS) == 4
    for tag in main.PL1D_TFS_LONG_4H_TAGS:
        assert "__long__4h__" in tag and "_b0__" in tag and tag not in main.PL1D_CELLS
        assert rows[tag] > 1.0 and tag in names
        assert tag in main._replay_verified_tags() and tag not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_wired(tag) and tag in main.SWING_LONG_4H_TAGS
    pfs = [rows[t] for t in main.PL1D_TFS_LONG_4H_TAGS]
    assert pfs == sorted(pfs, reverse=True)
    for t, n, pf in main._replay_rows():
        if t.startswith(("starc__fade_full__short__4h", "gap__runaway__short__4h")) and t.endswith("_b0__v1"):
            assert pf <= 1.0 and t not in main.SWING_LONG_4H_TAGS


def test_signal_uses_real_rule_and_reprices_stop(monkeypatch):
    tag = main.PL1D_TFS_LONG_4H_TAGS[0]
    seen = {}

    def fake(df, t, cells=None):
        seen["cells"] = cells
        return {"entry_price": 100.0, "stop_loss": 88.0, "atr_at_entry": 2.0, "risk": 12.0, "direction": "long"}
    monkeypatch.setattr(main, "pl1d_long_entry_signal", fake)
    df4h = pd.DataFrame({"Date": [f"2026-11-{i:02d} 09:15" for i in range(1, 70)], "Close": np.ones(69)})
    sig = main._pl1d_long_4h_signal(df4h, tag, entry_price=101.0)
    assert seen["cells"] is main.PL1D_LONG_4H_CELLS
    assert sig["entry_price"] == 101.0 and sig["stop_loss"] == 101.0 - 6.0 * 2.0 and sig["tf"] == "4h"
    assert main._pl1d_long_4h_signal(df4h.iloc[:10], tag) is None


def test_exit_first_bar_is_next_4h_bar_and_stop():
    tag = main.PL1D_TFS_LONG_4H_TAGS[0]
    dates = ["2026-11-10 09:15", "2026-11-10 13:15", "2026-11-11 09:15", "2026-11-11 13:15"]
    df = pd.DataFrame({"Date": dates, "Open": [100, 100, 99, 97], "High": [101, 101, 100, 98],
                       "Low": [99, 95, 96, 90], "Close": [100, 99, 97, 91]})
    pos = {"strategy": tag, "entry_day": "2026-11-10 09:15", "initial_stop_loss": 94.0, "entry_price": 100.0}
    assert main._pl1d_long_4h_exit(df.iloc[:3], pos) is None  # same-day bar 1 counts (low 95 > 94), next day open
    assert main._pl1d_long_4h_exit(df, pos) == ("pl1d_stop_loss", 94.0)


def test_exit_timeout_after_hold_bars():
    tag = main.PL1D_TFS_LONG_4H_TAGS[0]
    n = 25
    df = pd.DataFrame({"Date": [f"x{i:03d}" for i in range(n)], "Open": [100.0] * n, "High": [101.0] * n,
                       "Low": [99.0] * n, "Close": [100.0 + i for i in range(n)]})
    pos = {"strategy": tag, "entry_day": "x000", "initial_stop_loss": 90.0, "entry_price": 100.0}
    assert main._pl1d_long_4h_exit(df, pos) == ("pl1d_max_hold_timeout", 120.0)


def test_bar1_signal_is_logged_not_entered(monkeypatch):
    tag = main.PL1D_TFS_LONG_4H_TAGS[0]
    df4h = pd.DataFrame({"Date": ["2026-11-13 13:15"] * 70})
    monkeypatch.setattr(main, "_island_4h_completed_bars", lambda *a, **k: df4h)
    monkeypatch.setattr(main, "_pl1d_long_4h_signal", lambda d, t, e=None: {"x": 1} if t == tag else None)
    logged = []
    monkeypatch.setattr(main, "_log_real_attempt", lambda *a, **k: logged.append(a[3]))
    now = pd.Timestamp("2026-11-13 15:40").to_pydatetime()
    assert main._pl1d_long_4h_try_entry(None, "ABC", None, 1e5, 1.0, now=now) is None
    assert logged == ["skipped_4h_signal_after_close"]
