"""B-864: er.simulate bad-bar guard and top-trade / trimmed-PFnet reporting."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import elder_indicators_research as er  # noqa: E402


def _df(n=80, glitch_at=None, glitch_mult=800.0, bad_ohlc_at=None):
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.2
    l = np.minimum(o, c) - 0.2
    if glitch_at is not None:
        c[glitch_at] *= glitch_mult
        h[glitch_at] = c[glitch_at]
    if bad_ohlc_at is not None:
        h[bad_ohlc_at] = l[bad_ohlc_at] - 1.0
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1000.0}, index=idx)


def _sig(df, entry_bar):
    n = len(df)
    e = np.zeros(n, bool)
    e[entry_bar] = True
    nan = np.full(n, np.nan)
    return {"long": e, "short": np.zeros(n, bool), "long_lvl": nan, "short_lvl": nan,
            "exit_long": np.zeros(n, bool), "exit_short": np.zeros(n, bool)}


def _mask(df):
    return er.bad_bar_mask(df.Open.to_numpy(), df.Close.to_numpy(), df.High.to_numpy(), df.Low.to_numpy())


def test_mask_flags_800x_and_inconsistent_ohlc():
    m = _mask(_df(glitch_at=40, bad_ohlc_at=60))
    assert m[40] and m[60]
    assert not m[10] and not m[70]


def test_clean_data_unaffected():
    df = _df()
    assert not _mask(df).any()
    assert len(er.simulate(df, _sig(df, 30), "long", 2.0)) == 1


def test_trade_touching_glitch_bar_dropped():
    clean = _df()
    glit = _df(glitch_at=35)
    t_clean = er.simulate(clean, _sig(clean, 30), "long", 50.0)   # huge stop: rides into bar 35
    t_glit = er.simulate(glit, _sig(glit, 30), "long", 50.0)
    assert t_clean and not t_glit


def test_single_800x_bar_cannot_dominate_pfnet():
    glit = _df(glitch_at=35)
    agg = er.new_agg()
    for entry in range(5, 34, 3):
        er.add_trades(agg, er.simulate(glit, _sig(glit, entry), "long", 50.0))
    s = er.summarize(agg)
    assert s["max_trade_net_ret_pct"] is None or s["max_trade_net_ret_pct"] < 100.0


def test_trimmed_pfnet_and_top5_reporting():
    agg = er.new_agg()
    rets = [8.0, 0.05, 0.04, 0.03, 0.02, 0.01, -0.1, -0.1, -0.1]
    er.add_trades(agg, [{"ret": r, "hold": 3, "reason": "x", "s": i} for i, r in enumerate(rets)])
    s = er.summarize(agg)
    assert s["pfnet"] > 20 and s["pfnet_trim1"] < 1.0
    assert len(s["top5_trades"]) == 5 and s["top5_trades"][0]["net_ret_pct"] == 800.0
    assert s["max_trade_net_ret_pct"] == 800.0


def test_merge_keeps_global_top5_and_old_shards_without_top():
    a, b = er.new_agg(), er.new_agg()
    er.add_trades(a, [{"ret": r, "hold": 1, "reason": "x"} for r in (0.1, 0.2, 0.3)])
    er.add_trades(b, [{"ret": r, "hold": 1, "reason": "x"} for r in (0.4, 0.5, 0.6)])
    old = {k: v for k, v in b.items() if k != "best"}
    er.merge_aggs(a, b)
    assert [round(t[0], 1) for t in a["best"]] == [0.6, 0.5, 0.4, 0.3, 0.2]
    er.merge_aggs(a, old)
    assert len(a["best"]) == 5
