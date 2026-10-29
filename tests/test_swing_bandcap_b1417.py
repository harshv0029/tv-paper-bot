"""B-1417: shared live resting-stop model (scripts/swing_bandcap.py), band_cap on every live swing replay, and the
swing-bandcap-replay.yml workflow."""
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
import brk20_replay as br  # noqa: E402
import chan_shape_macddiv_main_replay as cs  # noqa: E402
import oneil_replay as onr  # noqa: E402
import swing_bandcap as bc  # noqa: E402
import swing_bandcap_replay as sbr  # noqa: E402
import swing_classic_main_replay as cl  # noqa: E402
import swing_short_main_replay as ss  # noqa: E402

WF = os.path.join(ROOT, ".github", "workflows", "swing-bandcap-replay.yml")


# ------------------------------------------------------------------ helper math
def test_band_constants_match_the_live_preclamp():
    import kotak_real_orders as kro
    assert bc.BAND_PCT == kro._PRICE_BAND_PCTS[0]
    assert bc.band_floor(100.0) == pytest.approx(100 * 0.9 * 1.003)
    assert bc.band_ceiling(100.0) == pytest.approx(100 * 1.1 * 0.997)


def test_resting_trigger_long_and_short():
    assert bc.resting_trigger(80.0, 100.0, "long") == (pytest.approx(90.27), True)   # stop below the band: floor
    assert bc.resting_trigger(95.0, 100.0, "long") == (95.0, False)                  # inside the band: strategy stop
    assert bc.resting_trigger(120.0, 100.0, "short") == (pytest.approx(109.67), True)
    assert bc.resting_trigger(105.0, 100.0, "short") == (105.0, False)


def test_resting_stop_exit_fills():
    # long, band floor bound: triggered by the low, filled at the trigger
    assert bc.resting_stop_exit("live", "long", 80.0, 100.0, 95.0, 90.0, 96.0) == (pytest.approx(90.27), "band_floor_stop_hit")
    # gap below the trigger fills at the open
    assert bc.resting_stop_exit("live", "long", 80.0, 100.0, 85.0, 84.0, 86.0) == (85.0, "band_floor_stop_hit")
    # strategy stop inside the band: intraday trigger at the strategy stop
    assert bc.resting_stop_exit("live", "long", 95.0, 100.0, 98.0, 94.0, 99.0) == (95.0, "resting_stop_hit")
    assert bc.resting_stop_exit("live", "long", 80.0, 100.0, 95.0, 91.0, 96.0) is None
    # short mirror on the high
    assert bc.resting_stop_exit("live", "short", 120.0, 100.0, 105.0, 104.0, 110.0) == (pytest.approx(109.67), "band_floor_stop_hit")
    assert bc.resting_stop_exit("live", "short", 120.0, 100.0, 112.0, 111.0, 113.0) == (112.0, "band_floor_stop_hit")
    # off / missing prev close never trigger
    assert bc.resting_stop_exit("off", "long", 80.0, 100.0, 50.0, 40.0, 60.0) is None
    assert bc.resting_stop_exit("live", "long", 80.0, float("nan"), 50.0, 40.0, 60.0) is None


def test_mode_parsing():
    assert bc.mode_from_env({}) == "off"
    assert bc.mode_from_env({"BAND_CAP": ""}) == "off"
    assert bc.mode_from_env({"BAND_CAP": "LIVE"}) == "live"
    with pytest.raises(SystemExit):
        bc.normalize_mode("intraday")


def test_prev_session_close_daily_and_hourly():
    d = pd.DataFrame({"Date": ["2024-01-01", "2024-01-02", "2024-01-03"], "Close": [10.0, 11.0, 12.0]})
    p = bc.prev_session_close(d)
    assert np.isnan(p[0]) and list(p[1:]) == [10.0, 11.0]
    h = pd.DataFrame({"Date": ["2024-01-01 09:15", "2024-01-01 10:15", "2024-01-02 09:15", "2024-01-02 10:15"],
                      "Close": [10.0, 10.5, 11.0, 11.5]})
    p = bc.prev_session_close(h)
    assert np.isnan(p[0]) and np.isnan(p[1]) and list(p[2:]) == [10.5, 10.5]  # yesterday's LAST close, not the prior bar


def test_band_tag_grammar():
    assert bc.band_tag("x__v__long__1d__atr4_rr4__v1", "off") == "x__v__long__1d__atr4_rr4__v1"
    assert (bc.band_tag("brk20_min_rr__main_replay__long__1d__atr4_rr4__v1", "live")
            == "brk20_min_rr__main_replay__long__1d__atr4_rr4_rsbandfloor__v1")
    assert (bc.band_tag("chan_shape__mom_mr__long__1d__atr4d0_hold10__nonovl__v2", "live")
            == "chan_shape__mom_mr__long__1d__atr4d0_hold10_rsbandfloor__nonovl__v2")
    # same tag B-1413 registered for the OB exitinval band-live run
    assert (bc.band_tag("order_block_delta__exitinval__long__1d__atr6d0_hold30_sigema13w__v1", "live")
            == "order_block_delta__exitinval__long__1d__atr6d0_hold30_rsbandfloor_sigema13w__v1")
    assert bc.band_tag("power_play", "live") == "power_play__rsbandfloor"


def test_memo_main_shares_entry_calls_per_bar():
    calls = []
    mod = types.SimpleNamespace(sig=lambda df, x: calls.append(len(df)) or {"n": len(df), "x": x}, other=7)
    mm = bc.MemoMain(mod, ["sig"])
    df = pd.DataFrame({"a": range(10)})
    assert mm.sig(df.iloc[:5], 1) == mm.sig(df.iloc[:5], 1)
    mm.sig(df.iloc[1:6], 1)  # same length, different last bar -> separate entry
    assert calls == [5, 5] and mm.other == 7
    mm.reset()
    mm.sig(df.iloc[:5], 1)
    assert calls == [5, 5, 5]


# ------------------------------------------------------------------ every replay accepts band_cap, default off
@pytest.mark.parametrize("fn", [br.replay_symbol, ss.replay_symbol, cs.replay_symbol, cl.replay_symbol,
                                onr.replay_symbol])
def test_each_replay_accepts_band_cap_default_off(fn):
    assert inspect.signature(fn).parameters["band_cap"].default == "off"


def test_classic_family_list_in_sync():
    assert tuple(cl.FAMILIES) == sbr.CLASSIC
    assert set(cl.ENTRY_FNS) <= set(sbr.MEMO_FNS)


def _crash_frame():
    n = 80
    c = np.full(n, 100.0)
    o, h, lo = c.copy(), c + 0.5, c - 0.5
    o[50], lo[50], c[50], h[50] = 99.0, 84.0, 86.0, 99.5   # -14% intraday, closes 86 (above the 80 strategy stop)
    c[51:] = 86.0
    o[51:], h[51:], lo[51:] = 86.0, 86.5, 85.5
    df = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": 1e6})
    df["Date"] = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=n)]
    return df


def _stub_main():
    """Entry fires once at bar 40 (stop 80 = 20% below), exit fn never fires, live resting level = the frozen stop."""
    def entry(df):
        return {"entry_price": 100.0, "stop_loss": 80.0, "atr_at_entry": 5.0} if len(df) == 41 else None
    return types.SimpleNamespace(
        POWER_PLAY_LAUNCH_MAX_DAYS=5, POWER_PLAY_CONSOL_MAX_DAYS=5, power_play_entry_signal=entry,
        power_play_exit_reason=lambda df, day, stop, atr, rmc: (None, max(rmc, float(df["Close"].iloc[-1]))),
        _swing_strategy_stop_level=lambda tag, stop, atr, rmc: float(stop))


def test_classic_band_live_exits_at_floor_and_off_is_unchanged():
    m, df = _stub_main(), _crash_frame()
    off = cl.replay_symbol(m, df, "power_play", "power_play", 0.008)
    assert off == cl.replay_symbol(m, df, "power_play", "power_play", 0.008, "off")
    assert [t["reason"] for t in off] == ["data_end_forced_close"]
    live = cl.replay_symbol(m, df, "power_play", "power_play", 0.008, "live")
    assert live[0]["reason"] == "band_floor_stop_hit"
    assert live[0]["gross"] == pytest.approx(100 * 0.9 * 1.003 / 100.0 - 1)  # filled at the floor (open 99 above it)
    assert live[0]["held"] == 10


def test_brk20_default_equals_off_on_synthetic():
    import main
    df = br.synthetic_frame(3, n=300)
    a = br.replay_symbol(main, df, "long", 4.0, 4.0, None, 0.008)
    assert a == br.replay_symbol(main, df, "long", 4.0, 4.0, None, 0.008, "off")


def test_oneil_weekly_refuses_live_band():
    sp = onr.parse_tag("oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v1")
    df = pd.DataFrame({"Open": [1.0] * 5, "High": [1.0] * 5, "Low": [1.0] * 5, "Close": [1.0] * 5, "Volume": [1.0] * 5})
    with pytest.raises(ValueError):
        onr.replay_symbol(df, None, sp, 0.008, band_cap="live")


# ------------------------------------------------------------------ workflow
def test_workflow_parses_with_expected_inputs():
    wf = yaml.safe_load(open(WF))
    on = wf.get("on", wf.get(True))
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["strategies"]["default"] == "all"
    assert inputs["band_cap"]["default"] == "live"
    rep = wf["jobs"]["replay"]
    assert rep["strategy"]["max-parallel"] <= 4
    body = yaml.safe_dump(wf)
    assert "scripts/swing_bandcap_replay.py run" in body and "scripts/swing_bandcap_replay.py merge" in body
    assert "upload-artifact" in body


def test_plan_matrix():
    p = sbr.plan({"STRATEGIES": "all", "NSHARDS": "2"})
    assert len(p["include"]) == len(sbr.FAMILIES) * 2
    p = sbr.plan({"STRATEGIES": "brk20,short_swing", "NSHARDS": "3"})
    assert {x["family"] for x in p["include"]} == {"brk20", "short_swing"} and len(p["include"]) == 6
    with pytest.raises(SystemExit):
        sbr.plan({"STRATEGIES": "nope"})
