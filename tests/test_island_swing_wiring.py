"""B-877: island reversal LONG 1d atr1d5 live swing wiring (3 variants, own tags, SL always, no new kill switch)."""
import inspect
import sys

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

TAGS = main.ISLAND_SWING_TAGS


def _frame(o, h, l, c, v=1_000_000.0, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(c))
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": float(v)}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _island(n=60, base=100.0, volume=1_000_000.0):
    """Flat series, then gap down (bar n-4), consolidation, gap up above the gap-down bar's high (last bar)."""
    c = np.full(n, base)
    o, h, l = c.copy(), c + 1.0, c - 1.0
    i = n - 4
    for k, (lo, hi) in enumerate([(88.0, 90.0), (88.0, 90.5), (88.5, 91.0)]):
        o[i + k] = c[i + k] = (lo + hi) / 2
        l[i + k], h[i + k] = lo, hi
    j = n - 1
    l[j], h[j], o[j], c[j] = 92.0, 95.0, 92.5, 94.0   # Low 92 > High[j-1]=91 and > gap-down High 90
    return _frame(o, h, l, c, v=volume)


def test_tags_registry_mapping_and_gate():
    assert len(set(TAGS)) == 3
    for t in TAGS:
        assert "__long__1d__" in t and t.endswith("__v2")
        reg = main._STRATEGY_TAG_TO_REGISTRY_NAME[t]
        assert reg == t  # each variant maps to ITS OWN registry tag
        strat = next(s for s in sr.REGISTRY if s.name == reg)
        assert strat.metrics.pfnet >= sr.PFNET_LIVE_FLOOR
        oos = next(s for s in sr.REGISTRY if s.name == t.replace("__nonovl__v2", "__segoos__v2"))
        assert oos.metrics.pfnet >= sr.PFNET_LIVE_FLOOR  # held-out check also clears
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is (t not in main.REPLAY_OWED_TAGS)  # replay-verified tags re-open (2026-10-12)
    assert len({main._STRATEGY_TAG_TO_REGISTRY_NAME[t] for t in TAGS}) == 3


def test_signal_fires_on_island_with_real_atr_stop():
    df = _island()
    for t in TAGS:
        sig = main.island_swing_entry_signal(df, t)
        assert sig is not None, t
        assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 1.5 * sig["atr_at_entry"])
        assert 0 < sig["stop_loss"] < sig["entry_price"]


def test_no_signal_without_island():
    flat = _island()
    # no gap up on the last bar: close inside the range, Low not above the prior High
    flat.iloc[-1, flat.columns.get_loc("Low")] = 89.0
    for t in TAGS:
        assert main.island_swing_entry_signal(flat, t) is None
    # pure random-walk without gaps
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.2, 80))
    walk = _frame(c, c + 0.5, c - 0.5, c)
    for t in TAGS:
        assert main.island_swing_entry_signal(walk, t) is None


def test_gap_up_must_clear_gap_down_high():
    df = _island()
    # last-bar Low above prior High (91) but NOT above the gap-down bar's High if we raise that High
    df.iloc[-4, df.columns.get_loc("High")] = 92.5
    df.iloc[-4, df.columns.get_loc("Low")] = 90.0
    assert main.island_swing_entry_signal(df, main.ISLAND_NONE_TAG) is None


def test_only_first_reclaim_counts():
    df = _island(n=70)
    # a second island-like gap-up one bar later must not re-signal the same gap-down
    n = len(df)
    extra = df.iloc[[-1]].copy()
    extra.index = [df.index[-1] + pd.Timedelta(days=1)]
    extra["Date"] = extra.index[0].strftime("%Y-%m-%d")
    for k, v in (("Open", 96.5), ("High", 99.0), ("Low", 96.0), ("Close", 98.0)):
        extra[k] = v
    df2 = pd.concat([df, extra])
    assert main.island_swing_entry_signal(df2, main.ISLAND_NONE_TAG) is None


def test_filters_split_variants():
    thin = _island(volume=10.0)  # turnover ~1e3 << 1e7
    assert main.island_swing_entry_signal(thin, main.ISLAND_NONE_TAG) is not None
    assert main.island_swing_entry_signal(thin, main.ISLAND_PX20_TAG) is not None
    assert main.island_swing_entry_signal(thin, main.ISLAND_TURN1CR_TAG) is None
    cheap = _island()
    cheap[["Open", "High", "Low", "Close"]] = cheap[["Open", "High", "Low", "Close"]] / 10.0
    assert main.island_swing_entry_signal(cheap, main.ISLAND_PX20_TAG) is None
    assert main.island_swing_entry_signal(cheap, main.ISLAND_NONE_TAG) is not None


def _after(df_entry, extra_rows):
    last = df_entry.iloc[-1]
    rows = []
    d = df_entry.index[-1]
    for (o, h, l, c) in extra_rows:
        d = d + pd.offsets.BDay(1)
        rows.append(pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e6,
                                  "Date": d.strftime("%Y-%m-%d")}, index=[d]))
    return pd.concat([df_entry] + rows)


def test_exit_adapter_stop_rule_exit_and_timeout():
    df = _island()
    sig = main.island_swing_entry_signal(df, main.ISLAND_NONE_TAG)
    day, stop, atr, px = df["Date"].iloc[-1], sig["stop_loss"], sig["atr_at_entry"], sig["entry_price"]
    r, _ = main._island_swing_exit_adapter(df, day, stop, atr, px)
    assert r is None  # nothing after entry day yet
    up = _after(df, [(px + 0.1, px + 1.0, px - 0.5, px + 0.5)])
    assert main._island_swing_exit_adapter(up, day, stop, atr, px)[0] is None
    hit = _after(df, [(px, px + 0.5, stop - 1.0, stop - 0.5)])
    assert main._island_swing_exit_adapter(hit, day, stop, atr, px)[0] == "island_stop_loss"
    # 31 flat bars: the 30-bar max hold fires (fill bar is the first bar after entry day)
    flat = _after(df, [(px, px + 0.2, px - 0.2, px)] * 31)
    r, _ = main._island_swing_exit_adapter(flat, day, stop, atr, px)
    assert r in ("island_max_hold_timeout", "island_rule_exit")
    # falling EMA13 with close below it exits via the rule
    fall = _after(df, [(px, px + 0.1, px - 0.3, px - 0.2 * (k + 1)) for k in range(6)])
    assert main._island_swing_exit_adapter(fall, day, stop, atr, px)[0] == "island_rule_exit"


def test_scan_wiring_checked_last_sl_attached_reasoned_exit_no_new_switch():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert src.index("_island_swing_try_entry") > src.index('brk20_min_rr_entry_signal(df, "long"')
    assert "_island_swing_exit_adapter" in src
    assert "_maybe_place_real_swing_exit(conn, symbol, reason=" in src
    entry = inspect.getsource(main._island_swing_try_entry)
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in entry
    assert 'sig["stop_loss"]' in entry
    assert not any("island" in n.lower() for n in dir(main) if n.startswith("is_real_") or n.endswith("_TRADING_ENABLED"))


def test_gap05_tags_can_fire_b887():
    """B-887: island_filters_passed has no 'gap05' key; gap05 must use the 'none' liquidity gate so it can ever fire."""
    import inspect
    src = inspect.getsource(main.island_swing_entry_signal)
    assert '"none" if flt == "gap05"' in src
    import numpy as np
    import pandas as pd
    n = 80
    c = np.full(n, 100.0); h = c + 1.0; l = c - 1.0
    # gap-down at i=40 (high < prior low by > 0.5 ATR), reclaim at j=41 (low > prior high and > h[i])
    h[40], l[40], c[40] = 90.0, 88.0, 89.0
    h[41], l[41], c[41] = 101.0, 99.5, 100.5
    h[39], l[39] = 101.0, 99.0
    df = pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": np.full(n, 1e7)})
    df.index = pd.date_range("2024-01-01", periods=n, freq="B")
    sub = df.iloc[:42]
    tag = main.ISLAND_GAP05_TAGS[0]
    assert main.island_bottom_signal_on_last_bar(sub, min_gap_atr=main.ISLAND_GAP05_MIN_ATR)
    assert main.island_swing_entry_signal(sub, tag) is not None
