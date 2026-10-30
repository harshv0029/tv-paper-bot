"""B-1426: band_cap (live resting-stop model) on the remaining LIVE swing families - island, gapfade, pl1d, swingminrr
(VCP long), tasuki short, swingminrr gate short 1h, envelope 1h, cup cheat 1h - and their wiring into
scripts/swing_bandcap_replay.py + swing-bandcap-replay.yml. Synthetic frames and stub `main` modules only."""
import inspect
import os
import sys
import types

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import cup_cheat_main_replay as cup  # noqa: E402
import envelope_main_replay as env  # noqa: E402
import gapfade_main_replay as gf  # noqa: E402
import island_main_replay as ir  # noqa: E402
import pl1d_main_replay as pl  # noqa: E402
import swing_bandcap as bc  # noqa: E402
import swing_bandcap_replay as sbr  # noqa: E402
import swing_short_main_replay as ss  # noqa: E402
import tasuki_swingminrr_short_main_replay as tsm  # noqa: E402

WF = os.path.join(ROOT, ".github", "workflows", "swing-bandcap-replay.yml")
NEW = ("island", "gapfade", "pl1d", "swingminrr", "tasuki_short", "swm1h_short", "envelope", "cup_cheat")
FLOOR = 100 * 0.9 * 1.003      # band floor off a 100 prev close
CEIL = 100 * 1.1 * 0.997       # band ceiling off a 100 prev close


def _frame(n=120, shock=90, side="long"):
    """Flat at 100; on bar `shock` a -14% (long) / +14% (short) intraday wick that CLOSES inside the strategy stop
    (86 vs a long stop of 80; 114 vs a short stop of 120), then flat at the new close."""
    c = np.full(n, 100.0)
    o, h, lo = c.copy(), c + 0.5, c - 0.5
    if side == "long":
        o[shock], lo[shock], c[shock], h[shock] = 99.0, 84.0, 86.0, 99.5
        nc = 86.0
    else:
        o[shock], h[shock], c[shock], lo[shock] = 101.0, 116.0, 114.0, 100.5
        nc = 114.0
    c[shock + 1:] = nc
    o[shock + 1:], h[shock + 1:], lo[shock + 1:] = nc, nc + 0.5, nc - 0.5
    df = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": 1e6})
    df["Date"] = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=n)]
    return df


# ------------------------------------------------------------------ shared helpers
def test_make_band_and_band_hit():
    df = _frame()
    assert bc.make_band(df, "off") is None and bc.make_band(df, None) is None
    band = bc.make_band(df, "LIVE")
    assert band[0] == "live" and np.isnan(band[1][0]) and band[1][90] == 100.0
    assert bc.band_hit(None, df, 90, 80.0) is None
    assert bc.band_hit(band, df, 90, 80.0, "long") == (pytest.approx(FLOOR), "band_floor_stop_hit")
    assert bc.band_hit(band, df, 89, 80.0, "long") is None
    s = _frame(side="short")
    assert bc.band_hit(bc.make_band(s, "live"), s, 90, 120.0, "short") == (pytest.approx(CEIL), "band_floor_stop_hit")


@pytest.mark.parametrize("fn", [ir.replay_symbol, gf.replay_symbol, pl.replay_symbol, env.replay_symbol,
                                cup.replay_symbol, tsm.replay_symbol])
def test_each_new_replay_accepts_band_cap_default_off(fn):
    assert inspect.signature(fn).parameters["band_cap"].default == "off"


@pytest.mark.parametrize("fn", [ir.run_trade, gf.gapfade_trade, pl.pl1d_trade, env.envelope_trade, cup.cup_trade])
def test_trade_helpers_default_band_none(fn):
    assert inspect.signature(fn).parameters["band"].default is None


def _check(off, live, reason="band_floor_stop_hit", px=FLOOR, side="long", held=None):
    assert len(off) == 1 and off[0]["reason"] != reason            # off: the wick closes inside the stop, no exit
    assert live[0]["reason"] == reason
    g = (px - 100.0) / 100.0 * (1 if side == "long" else -1)
    assert live[0]["gross"] == pytest.approx(g)
    assert live[0]["net"] == pytest.approx(g - 0.008)
    if held is not None:
        assert live[0]["held"] == held


# ------------------------------------------------------------------ island (long 1d)
def _island_stub():
    tag = "reversal__island_none__long__1d__atr1d5_within8__nonovl__v2"
    return tag, types.SimpleNamespace(
        _ISLAND_FILTER_OF_TAG={tag: "none"},
        island_bottom_signal_on_last_bar=lambda df: len(df) == 41,
        island_swing_entry_signal=lambda df, t: {"entry_price": 100.0, "stop_loss": 80.0, "atr_at_entry": 5.0},
        brk20_min_rr_exit_reason=lambda df, day, ep, stop, d: (None, None))


def test_island_band_live_vs_off():
    tag, m = _island_stub()
    df = _frame()
    off = ir.replay_symbol(m, df, [tag], 0.008)[tag]
    assert off == ir.replay_symbol(m, df, [tag], 0.008, None, "off")[tag]
    assert off[0]["reason"] == "data_end_forced_close"
    _check(off, ir.replay_symbol(m, df, [tag], 0.008, None, "live")[tag], held=50)


# ------------------------------------------------------------------ gapfade (long 1d), trade helper
def test_gapfade_trade_band_live_vs_off():
    m = types.SimpleNamespace(_gapfade_exit_adapter=lambda df, day, stop, atr, run: (None, run))
    df = gf._prep(_frame())
    sig = {"entry_price": 100.0, "stop_loss": 80.0, "atr_at_entry": 5.0}
    off = [gf.gapfade_trade(m, df, 40, sig, 0.008)]
    assert off == [gf.gapfade_trade(m, df, 40, sig, 0.008, None)]
    live = [gf.gapfade_trade(m, df, 40, sig, 0.008, bc.make_band(df, "live"))]
    _check(off, live, held=50)
    assert live[0]["exit_i"] == 90


# ------------------------------------------------------------------ pl1d (long 1d), full replay_symbol
def test_pl1d_band_live_vs_off():
    tag = "gap__runaway__long__1d__atr4_h20__v1"
    m = types.SimpleNamespace(
        PL1D_CELLS={tag: (None, 4.0, 200)},
        pl1d_long_entry_signal=lambda df, t: ({"entry_price": 100.0, "stop_loss": 80.0, "atr_at_entry": 5.0}
                                              if len(df) == 61 else None),
        pl1d_exit_reason=lambda df, day, stop, hold: (None, None))
    df = _frame()
    off = pl.replay_symbol(m, df, [tag], 0.008)[tag]
    assert off == pl.replay_symbol(m, df, [tag], 0.008, "off")[tag]
    _check(off, pl.replay_symbol(m, df, [tag], 0.008, "live")[tag], held=30)


# ------------------------------------------------------------------ swingminrr VCP long (swing_short_main_replay)
def test_swingminrr_long_band_live_vs_off():
    tag = "swingminrr__minervini_vcp_base__long__1d__atr1d5__v1"
    m = types.SimpleNamespace(
        swingminrr_vcp_entry_signal=lambda df, t: ({"entry_price": 100.0, "stop_loss": 80.0, "atr_at_entry": 5.0}
                                                   if len(df) == 70 else None),
        _swingminrr_exit_adapter=lambda df, day, stop, atr, ep: (None, None))
    spec = {"dir": "long", "gate_rr": None}
    df = _frame()
    off = ss.replay_symbol(m, df, tag, spec, 0.008)
    assert off[0]["reason"] == "data_end_forced_close"
    _check(off, ss.replay_symbol(m, df, tag, spec, 0.008, "signal_close", None, "live"), held=21)


# ------------------------------------------------------------------ tasuki / swingminrr gate short (BUY stop, CEILING)
def test_swm1h_short_band_live_uses_ceiling():
    tag = "swingminrr__brk20_gate__short__1h__atr3_rr4__v1"
    m = types.SimpleNamespace(
        swingminrr_gate_short_entry_signal=lambda sub: ({"entry_price": 100.0, "stop_loss": 120.0}
                                                        if sub.index[-1] == 70 else None),
        swingminrr_gate_short_exit_reason=lambda bars, stop, target=None: None)
    spec = {"group": "swm1h", "rr": None}
    df = _frame(side="short")
    off = tsm.replay_symbol(m, df, tag, spec, 0.008)
    assert off == tsm.replay_symbol(m, df, tag, spec, 0.008, "signal_close", "off")
    assert off[0]["reason"] == "data_end_forced_close"
    _check(off, tsm.replay_symbol(m, df, tag, spec, 0.008, "signal_close", "live"), px=CEIL, side="short", held=20)


def test_tasuki_short_band_gap_fills_at_open():
    tag = "tasuki__gap_etf__short__1d__atr6_h3__v1"
    df = _frame(side="short")
    df.loc[90, ["Open", "High", "Low", "Close"]] = [112.0, 116.0, 111.0, 114.0]  # gaps above the ceiling: fill at open
    m = types.SimpleNamespace(
        tasuki_short_signal=lambda sub: sub.index[-1] == 88,
        _compute_atr_value=lambda sub, n: 5.0,
        tasuki_short_stop=lambda ep, atr, k: ep + 20.0,
        tasuki_short_exit_reason=lambda bars, stop: None)
    spec = {"group": "tasuki", "atr": 6.0}
    off = tsm.replay_symbol(m, df, tag, spec, 0.008)
    _check(off, tsm.replay_symbol(m, df, tag, spec, 0.008, "signal_close", "live"), px=112.0, side="short", held=2)


# ------------------------------------------------------------------ envelope / cup cheat (1h), trade helpers
def test_envelope_trade_long_and_short():
    lt, st = "envelope__0d05_fade__long__1h__atr6_h30__v1", "envelope__0d05_fade__short__1h__atr6_h30__v1"
    m = types.SimpleNamespace(ENVELOPE_1H_CELLS={lt: ("long", 6.0, 300), st: ("short", 6.0, 300)},
                              envelope_fade_exit_reason=lambda df, d, k, stop, hold: None)
    df = _frame()
    off = [env.envelope_trade(m, df, 40, {"entry_price": 100.0, "stop_loss": 80.0}, lt, 0.008)]
    _check(off, [env.envelope_trade(m, df, 40, {"entry_price": 100.0, "stop_loss": 80.0}, lt, 0.008,
                                    bc.make_band(df, "live"))])
    s = _frame(side="short")
    off = [env.envelope_trade(m, s, 40, {"entry_price": 100.0, "stop_loss": 120.0}, st, 0.008)]
    _check(off, [env.envelope_trade(m, s, 40, {"entry_price": 100.0, "stop_loss": 120.0}, st, 0.008,
                                    bc.make_band(s, "live"))], px=CEIL, side="short")


def test_cup_trade_band_live_vs_off_and_hourly_band_reference():
    tag = "base__cup_cheat_3c__long__1h__atr2d5_h30__v1"
    m = types.SimpleNamespace(CUP_CHEAT_1H_CELLS={tag: (2.5, 300)}, cup_cheat_3c_fires=None,
                              cup_cheat_3c_entry_signal=None, cup_cheat_3c_exit_reason=lambda df, k, stop, hold: None)
    df = _frame()
    sig = {"entry_price": 100.0, "stop_loss": 80.0}
    off = [cup.cup_trade(m, df, 40, sig, tag, 0.008)]
    _check(off, [cup.cup_trade(m, df, 40, sig, tag, 0.008, "long", bc.make_band(df, "live"))])
    # hourly bars: the band reference is the PREVIOUS SESSION's last close, not the prior hourly bar
    h = df.copy()
    h["Date"] = [f"2024-01-{1 + i // 7:02d} {9 + i % 7:02d}:15" for i in range(len(h))]
    band = bc.make_band(h, "live")
    assert band[1][7] == h["Close"].iloc[6] and band[1][13] == h["Close"].iloc[6]


# ------------------------------------------------------------------ driver + workflow
def test_driver_families_and_plan():
    assert set(NEW) <= set(sbr.FAMILIES) and len(set(sbr.FAMILIES)) == len(sbr.FAMILIES)
    p = sbr.plan({"STRATEGIES": ",".join(NEW), "NSHARDS": "2"})
    assert {x["family"] for x in p["include"]} == set(NEW) and len(p["include"]) == 2 * len(NEW)
    assert len(sbr.plan({"STRATEGIES": "all", "NSHARDS": "1"})["include"]) == len(sbr.FAMILIES)


def test_driver_family_tags_are_the_live_constants():
    import main
    sbr._load_mods()
    assert sbr.family_tags(main, "island") == [t for t in main.ISLAND_ALL_TAGS
                                                if "__v1" not in t and "__seg" not in t]
    assert set(main.ISLAND_SWING_TAGS) <= set(sbr.family_tags(main, "island"))
    assert sbr.family_tags(main, "gapfade") == list(main.GAPFADE_TAGS)
    assert sbr.family_tags(main, "pl1d") == list(main.PL1D_CELLS)
    assert sbr.family_tags(main, "swingminrr") == list(main.SWINGMINRR_TAGS)
    assert sbr.family_tags(main, "tasuki_short") == list(main.TASUKI_SHORT_CELLS)
    assert sbr.family_tags(main, "swm1h_short") == list(main.SWINGMINRR_SHORT_1H_CELLS)
    assert sbr.family_tags(main, "envelope") == list(main.ENVELOPE_LONG_LIVE_CELLS)
    assert sbr.family_tags(main, "cup_cheat") == list(main.CUP_CHEAT_LONG_LIVE_CELLS)
    for f in NEW:  # every live-mode result is a NEW tag, never a rename
        for t in sbr.family_tags(main, f):
            assert bc.band_tag(t, "live") != t and "rsbandfloor" in bc.band_tag(t, "live")


def test_driver_replay_dispatch_island_and_pl1d():
    sbr._load_mods()
    tag, m = _island_stub()
    df = _frame()
    assert sbr.replay(m, "island", df, [tag], 0.008, "live")[tag][0]["reason"] == "band_floor_stop_hit"
    assert sbr.replay(m, "island", df, [tag], 0.008, "off")[tag][0]["reason"] == "data_end_forced_close"


def test_memo_fns_cover_new_entry_functions():
    for fn in ("island_swing_entry_signal", "gapfade_long_entry_signal", "pl1d_long_entry_signal",
               "swingminrr_vcp_entry_signal", "minervini_vcp_entry_signal", "tasuki_short_signal",
               "swingminrr_gate_short_entry_signal", "envelope_fade_entry_signal", "cup_cheat_3c_entry_signal"):
        assert fn in sbr.MEMO_FNS


def test_workflow_lists_new_families():
    wf = yaml.safe_load(open(WF))
    on = wf.get("on", wf.get(True))
    desc = on["workflow_dispatch"]["inputs"]["strategies"]["description"]
    for f in NEW:
        assert f in desc
