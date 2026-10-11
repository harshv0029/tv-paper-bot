import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts"))
spec = importlib.util.spec_from_file_location("oneil_replay", R / "scripts" / "oneil_replay.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)
orx = rp.orx

TAG = "oneil_flatbase__breakout__long__1w__atr3_avg1_chase10_h26_rsnone__v1"


def test_parse_tags():
    s = rp.parse_tag(TAG)
    assert (s["family"], s["dir"], s["tf"], s["hold"], s["mode"], s["val"], s["chase"], s["rs"]) == \
        ("oneil_flatbase", "long", "1w", 26, "avg", 3.0, 0.10, "none")
    assert rp.parse_tag("oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone_trl1__v1")["mode"] == "trl"
    assert rp.parse_tag("oneil_pivot__breakout__short__1d__atr2d5_chase5_h40_rs80__v1")["val"] == 2.5
    with pytest.raises(ValueError):
        rp.parse_tag("gap_and_go")
    for t in rp.DEFAULT_TAGS:
        rp.parse_tag(t)


def _flat_base_series():
    """Synthetic: long advance, tight flat base, then a high-volume breakout, then a drift up (or down)."""
    rng = np.random.default_rng(1)
    adv = 100 * np.cumprod(np.full(20, 1.04))            # ~+120% advance over 20 bars
    flat = adv[-1] * (1 + rng.uniform(-0.02, 0.02, 7))   # 7-bar flat base inside 12%
    brk = [flat.max() * 1.05]
    after = brk[0] * np.cumprod(np.full(30, 1.01))
    c = np.concatenate([np.full(30, 100.0), adv, flat, brk, after])
    o = np.roll(c, 1)
    o[0] = c[0]
    h, l = np.maximum(o, c) * 1.005, np.minimum(o, c) * 0.995
    v = np.full(len(c), 1000.0)
    v[30 + 20 + 7] = 5000.0                              # breakout bar volume
    idx = pd.date_range("2020-01-05", periods=len(c), freq="W")
    return pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=v), index=idx)


def test_walk_forward_has_no_lookahead_and_stop_on_every_trade():
    df = _flat_base_series()
    sp = rp.parse_tag("oneil_flatbase__breakout__long__1w__atr3_chase10_h12_rsnone__v1")
    tr = rp.replay_symbol(df, None, sp, 0.008)
    assert tr, "synthetic breakout must trigger"
    # truncating the future after the entry bar must not change the signal bar (no look-ahead)
    first = tr[0]["entry_bar"]
    tr2 = rp.replay_symbol(df.iloc[:first + 13], None, sp, 0.008)
    assert tr2 and tr2[0]["entry_bar"] == first
    assert all(t["reason"] in ("stop", "trail_stop", "timeout") for t in tr)
    assert all(abs(t["net"] - (t["gross"] - 0.008)) < 1e-12 for t in tr)


def test_stop_gap_fills_at_open_and_caps_loss():
    df = _flat_base_series()
    sp = rp.parse_tag("oneil_flatbase__breakout__long__1w__atr3_chase10_h12_rsnone__v1")
    base = rp.replay_symbol(df, None, sp, 0.0)
    e = base[0]["entry_bar"]
    d2 = df.copy()
    d2.iloc[e + 1, d2.columns.get_loc("Open")] = d2["Open"].iloc[e] * 0.5   # gap far through any ATR stop
    for col in ("High", "Close"):
        d2.iloc[e + 1, d2.columns.get_loc(col)] = d2["Open"].iloc[e] * 0.52
    d2.iloc[e + 1, d2.columns.get_loc("Low")] = d2["Open"].iloc[e] * 0.45
    t = rp.replay_symbol(d2, None, sp, 0.0)[0]
    assert t["reason"] == "stop" and t["held"] == 2
    assert t["gross"] == pytest.approx(0.5 - 1, abs=0.02)   # filled at the gap open, not at the stop level


def test_avg_down_flag_and_slippage_make_losses_worse_not_better():
    df = _flat_base_series()
    sp = rp.parse_tag("oneil_flatbase__breakout__long__1w__atr3_chase10_h12_rsnone__v1")
    a = rp.replay_symbol(df, None, sp, 0.008)
    s = rp.replay_symbol(df, None, sp, 0.008, slip=0.01)
    assert len(a) == len(s)
    assert sum(x["net"] for x in s) <= sum(x["net"] for x in a) + 1e-12


def test_cells_merge_additively_and_finalize_metrics():
    c1, c2 = rp.new_cell(), rp.new_cell()
    rp.add_trades(c1, [dict(net=0.2, gross=0.208, held=4, reason="timeout"), dict(net=-0.1, gross=-0.092, held=2, reason="stop")])
    rp.add_trades(c2, [dict(net=0.1, gross=0.108, held=6, reason="timeout"), dict(net=-0.05, gross=-0.042, held=3, reason="stop")])
    m = rp.merge_cells([{"t": c1}, {"t": c2}])["t"]
    assert m["n"] == 4 and m["wins"] == 2 and m["held"] == 15
    f = rp.finalize({"t": m}, "universe-x")["t"]
    assert f["pfnet"] == pytest.approx(0.3 / 0.15, abs=1e-3)
    assert f["win_pct"] == 50.0 and f["avg_hold_bars"] == 3.75 and f["universe"] == "universe-x"
    assert f["pfgross"] is not None and "timeout" in f["exit_reasons"] and "stop" in f["exit_reasons"]
    assert f["pfnet_ex_top5"] is not None
    table = rp.format_table({"t": f})
    assert "pfnet_ex_top5" in table and "t\t4\t50.0" in table


def test_crosscheck_agrees_with_research_simulate_on_synthetic():
    df = _flat_base_series()
    sp = rp.parse_tag("oneil_flatbase__breakout__long__1w__atr3_chase10_h12_rsnone__v1")
    trades = rp.replay_symbol(df, pd.Series(np.nan, index=df.index), sp, 0.008)
    assert rp._crosscheck(sp, "SYN", df, pd.Series(np.nan, index=df.index), 0.008, trades) == []


def test_uses_full_universe_loader_and_cost_not_nifty200():
    src = (R / "scripts" / "oneil_replay.py").read_text()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "_load_nse_universe_from_file()" in code and "app.NSE_FULL_UNIVERSE" not in code
    assert "ROUND_TRIP_COST_PCT" in code
