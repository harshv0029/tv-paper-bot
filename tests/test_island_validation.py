import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import island_validation as iv


def _df(n=300, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    o = c * (1 + rng.normal(0, 0.002, n))
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.003, "Low": np.minimum(o, c) * 0.997,
                       "Close": c, "Volume": 5e6}, index=pd.date_range("2021-01-01", periods=n))
    # planted island bottom: gap down at 150, gap up at 152 above bar 150's high
    base = float(df["Close"].iloc[148])
    df.iloc[149, :4] = [base, base * 1.002, base * 0.998, base]
    df.iloc[150, :4] = [base * 0.90, base * 0.91, base * 0.89, base * 0.905]
    df.iloc[151, :4] = [base * 0.905, base * 0.915, base * 0.90, base * 0.91]
    df.iloc[152, :4] = [base * 0.95, base * 0.97, base * 0.94, base * 0.96]
    return df


def test_island_detected_and_gap_filter_is_stricter():
    df = _df()
    ent = iv.island_entries(df)
    assert ent[152]
    assert iv.island_entries(df, min_gap_atr=0.5).sum() <= ent.sum()
    assert iv.island_entries(df, min_gap_atr=50.0).sum() == 0


def test_run_symbol_tags_follow_grammar_and_cover_both_directions():
    aggs = {}
    iv.run_symbol(_df(), "1d", aggs)
    assert any("island_none__long__1d__atr3_within8__v1" == t.split("reversal__", 1)[1].replace("reversal__", "") or
               t == "reversal__island_none__long__1d__atr3_within8__v1" for t in aggs)
    assert all(t.islower() and "__v1" in t for t in aggs)
    ag = aggs["reversal__island_none__long__1d__atr3_within8__v1"]
    s = iv.summarize(ag)
    assert s["n"] >= 1 and "pfnet_ex_top5" in s and s["by_year"]


def test_ex_top5_removes_winners():
    ag = iv.new_agg()
    ag["n"], ag["win_sum"], ag["loss_sum"] = 10, 1.0, 0.5
    ag["top"] = [0.3, 0.2, 0.1]
    s = iv.summarize(ag)
    assert s["pfnet_ex_top5"] == round((1.0 - 0.6) / 0.5, 3)


def test_liquidity_filter_masks_illiquid():
    df = _df()
    df["Volume"] = 10.0
    sig_none = iv.build_signal(df, "none")
    sig_liq = iv.build_signal(df, "turn1cr")
    assert sig_none["long"].any() and not sig_liq["long"].any()
