"""B-1471: Minervini lab cells wired on POOLED PFnet (user 2026-11-05), one cell per entry signal, per-cell variant."""
import numpy as np
import pandas as pd
import pytest

import main

CELLS = main.MINERVINI_LAB_LIVE_CELLS
UNF = "minervini_vcp__ma50_trail_srcmain__long__1d__h60__v1"


def _frame(n=300):
    rng = np.random.default_rng(2)
    c = 100 * np.exp(rng.normal(0.001, 0.01, n).cumsum())
    idx = pd.bdate_range(end="2026-10-30", periods=n)
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": np.full(n, 1e5)}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def test_one_cell_per_entry_signal_and_exclusions():
    keys = [(f, w) for f, w, _ in CELLS.values()]
    assert len(keys) == len(set(keys))
    for t, (f, _w, _h) in CELLS.items():
        assert "stopout_cluster" not in t and "rs_blend" not in t and "breadth_nhnl" not in t and "regime_" not in t
        assert f is None or f in main.MINERVINI_LAB_FEATURE_NAMES
    assert list(CELLS)[-1] == UNF and CELLS[UNF] == (None, None, 60)


def test_cell_variant_parsing_and_stop_desc():
    assert main._minervini_lab_cell_variant(UNF) == "ma50_trail"
    assert all(main._minervini_lab_cell_variant(t) == "pct8_hard" for t in list(CELLS)[:-1])
    assert "MA50" in main._SWING_SL_RULES[UNF] and "8% hard stop" in main._SWING_SL_RULES[list(CELLS)[0]]


def test_unfiltered_cell_uses_structural_stop(monkeypatch):
    df = _frame()
    px = float(df["Close"].iloc[-1])
    monkeypatch.setattr(main, "minervini_vcp_entry_signal",
                        lambda d, rs_percentile=None: {"stop_loss": px * 0.95, "atr_at_entry": 2.0})
    sig = main.minervini_lab_live_entry_signal(df, UNF)
    assert sig["stop_loss"] == pytest.approx(px * 0.95) and sig["stop_loss"] < sig["entry_price"]


def test_index_features_fail_closed_without_index(monkeypatch):
    df = _frame()
    px = float(df["Close"].iloc[-1])
    monkeypatch.setattr(main, "minervini_vcp_entry_signal",
                        lambda d, rs_percentile=None: {"stop_loss": px * 0.95, "atr_at_entry": 2.0})
    monkeypatch.setitem(main._ONEIL_DAILY_IDX, "close", None)
    for t, (f, _w, _h) in CELLS.items():
        if f in main.MINERVINI_LAB_INDEX_FEATURES:
            assert main.minervini_lab_live_entry_signal(df, t) is None, t


def test_ma50_exit_adapter(monkeypatch):
    df = _frame()
    df.loc[df.index[-1], ["Open", "High", "Low", "Close"]] = [50.0, 50.0, 49.9, 50.0]  # close far below MA50, above stop
    entry_day = df["Date"].iloc[-3]
    why, _ = main._minervini_lab_live_exit_adapter(df, entry_day, 10.0, 2.0, 0.0, UNF)
    assert why == "minervini_lab_ma50_break"
