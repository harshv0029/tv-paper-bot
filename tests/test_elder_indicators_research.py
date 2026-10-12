import ast
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import elder_indicators_research as er  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "elder_indicators_research.py")


def synth(n=500, seed=1, drift=0.0005):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    v = rng.integers(1000, 5000, n).astype(float)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


def test_script_parses():
    ast.parse(open(SCRIPT).read())


def test_tag_grammar():
    t = er.make_tag("ema13", "ema_dip", "long", "1d", {"n": 13, "atr": 1.5})
    assert t == "ema13__ema_dip__long__1d__atr1d5_n13__v1"
    assert er.make_tag("roc", "roc_centerline", "short", "1d", {"n": 7, "atr": 2.0}).endswith("atr2_n7__v1")


def test_all_families_tags_unique_and_lowercase():
    seen = set()
    for fam in er.FAMILIES:
        for variant, params, _, _ in er.variant_specs(fam):
            for d in ("long", "short"):
                for am in er.ATR_MULTS:
                    t = er.make_tag(fam, variant, d, "1d", {**params, "atr": am})
                    assert t == t.lower() and t not in seen
                    seen.add(t)


@pytest.mark.parametrize("fam", er.FAMILIES)
def test_family_runs_both_directions(fam):
    df = synth()
    aggs = {}
    er.run_symbol(df, fam, "1d", aggs)
    for variant, params, fn, _ in er.variant_specs(fam):
        sig = fn(df)
        for k in ("long", "short", "exit_long", "exit_short", "long_lvl", "short_lvl"):
            assert len(sig[k]) == len(df)
    assert any("__long__" in t for t in aggs) or any("__short__" in t for t in aggs)
    for ag in aggs.values():
        assert ag["n"] > 0


def test_stop_loss_on_every_trade_and_gap_fill():
    df = synth(60)
    n = len(df)
    sig = er._pack(df, np.r_[True, np.zeros(n - 1, bool)], np.zeros(n, bool),
                   np.zeros(n, bool), np.zeros(n, bool))
    # force a gap-down on bar 3 below any 1.5 ATR stop (0.6x: a >50% one-bar move is dropped by the B-864 bad-bar guard)
    df = df.copy()
    df.iloc[3, df.columns.get_loc("Open")] = df["Close"].iloc[0] * 0.6
    df.iloc[3, df.columns.get_loc("Low")] = df["Close"].iloc[0] * 0.6
    tr = er.simulate(df, sig, "long", 1.5)
    assert tr and tr[0]["reason"] == "stop_loss"
    assert tr[0]["ret"] < -0.3          # filled at the gap open, not at the stop


def test_cost_applied_and_short_sign():
    n = 40
    idx = pd.bdate_range("2023-01-02", periods=n)
    px = np.linspace(100, 60, n)          # steady fall
    df = pd.DataFrame({"Open": px, "High": px * 1.001, "Low": px * 0.999, "Close": px,
                       "Volume": 1.0}, index=idx)
    sig = er._pack(df, np.zeros(n, bool), np.r_[True, np.zeros(n - 1, bool)],
                   np.zeros(n, bool), np.zeros(n, bool))
    tr = er.simulate(df, sig, "short", 3.0, max_hold=10)
    assert tr[0]["reason"] == "max_hold_timeout"
    gross = (px[1] - px[11]) / px[1]
    assert tr[0]["ret"] == pytest.approx(gross - er.COST_ROUND_TRIP, rel=1e-6)


def test_aggregation_merge_and_summary():
    a, b = er.new_agg(), er.new_agg()
    er.add_trades(a, [{"ret": 0.05, "hold": 4, "reason": "rule_exit"},
                      {"ret": -0.02, "hold": 2, "reason": "stop_loss"}])
    er.add_trades(b, [{"ret": 0.03, "hold": 6, "reason": "rule_exit"}])
    er.merge_aggs(a, b)
    s = er.summarize(a)
    assert s["n"] == 3 and s["pfnet"] == pytest.approx(0.08 / 0.02)
    assert s["win_pct"] == pytest.approx(66.67, abs=0.01)
    assert s["avg_hold_bars"] == 4.0 and s["exit_reasons"] == {"rule_exit": 2, "stop_loss": 1}


def test_weekly_slope_no_lookahead():
    df = synth(300)
    base = er.weekly_hist_slope_daily(df)
    df2 = df.copy()
    df2.iloc[-3:, df2.columns.get_loc("Close")] *= 3     # change only the last days
    alt = er.weekly_hist_slope_daily(df2)
    k = len(df) - 10
    assert base.iloc[:k].fillna(0).equals(alt.iloc[:k].fillna(0))


def test_adx_bell_fires_on_trend_start():
    n = 300
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(3)
    c = np.r_[100 + rng.normal(0, 0.5, 150), 100 + np.arange(150) * 1.0 + rng.normal(0, 0.5, 150)]
    df = pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": 1.0}, index=idx)
    sig = er.v_adx_bell(df, 4)
    assert sig["long"].any()


def test_merge_dir_roundtrip(tmp_path):
    import json
    ag = er.new_agg()
    er.add_trades(ag, [{"ret": 0.1, "hold": 3, "reason": "rule_exit"}])
    for i in range(2):
        json.dump({"fetched": 5, "aggs": {"x__y__long__1d__atr2__v1": ag}},
                  open(tmp_path / f"s{i}.json", "w"))
    res = er.merge_dir(str(tmp_path))
    assert res["rows"][0]["n"] == 2 and res["symbols_fetched"] == 10
