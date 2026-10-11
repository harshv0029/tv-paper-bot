"""Harness calls the REAL main._mcx_daily_flags and parses/simulates MCX cells (no network)."""
import importlib.util
import pathlib

import numpy as np
import pandas as pd

import main

R = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mcx_live_replay", R / "scripts" / "mcx_live_replay.py")
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)


def _df(n=200, seed=1):
    rng = np.random.default_rng(seed)
    c = np.abs(100 + np.cumsum(rng.normal(0, 1, n))) + 50
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1}, index=idx)


def test_parse_tag():
    assert h.parse_tag("sma_crossover__gc__long__1d__atrnone__v1") == ("sma_crossover", "GC=F", False, None)
    assert h.parse_tag("bollinger_mean_reversion__ng__short__1d__atr1d5__v1") == ("bollinger_mean_reversion", "NG=F", True, 1.5)
    assert h.parse_tag("sma_crossover__gc__long__5m__atrnone__v1") is None


def test_registry_cells_include_every_wired_cell():
    names = {s.name for s in h.registry_mcx_cells()}
    assert {c[0] for c in main._MCX_DAILY_CELLS} <= names and len(names) >= 49


def test_live_flags_call_real_main_function(monkeypatch):
    calls = []
    real = main._mcx_daily_flags

    def spy(d, s, p, short=False):
        calls.append(len(d))
        return real(d, s, p, short=short)

    monkeypatch.setattr(main, "_mcx_daily_flags", spy)
    df = _df(90)
    fresh, on = h.live_flags(df, "sma_crossover", {"fast": 9, "slow": 21}, False)
    assert calls and len(fresh) == len(df) == len(on)
    assert not fresh[:60].any()


def test_replay_cell_runs_all_directions_and_stop_labels():
    df = _df(300, 3)
    r0 = h.replay_cell("sma_crossover__gc__long__1d__atrnone__v1", df)
    r1 = h.replay_cell("sma_crossover__gc__long__1d__atr1d5__v1", df)
    r2 = h.replay_cell("sma_crossover__gc__short__1d__atrnone__v1", df)
    for r in (r0, r1, r2):
        assert {"pfnet", "win_pct", "n", "avg_held_days", "exits"} <= set(r)
    assert "atr_stop" not in r0["exits"]
