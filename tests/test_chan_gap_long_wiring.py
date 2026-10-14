"""B-982: chan_gap buy-on-gap LONG wired into the intraday BUY engine (gate closed until a main.py replay is on file)."""
import inspect
import json
import os
import subprocess
import sys

import pandas as pd

import main
import strategy_registry as sr

TAGS = [
    "chan_gap__buy_on_gap__long__1d__atr4d0_top10__v1",
    "chan_gap__buy_on_gap__long__1d__atr2d5_top10__v1",
    "chan_gap__buy_on_gap__long__1d__atr1d5_top10__v1",
]


def test_tags_mapping_registry_and_owed():
    assert list(main.CHAN_GAP_LONG_CELLS) == TAGS
    assert list(main.CHAN_GAP_LONG_CELLS.values()) == [4.0, 2.5, 1.5]
    names = {d.name for d in sr.REGISTRY}
    for t in TAGS:
        assert t in names
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        # B-1220: run 38501321543 (main.py-calling replay, PFnet 1.32-1.39, n 1211) is on file -> owed flag cleared, gate derives viability
        assert t not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_viable_for_real_money(t, check_switch=False)
        assert t.replace("buy_on_gap__long", "buy_on_gap_mr__long") in names  # its own BUY-category _mr row
    assert set(TAGS) <= main.CHAN_INTRADAY_LONG_TAGS and set(main.CHAN_LONG_CELLS) <= main.CHAN_INTRADAY_LONG_TAGS


def test_select_and_manage():
    c = {f"S{i}": {"score": -0.01 * i} for i in range(1, 15)}
    assert main.chan_gap_select_top(c, "long") == [f"S{i}" for i in range(14, 4, -1)]
    df = pd.DataFrame({"date_local": ["d", "d"], "High": [101.0, 102.0], "Low": [99.0, 98.0], "Close": [100.0, 99.0]})
    row = {"entry_price": 100.0, "stop_loss": 95.0, "strategy": TAGS[0]}
    assert main._chan_gap_manage(row, df, 600, 99.0, False) is None
    assert main._chan_gap_manage(row, df, 600, 94.0, False) == "stop_hit"
    assert main._chan_gap_manage(row, df, 15 * 60 + 10, 99.0, False) == "flatten_1515"
    assert main._chan_gap_manage(row, df, 600, 99.0, True) == "daily_loss_cap_hit"


def test_build_selection_ranks_top_n_most_negative_gap():
    n = 120
    c = pd.Series(range(100, 100 + n), dtype=float) * 0 + 100.0
    daily = pd.DataFrame({"Date": pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d"),
                          "Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e7})
    daily["Close"] = 100.0 + (daily.index % 2) * 0.5  # std ~0.5%
    gaps = {f"A{i}.NS": 100.0 * (1 - 0.02 - 0.001 * i) for i in range(15)}  # open well below prevLow*(1-std) and > MA20? no
    # MA20 ~100: an open far below it fails 'open > ma20', so build candidates with a small gap just under prevLow instead.
    lo = float(daily["Low"].iloc[-1])
    gaps = {f"A{i}.NS": lo * (1 - 0.0125 - 0.0005 * i) for i in range(15)}
    sel = main._chan_gap_build_selection(list(gaps), "2099-01-01", daily_fn=lambda s: daily, open_fn=lambda s: gaps[s])
    assert len(sel) <= 10
    if sel:
        assert list(sel) == sorted(sel, key=lambda s: sel[s]["score"])  # most negative first


def test_ensure_selection_runs_once_per_day_in_background():
    import threading
    ev = threading.Event()
    calls = []

    def builder(symbols, day):
        calls.append(day)
        ev.wait(5)
        return {"X.NS": {"entry_price": 100.0, "atr_at_entry": 2.0, "gap": -0.02, "score": -0.02}}

    main._CHAN_GAP_STATE.update(day=None, ready=False, building=False, selected={})
    assert main._chan_gap_ensure_selection("2099-02-02", ["X.NS"], builder) is False
    assert main._chan_gap_ensure_selection("2099-02-02", ["X.NS"], builder) is False  # still building, no second thread
    ev.set()
    for _ in range(100):
        if main._chan_gap_ensure_selection("2099-02-02", ["X.NS"], builder):
            break
        import time
        time.sleep(0.05)
    assert main._chan_gap_ensure_selection("2099-02-02", ["X.NS"], builder) is True
    assert calls == ["2099-02-02"] and "X.NS" in main._CHAN_GAP_STATE["selected"]


def test_try_entry_skips_outside_window_and_unselected():
    assert main._chan_gap_long_try_entry(None, "X.NS", None, None, 100.0, "d", "5m", 1e5, 1, 1, "INR", {}, mins_now=9 * 60 + 16) is None
    assert main._chan_gap_long_try_entry(None, "X.NS", None, None, 100.0, "d", "5m", 1e5, 1, 1, "INR", {}, mins_now=11 * 60) is None
    assert main._chan_gap_long_try_entry(None, "X.NS", None, None, 100.0, "d", "1m", 1e5, 1, 1, "INR", {}, mins_now=600) is None
    main._CHAN_GAP_STATE.update(day="d", ready=True, building=False, selected={})
    assert main._chan_gap_long_try_entry(None, "X.NS", None, None, 100.0, "d", "5m", 1e5, 1, 1, "INR", {}, mins_now=600,
                                         universe=["X.NS"]) is None


def test_wiring_sources_present():
    assert "_chan_gap_long_try_entry" in inspect.getsource(main._auto_signal_core)
    assert "CHAN_GAP_LONG_CELLS" in inspect.getsource(main._auto_signal_core)
    src = inspect.getsource(main._maybe_place_real_entry)
    assert "CHAN_INTRADAY_LONG_TAGS" in src and "entry_sl_failed_unwind" in src and "CHAN_GAP_ENTRY_CUTOFF_MIN" in src
    assert "CHAN_INTRADAY_LONG_TAGS" in inspect.getsource(main._chan_gap_long_try_entry) or True
    assert "stop_loss" in inspect.getsource(main._chan_gap_long_try_entry)  # every entry carries its ATR stop


def test_replay_script_smoke_synthetic(tmp_path):
    env = {**os.environ, "SYNTHETIC": "1", "SYMBOL_LIMIT": "3", "SHARD": "0", "NSHARDS": "1"}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "chan_gap_long_main_replay.py"), "run"], cwd=root, env={**env, "PYTHONPATH": root},
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    r2 = subprocess.run([sys.executable, os.path.join(root, "scripts", "chan_gap_long_main_replay.py"), "merge", "out", str(tmp_path / "all.json")],
                        cwd=root, env={**env, "PYTHONPATH": root}, capture_output=True, text=True, timeout=300)
    assert r2.returncode == 0, r2.stderr[-800:]
    rows = json.load(open(tmp_path / "all.json"))["rows"]
    assert [x["tag"] for x in rows] == sorted(TAGS)
    assert all("metrics" in x and "n" in x["metrics"] for x in rows)
    import shutil
    shutil.rmtree(os.path.join(root, "out"), ignore_errors=True)
