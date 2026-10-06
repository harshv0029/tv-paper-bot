"""Tests for main.pnf_scan / pnf_entry_signal (Point & Figure, backlog B-12)."""
import numpy as np
import pandas as pd
import pytest

import main


def _frame(bars):
    """bars: list of (high, low, close) after 31 flat warm-up bars (box size = 1.0)."""
    rows = [(101.0, 100.0, 100.5)] * 31 + list(bars)
    h, l, c = (np.array(x, dtype=float) for x in zip(*rows))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1000.0})


# index base: bar 30 (c=100.5) seeds an X column at box 100
BARS_DOUBLE = [
    (105.2, 104.0, 105.0),  # X col rises to 105
    (104.9, 101.9, 102.0),  # 3-box reversal -> O col (top 104, bot 101)
    (101.5, 100.5, 100.8),  # O col extends to 100
    (103.1, 100.2, 103.0),  # 3-box reversal up -> X col (bot 101, top 103)
    (104.2, 103.0, 104.0),  # top 104, prior X top 105 not cleared
    (106.3, 104.0, 106.0),  # clears prior X top 105 -> double-top breakout
]


def _fires(df, variant, direction="long", params=None):
    r = main.pnf_scan(df, variant, direction, params)
    return np.flatnonzero(r["signal"]), r


def test_double_top_fires_once_on_breakout_bar_with_stop_under_last_o_column():
    df = _frame(BARS_DOUBLE)
    idx, r = _fires(df, "double_top")
    assert list(idx) == [len(df) - 1]
    i = idx[0]
    assert r["entry_price"][i] == pytest.approx(106.0)
    assert r["stop_loss"][i] == pytest.approx(100.0)  # bottom of the last O column
    assert r["target"][i] == pytest.approx(106.0 + 2.0 * 6.0)


def test_no_signal_before_prior_top_cleared():
    idx, _ = _fires(_frame(BARS_DOUBLE[:-1]), "double_top")
    assert len(idx) == 0


def test_pullback_fires_on_reversal_up_while_bullish():
    bars = BARS_DOUBLE + [
        (106.2, 102.9, 103.0),  # reversal down -> O col (bot 102)
        (105.3, 102.1, 105.0),  # 3-box reversal up while bullish
    ]
    df = _frame(bars)
    idx, r = _fires(df, "pullback")
    assert list(idx) == [len(df) - 1]
    assert r["stop_loss"][idx[0]] == pytest.approx(102.0)  # latest (closer) O column


def test_pullback_not_bullish_without_prior_buy_signal():
    # the reversal up at BARS_DOUBLE[3] happens before any breakout -> no pullback signal
    idx, _ = _fires(_frame(BARS_DOUBLE[:4]), "pullback")
    assert len(idx) == 0


def test_triple_top_needs_two_equal_prior_tops_then_clear():
    bars = [
        (105.2, 104.0, 105.0),  # X col top 105
        (104.9, 101.9, 102.0),  # -> O
        (104.2, 101.5, 104.0),  # 3-box reversal up -> X col
        (105.4, 103.0, 105.0),  # X col top 105 again (equal, not cleared)
        (104.9, 101.9, 102.0),  # -> O
        (104.2, 101.8, 104.0),  # -> X
        (106.3, 103.0, 106.0),  # clears both tops at 105
    ]
    df = _frame(bars)
    idx, _ = _fires(df, "triple_top")
    assert list(idx) == [len(df) - 1]
    # double-top variant also fires there (a simple breakout is part of every complex one)
    assert (len(df) - 1) in list(_fires(df, "double_top")[0])


def test_short_is_negated_mirror():
    df = _frame(BARS_DOUBLE)
    neg = df.copy()
    for col in ("Open", "Close"):
        neg[col] = -df[col]
    neg["High"], neg["Low"] = -df["Low"], -df["High"]
    r_short = main.pnf_scan(neg, "double_top", "short")
    r_long = main.pnf_scan(df, "double_top", "long")
    assert list(np.flatnonzero(r_short["signal"])) == list(np.flatnonzero(r_long["signal"]))
    i = np.flatnonzero(r_long["signal"])[0]
    assert r_short["entry_price"][i] == pytest.approx(-r_long["entry_price"][i])
    assert r_short["stop_loss"][i] == pytest.approx(-r_long["stop_loss"][i])


def test_entry_signal_last_row_shape_and_guards():
    assert main.pnf_entry_signal(_frame(BARS_DOUBLE[:1]), "double_top", "long") is None
    sig = main.pnf_entry_signal(_frame(BARS_DOUBLE), "double_top", "long")
    assert sig and sig["entry_price"] > sig["stop_loss"] and sig["target"] > sig["entry_price"]
    with pytest.raises(ValueError):
        main.pnf_scan(_frame(BARS_DOUBLE), "nope", "long")
    with pytest.raises(ValueError):
        main.pnf_scan(_frame(BARS_DOUBLE), "double_top", "sideways")


def test_signals_never_use_bars_after_signal_bar():
    df = _frame(BARS_DOUBLE + [(106.0, 90.0, 91.0)] * 5)
    idx_full, _ = _fires(df, "double_top")
    idx_cut, _ = _fires(df.iloc[: len(BARS_DOUBLE) + 31], "double_top")
    assert list(idx_cut) == [i for i in idx_full if i < len(BARS_DOUBLE) + 31]
