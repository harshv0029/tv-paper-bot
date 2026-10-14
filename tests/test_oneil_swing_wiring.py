"""O'Neil 1w LONG cells in the live swing scan (run 38517583883): registry, gate, mapping, weekly resample, entry with stop, exit."""
import dataclasses
import inspect

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

TAGS = list(main.ONEIL_SWING_CELLS)


def _frame(close, vol=None, end="2026-10-12"):
    close = np.asarray(close, float)
    idx = pd.bdate_range(end=end, periods=len(close))
    v = np.full(len(close), 1000.0) if vol is None else np.asarray(vol, float)
    df = pd.DataFrame({"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close, "Volume": v}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _newhigh_frame(n=330):
    # rising closes; the whole previous week (5 sessions) carries 3x volume; last bar = Monday 2026-10-12 (first session)
    c = 100 + np.arange(n) * 0.1
    v = np.full(n, 1000.0)
    v[-6:-1] = 3000.0
    return _frame(c, v)


def test_registry_rows_and_mapping():
    names = {s.name: s for s in sr.REGISTRY}
    expect = {"oneil_flatbase__breakout__long__1w__atr3_avg1_chase10_h12_rsnone__v2": 3.477,
              "oneil_flatbase__breakout__long__1w__atr3_avg1_chase10_h26_rsnone__v2": 5.149,
              "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v2": 3.921,
              "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone_trl1__v2": 3.407,
              "oneil_flatbase__breakout__short__1w__atr3_chase10_h26_rsnone__v2": 1.399,
              "oneil_newhigh__first__long__1w__atr3_h26_rsnone__v2": 2.484,
              "oneil_pivot__breakout__long__1w__atr3_chase10_h26_rsnone__v2": 2.177}
    for t, pf in expect.items():
        m = names[t].metrics
        assert m.pfnet == pytest.approx(pf) and m.avg_held_bars and m.win_rate_pct > 0
    assert names["oneil_flatbase__breakout__short__1w__atr3_chase10_h26_rsnone__v2"].categories == (sr.TradeCategory.SHORT_SELL,)
    for t in TAGS:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t not in main.REPLAY_OWED_TAGS  # main.py replay JSON is the proof
    # never wired: avg-down controls, trl1, short
    for t in expect:
        if t not in TAGS:
            assert t not in main._STRATEGY_TAG_TO_REGISTRY_NAME


def test_gate_opens_only_if_viable():
    t = main.ONEIL_FLATBASE_TAG
    assert main._is_strategy_viable_for_real_money(t, check_switch=False) is True
    strat = next(s for s in sr.REGISTRY if s.name == t)
    orig = strat.metrics
    object.__setattr__(strat, "metrics", dataclasses.replace(orig, pfnet=1.05))
    try:
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is False
    finally:
        object.__setattr__(strat, "metrics", orig)


def test_weekly_resample_counts_sessions():
    w = main.oneil_weekly_from_daily(_newhigh_frame())
    assert int(w["nbars"].iloc[-1]) == 1 and int(w["nbars"].iloc[-2]) == 5


def test_newhigh_entry_carries_atr_stop():
    sig = main.oneil_swing_entry_signal(_newhigh_frame(), main.ONEIL_NEWHIGH_TAG)
    assert sig is not None
    assert 0 < sig["stop_loss"] < sig["entry_price"]
    assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 3.0 * sig["atr_at_entry"])


def test_no_entry_without_volume_or_late_in_week():
    df = _newhigh_frame()
    flat = df.copy()
    flat["Volume"] = 1000.0
    assert main.oneil_swing_entry_signal(flat, main.ONEIL_NEWHIGH_TAG) is None
    c = df["Close"].to_numpy()
    late = _frame(np.append(c, [c[-1] + 0.1, c[-1] + 0.2]), np.append(df["Volume"].to_numpy(), [1000.0, 1000.0]), end="2026-10-14")
    assert main.oneil_swing_entry_signal(late, main.ONEIL_NEWHIGH_TAG) is None  # 3rd session of the week: window passed
    assert main.oneil_swing_entry_signal(df, "nope") is None


def test_exit_stop_and_timeout():
    base = _frame(np.full(60, 100.0), end="2026-10-12")
    ed = base["Date"].iloc[-1]
    assert main.oneil_swing_exit_reason(base, ed, 90.0, 100.0)[0] is None
    nxt = _frame(np.full(61, 100.0), end="2026-10-13")
    lo = nxt["Low"].to_numpy().copy()
    lo[-1] = 85.0
    nxt["Low"] = lo
    assert main.oneil_swing_exit_reason(nxt, ed, 90.0, 100.0)[0] == "oneil_stop_hit"
    # entry week = bar 1: timeout on the Friday of week 26 (Mon 2026-10-12 + 25 weeks = Fri 2027-04-09)
    far = _frame(np.full(400, 100.0), end="2027-04-09")
    assert main.oneil_swing_exit_reason(far, "2026-10-12", 90.0, 100.0)[0] == "oneil_max_hold_timeout"
    early = far[far["Date"] <= "2027-04-02"]  # Friday of week 25 -> still held
    assert main.oneil_swing_exit_reason(early, "2026-10-12", 90.0, 100.0)[0] is None


def test_scan_wiring_last_with_real_mirror_and_exit_branch():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert src.index("_gapfade_try_entry(conn") < src.index("_oneil_swing_try_entry(conn")  # LAST of the chain
    assert 'pos["strategy"] in ONEIL_SWING_CELLS' in src
    ent = inspect.getsource(main._oneil_swing_try_entry)
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in ent
    assert "_is_strategy_viable_for_real_money(tag" in ent
    assert not any("ONEIL_TRADING_ENABLED" in n.upper() for n in dir(main))  # no new kill switch
