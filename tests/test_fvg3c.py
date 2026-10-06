"""Unit tests for main.fvg3c_scan / fvg3c_entry_signal / fvg3c_exit_reason
(backlog B-32). Hand-built bars; ATR period 2 so tiny frames have an ATR."""
import numpy as np
import pandas as pd
import pytest

import main

P = {"atr_period": 2}


def _df(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"]).assign(Volume=1000.0)


# bearish FVG: candle1 = idx1 (low 107), candle3 = idx3 (high 105) -> gap [105, 107]
BASE = [
    (110, 112, 108, 109),
    (109, 110, 107, 107.5),     # candle1
    (107.5, 108, 104, 104.5),   # candle2, range [104, 108]
]
INSIDE_C3 = (104.8, 105.0, 103.9, 104.2)   # body [104.2,104.8] inside c2, weak bearish
CONSOL = [(104.3, 104.8, 104.0, 104.5), (104.5, 104.9, 104.2, 104.6)]
RETEST_WICK = (104.8, 106.0, 104.6, 104.7)  # taps 105, bearish, long upper wick


def _valid_df():
    return _df(BASE + [INSIDE_C3] + CONSOL + [RETEST_WICK])


def test_valid_retest_short_signals_on_retest_bar():
    r = main.fvg3c_scan(_valid_df(), "valid_retest", "short", P)
    assert list(np.flatnonzero(r["signal"])) == [6]
    e, s, t = r["entry_price"][6], r["stop_loss"][6], r["target"][6]
    assert s > e > t
    assert e == pytest.approx(104.7)
    assert (s - e) * 2.0 == pytest.approx(e - t)  # rr = 2


def test_valid_retest_not_signalled_by_other_variants():
    df = _valid_df()
    # candle3 body is inside candle2 and weak: neither breakaway nor rejection
    assert not main.fvg3c_scan(df, "breakaway", "short", P)["signal"].any()
    assert not main.fvg3c_scan(df, "rejection", "short", P)["signal"].any()


def test_breakaway_enters_on_candle3_when_body_outside_candle2():
    c3 = (103.8, 104.5, 103.0, 103.2)  # body low 103.2 < c2.low 104
    r = main.fvg3c_scan(_df(BASE + [c3]), "breakaway", "short", P)
    assert list(np.flatnonzero(r["signal"])) == [3]
    assert r["stop_loss"][3] > r["entry_price"][3] > r["target"][3]
    assert not main.fvg3c_scan(_df(BASE + [c3]), "valid_retest", "short", P)["signal"].any()


def test_rejection_enters_on_strong_bearish_candle3():
    c3 = (104.9, 105.0, 103.2, 103.3)  # body 1.6 / range 1.8 = 0.89
    r = main.fvg3c_scan(_df(BASE + [c3]), "rejection", "short", P)
    assert list(np.flatnonzero(r["signal"])) == [3]


def test_valid_retest_requires_consolidation():
    # retest comes immediately after candle3 (0 consolidation bars < cons_bars=2)
    r = main.fvg3c_scan(_df(BASE + [INSIDE_C3, RETEST_WICK]), "valid_retest", "short", P)
    assert not r["signal"].any()


def test_gap_closed_through_top_invalidates():
    blow = (104.6, 108.5, 104.4, 108.0)  # closes above gap_hi (107)
    r = main.fvg3c_scan(_df(BASE + [INSIDE_C3] + CONSOL + [blow, RETEST_WICK]), "valid_retest", "short", P)
    assert not r["signal"].any()


def test_long_is_exact_price_mirror_of_short():
    K = 1000.0
    short_df = _valid_df()
    mirror = pd.DataFrame({
        "Open": K - short_df["Open"], "High": K - short_df["Low"],
        "Low": K - short_df["High"], "Close": K - short_df["Close"], "Volume": 1000.0,
    })
    rs = main.fvg3c_scan(short_df, "valid_retest", "short", P)
    rl = main.fvg3c_scan(mirror, "valid_retest", "long", P)
    assert list(np.flatnonzero(rl["signal"])) == list(np.flatnonzero(rs["signal"])) == [6]
    # long orientation: stop below entry below target
    assert rl["stop_loss"][6] < rl["entry_price"][6] < rl["target"][6]


def test_entry_signal_last_row_wrapper():
    df = _valid_df()
    sig = main.fvg3c_entry_signal(df, "valid_retest", "short", P)
    assert sig is not None and sig["stop_loss"] > sig["entry_price"] > sig["target"]
    assert main.fvg3c_entry_signal(df.iloc[:-1], "valid_retest", "short", P) is None
    assert main.fvg3c_entry_signal(df.iloc[:2], "valid_retest", "short", P) is None


def test_bad_variant_or_direction_raises():
    with pytest.raises(ValueError):
        main.fvg3c_scan(_valid_df(), "nope", "short")
    with pytest.raises(ValueError):
        main.fvg3c_scan(_valid_df(), "breakaway", "sideways")


def test_no_signal_on_flat_data():
    flat = _df([(100, 100.5, 99.5, 100)] * 30)
    for v in main.FVG3C_VARIANTS:
        for d in ("long", "short"):
            assert not main.fvg3c_scan(flat, v, d, P)["signal"].any()


def test_exit_reason_short_and_long():
    # short: stop above, target below
    assert main.fvg3c_exit_reason(106, 100, 103, "short", 105, 98, 1, 60) == ("stop_hit", 105)
    assert main.fvg3c_exit_reason(104, 97, 99, "short", 105, 98, 1, 60) == ("target_hit", 98)
    # both touched in one bar -> stop first (conservative)
    assert main.fvg3c_exit_reason(106, 97, 100, "short", 105, 98, 1, 60)[0] == "stop_hit"
    assert main.fvg3c_exit_reason(104, 100, 102, "short", 105, 98, 60, 60) == ("max_hold_timeout", 102)
    assert main.fvg3c_exit_reason(104, 100, 102, "short", 105, 98, 3, 60) == (None, None)
    # long: stop below, target above
    assert main.fvg3c_exit_reason(103, 99, 101, "long", 100, 106, 1, 60) == ("stop_hit", 100)
    assert main.fvg3c_exit_reason(107, 102, 105, "long", 100, 106, 1, 60) == ("target_hit", 106)


def test_sessions_block_fvg_spanning_a_session_break():
    df = _valid_df()
    # candle1 (idx1) in session 0, candle3 (idx3) in session 1 -> not an FVG
    sess = np.array([0, 0, 1, 1, 1, 1, 1, 1])
    assert not main.fvg3c_scan(df, "valid_retest", "short", P, sessions=sess)["signal"].any()
    # all one session -> unchanged
    ok = main.fvg3c_scan(df, "valid_retest", "short", P, sessions=np.zeros(8, dtype=int))
    assert list(np.flatnonzero(ok["signal"])) == [6]
    # retest in a later session than candle3 -> dropped
    sess2 = np.array([0, 0, 0, 0, 0, 0, 1, 1])
    assert not main.fvg3c_scan(df, "valid_retest", "short", P, sessions=sess2)["signal"].any()
