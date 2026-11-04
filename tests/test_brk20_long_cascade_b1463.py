"""B-1463 part 2: the other viable brk20_min_rr LONG 1d cells of main.py replay run 38185670883, wired as a cascade
(mirror of BRK20_SHORT_SWING_CELLS). Each tag mapped 1:1, viable, gated by its own registry row, stop on every signal."""
import inspect

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

NEW_TAGS = (
    "brk20_min_rr__main_replay__long__1d__atr4_rr3d5__v1",
    "brk20_min_rr__main_replay__long__1d__atr4_rr3__v1",
    "brk20_min_rr__main_replay__long__1d__atr3_rr4__v1",
    "brk20_min_rr__main_replay__long__1d__atr3_rr3d5__v1",
    "brk20_min_rr__main_replay__long__1d__atr3_rr3__v1",
)
REG = {s.name: s for s in sr.REGISTRY}


def _frame(close, high):
    close = np.asarray(close, float)
    idx = pd.bdate_range("2024-01-01", periods=len(close))
    df = pd.DataFrame({"Open": close, "High": np.asarray(high, float), "Low": close - 0.3, "Close": close,
                       "Volume": 1000.0}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _breakout(peak=140.0, n=100):
    c = np.full(n, 100.0)
    c[-1] = 101.0
    h = c + 0.3
    h[40] = peak
    return _frame(c, h)


def test_cascade_table_order_and_params():
    assert main.BRK20_LONG_SWING_CELLS[0] == (main.BRK20_SWING_TAG, 4.0, 4.0)
    assert main.BRK20_LONG_SWING_TAGS[1:] == NEW_TAGS
    for t, a, r in main.BRK20_LONG_SWING_CELLS:
        assert f"__atr{a:g}_rr{r:g}__".replace(".", "d") in t


@pytest.mark.parametrize("tag", NEW_TAGS)
def test_new_tag_mapped_viable_and_main_replay_evidenced(tag):
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
    s = REG[tag]
    assert s.is_viable() is True and s.metrics.pfnet > sr.PFNET_LIVE_FLOOR and s.metrics.n_trades >= 30
    assert "38185670883" in s.metrics.run_ref
    assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is True
    # exit / hold / dashboard plumbing knows the cell
    assert main._strategy_hold_spec(tag) == (main.BRK20_MAX_HOLD_BARS, "1d")
    assert tag in main._SWING_SL_RULES


@pytest.mark.parametrize("tag,atr_mult,min_rr", main.BRK20_LONG_SWING_CELLS)
def test_each_cell_signal_carries_stop(tag, atr_mult, min_rr):
    sig = main.brk20_min_rr_entry_signal(_breakout(), "long", atr_mult, min_rr)
    assert sig is not None
    assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - atr_mult * sig["atr_at_entry"])
    assert 0 < sig["stop_loss"] < sig["entry_price"]


def test_cascade_falls_back_to_looser_rr_cell():
    base = main.brk20_min_rr_entry_signal(_breakout(), "long", 4.0, 0.0)
    risk4 = 4.0 * base["atr_at_entry"]
    # room = 3.75 x the atr4 risk: atr4_rr4 is silent, atr4_rr3d5 fires
    tag, sig = main.brk20_long_swing_entry_signal(_breakout(peak=base["entry_price"] + 3.75 * risk4))
    assert tag == "brk20_min_rr__main_replay__long__1d__atr4_rr3d5__v1"
    assert 0 < sig["stop_loss"] < sig["entry_price"]
    tag, _ = main.brk20_long_swing_entry_signal(_breakout())
    assert tag == main.BRK20_SWING_TAG  # original cell keeps priority
    assert main.brk20_long_swing_entry_signal(_breakout(peak=100.3)) == (None, None)  # no room -> no entry


def test_exit_adapter_uses_cell_atr_mult():
    n = 100
    c = np.full(n + 31, 100.0)
    df = _frame(c, c + 0.3)
    entry_day = df["Date"].iloc[n - 1]
    # atr3 cell: stop 97 with atr 1 -> entry recovered as 100; a low of 96.5 on the fill bar is a stop hit
    lo = df["Low"].to_numpy().copy()
    lo[n] = 96.5
    hit = df.assign(Low=lo)
    r, _ = main._brk20_swing_exit_adapter(hit.iloc[:n + 1], entry_day, 97.0, 1.0, 100.0, tag=NEW_TAGS[2])
    assert r == "stop_loss"
    r, _ = main._brk20_swing_exit_adapter(df, entry_day, 97.0, 1.0, 100.0, tag=NEW_TAGS[2])
    assert r == "max_hold_timeout"


def test_scan_and_exit_dispatch_use_cascade():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert "brk20_long_swing_entry_signal(df)" in src
    assert 'pos["strategy"] in BRK20_LONG_SWING_ATR_OF_TAG' in src
    assert "tag=pos[\"strategy\"]" in src
