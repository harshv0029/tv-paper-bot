"""Island reversal SHORT mirror (1d atr1d5): ported, NOT wired. Mirror of tests/test_island_swing_wiring.py."""
import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

TAGS = main.ISLAND_SHORT_TAGS


def _frame(o, h, l, c, v=1_000_000.0, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(c))
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": float(v)}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _island_top(n=60, base=100.0, volume=1_000_000.0):
    """Flat, then gap UP (bar n-4), consolidation, gap DOWN below the gap-up bar's low (last bar)."""
    c = np.full(n, base)
    o, h, l = c.copy(), c + 1.0, c - 1.0
    i = n - 4
    for k, (lo, hi) in enumerate([(110.0, 112.0), (109.5, 112.0), (109.0, 111.5)]):
        o[i + k] = c[i + k] = (lo + hi) / 2
        l[i + k], h[i + k] = lo, hi
    j = n - 1
    l[j], h[j], o[j], c[j] = 104.0, 108.0, 107.5, 105.0  # High 108 < Low[j-1]=109 and < gap-up Low 110
    return _frame(o, h, l, c, v=volume)


def test_tags_follow_grammar_and_are_registered_research_only():
    assert len(set(TAGS)) == 4
    for t in TAGS:
        assert "__short__1d__" in t and t.endswith("__v2")
        strat = next(s for s in sr.REGISTRY if s.name == t)
        assert strat.metrics.pfnet < sr.PFNET_LIVE_FLOOR  # real metrics: fails the floor
        # not wired: no live tag mapping, so the real-money gate stays closed
        assert t not in main._STRATEGY_TAG_TO_REGISTRY_NAME
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is False


def test_not_in_live_entry_chain():
    assert not set(TAGS) & set(main.ISLAND_ALL_TAGS)


def test_signal_fires_with_stop_above_entry():
    df = _island_top()
    for t in TAGS[:3]:
        sig = main.island_short_entry_signal(df, t)
        assert sig is not None, t
        assert sig["direction"] == "short"
        assert sig["stop_loss"] == pytest.approx(sig["entry_price"] + 1.5 * sig["atr_at_entry"])
        assert sig["stop_loss"] > sig["entry_price"]


def test_long_island_is_not_a_short_signal_and_vice_versa():
    long_df = pd.DataFrame({"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 1}, index=range(1))
    short_df = _island_top()
    assert not main.island_bottom_signal_on_last_bar(short_df)
    # flip the top into a bottom by reciprocal prices -> long detector fires, short does not
    m = short_df.copy()
    m["High"], m["Low"] = 1 / short_df["Low"], 1 / short_df["High"]
    m["Open"], m["Close"] = 1 / short_df["Open"], 1 / short_df["Close"]
    assert main.island_bottom_signal_on_last_bar(m)
    assert not main.island_top_signal_on_last_bar(m)
    assert main.island_top_signal_on_last_bar(short_df)
    assert long_df is not None


def test_no_signal_without_gap_down_reclaim():
    df = _island_top()
    df.iloc[-1, df.columns.get_loc("High")] = 111.0  # no gap down vs prior low 109
    assert main.island_short_entry_signal(df, TAGS[0]) is None


def test_filters():
    cheap = _island_top(base=100.0)
    for c in ("Open", "High", "Low", "Close"):
        cheap[c] = cheap[c] * 0.1  # prices ~10 -> fails px20
    assert main.island_short_entry_signal(cheap, main.ISLAND_SHORT_PX20_TAG) is None
    assert main.island_short_entry_signal(cheap, main.ISLAND_SHORT_NONE_TAG) is not None
    thin = _island_top(volume=1.0)
    assert main.island_short_entry_signal(thin, main.ISLAND_SHORT_TURN1CR_TAG) is None
    assert main.island_short_entry_signal(thin, main.ISLAND_SHORT_NONE_TAG) is not None
    assert main.island_short_entry_signal(_island_top(), "bogus") is None


def test_gap05_requires_half_atr_gaps():
    # tiny gaps vs a wide-range history fail the 0.5 ATR rule, large ones pass
    assert main.island_short_entry_signal(_island_top(), main.ISLAND_SHORT_GAP05_TAG) is not None
    df = _island_top()
    df["High"] = df["High"] + 0.0
    wide = df.copy()
    wide.loc[wide.index[:-5], "High"] += 30.0
    wide.loc[wide.index[:-5], "Low"] -= 30.0
    assert main.island_short_entry_signal(wide, main.ISLAND_SHORT_GAP05_TAG) is None


def _exit_df(entry_px, atr, bars):
    n = 20
    c = np.full(n, entry_px)
    o, h, l = c.copy(), c + 0.2, c - 0.2
    df = _frame(o, h, l, c)
    last = df.index[-1]
    rows = []
    for k, (o_, h_, l_, c_) in enumerate(bars, 1):
        rows.append((last + pd.tseries.offsets.BDay(k), o_, h_, l_, c_))
    add = pd.DataFrame({"Open": [r[1] for r in rows], "High": [r[2] for r in rows], "Low": [r[3] for r in rows],
                        "Close": [r[4] for r in rows], "Volume": 1e6}, index=[r[0] for r in rows])
    add["Date"] = [d.strftime("%Y-%m-%d") for d in add.index]
    return pd.concat([df, add]), df.index[-1].strftime("%Y-%m-%d")


def test_exit_stop_above_triggers_gap_aware():
    stop = 100.0 + 1.5 * 2.0
    df, entry_day = _exit_df(100.0, 2.0, [(100.0, 100.5, 99.5, 100.0), (104.0, 105.0, 103.5, 104.5)])
    reason, rm = main._island_short_exit_adapter(df, entry_day, stop, 2.0, 100.0)
    assert reason == "island_short_stop_loss"
    assert rm <= 100.0


def test_exit_none_when_price_falls_and_max_hold():
    stop = 103.0
    bars = [(100 - k * 0.1, 100 - k * 0.1 + 0.05, 100 - k * 0.1 - 0.05, 100 - k * 0.1 - 0.02) for k in range(1, 4)]
    df, entry_day = _exit_df(100.0, 2.0, bars)
    reason, rm = main._island_short_exit_adapter(df, entry_day, stop, 2.0, 100.0)
    assert reason is None
    assert rm == pytest.approx(float(df["Close"].iloc[-1]))
    # max hold: 31 quiet bars after fill -> timeout
    bars = [(100.0, 100.05, 99.95, 100.0)] * 33
    df, entry_day = _exit_df(100.0, 2.0, bars)
    reason, _ = main._island_short_exit_adapter(df, entry_day, stop, 2.0, 100.0)
    assert reason in ("island_short_max_hold_timeout", "island_short_rule_exit")


def test_exit_zero_atr_safe():
    df, entry_day = _exit_df(100.0, 2.0, [(100.0, 100.5, 99.5, 100.0)])
    assert main._island_short_exit_adapter(df, entry_day, 103.0, 0.0, 100.0)[0] is None
