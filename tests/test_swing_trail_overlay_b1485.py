"""B-1485 (B-1484 stage 2): trailing-stop overlays on the fixed-stop swing families with no band_cap replay yet:
chan_kalman 1d/1h, minervini lab live cells, brk20 1h, O'Neil daily (ext_main leaders/rsscreen and the cup patterns).
Synthetic frames only (offline). Each test proves: off path unchanged, a trail mode changes exits, tags distinct."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import swing_bandcap as bc  # noqa: E402

MODES = ["off", "live"] + list(bc.TRAIL_MODES)


@pytest.fixture(scope="module")
def m():
    import main
    return main


def setup_function(_):
    bc.reset_trail()


def _nets(trades, key="net"):
    return [round(float(t[key]), 10) for t in trades]


# ---------------------------------------------------------------- chan_kalman
def test_chan_kalman_bandcap_off_matches_grid_and_trail_differs(m, monkeypatch):
    import chan_kalman_main_replay_job as ck
    assert ck.run_modes("trail") == MODES
    assert ck.run_modes("") == ["off"] and ck.run_modes("live") == ["off", "live"]
    # the real wired cells are parsed straight from main (z, ve, k, hold) and point at the grid's long tag
    for tf in ("1d", "1h"):
        cells = ck.live_cells(m, tf)
        assert cells, tf
        for tag, (z, ve, k, hold, d) in cells.items():
            assert tag == ck.make_tag("band_srcmain", d, tf, k, ve, z) and hold == ck.HOLD
    assert ck.live_cells(m, "5m") == {}
    # synthetic random walks rarely hit z=2 / Ve=1e-3, so swap in a grid cell that trades (monkeypatch, restored)
    tag = ck.make_tag("band_srcmain", "long", "1d", 4.0, 1e-4, 1.0)
    monkeypatch.setattr(m, "CHAN_KALMAN_1D_CELLS", {tag: (1.0, 1e-4, 4.0, 40)})
    frames = ck.synthetic_frames("1d", 3)
    grid = ck.run_job(m, "1d", iter(frames.items()))
    res = ck.run_job_bandcap(m, "1d", iter(frames.items()), MODES)
    g = next(r for r in grid["rows"] if r["tag"] == tag)["metrics"]
    rows = {r["band_cap"]: r for r in res["rows"]}
    assert rows["off"]["tag"] == tag and rows["off"]["metrics"] == g  # off = the grid's own row, bit-identical
    assert g["n"] > 0
    assert len({r["tag"] for r in res["rows"]}) == len(MODES)
    assert all(r["fixed_baseline"]["pfnet"] == g["pfnet"] for r in res["rows"])
    assert rows["live_tr0d5"]["metrics"]["avg_held_bars"] < g["avg_held_bars"]
    assert "trail_stop_hit" in rows["live_tr0d5"]["metrics"]["exit_reasons"]


def test_chan_kalman_walk_band_none_is_unchanged(m):
    import chan_kalman_main_replay_job as ck
    df = ck.synthetic_frames("1d", 1)["SYN0.NS"]
    pre = m.chan_kalman_band_v1_precompute(df, "1d", 1.0, 1e-4)
    a = ck.walk(m, df, "1d", pre, 2.5, (1,))
    b = ck.walk(m, df, "1d", pre, 2.5, (1,), ck.HOLD, None)
    assert a == b and a
    c = ck.walk(m, df, "1d", pre, 2.5, (1,), ck.HOLD, bc.make_band(df, "live_tr0d5"))
    assert [x[4] for x in c] != [x[4] for x in a]


# ---------------------------------------------------------------- minervini lab
def test_minervini_live_cell_specs_parse_every_wired_cell(m):
    import minervini_lab_main_replay_job as mv
    specs = mv.live_cell_specs(m)
    assert len(specs) == len(m.MINERVINI_LAB_LIVE_CELLS)
    exits = {ex for _t, ex, *_ in specs}
    assert exits <= set(m.MINERVINI_LAB_EXIT_VARIANTS) and {"pct8_hard", "ma50_trail"} <= exits
    for tag, ex, feat, want, maxh in specs:
        assert m.MINERVINI_LAB_LIVE_CELLS[tag] == (feat, want, maxh)
        assert len({bc.band_tag(tag, md) for md in MODES}) == len(MODES)
    assert "live_cells" in mv.JOBS and mv.run_modes("trail") == MODES


def test_minervini_off_unchanged_trail_changes_exits(m):
    import minervini_lab_main_replay_job as mv
    df = mv.synthetic_frame(0)
    sigs = mv.baseline_signals(df, "long")  # plentiful entries; the exit path is what is under test
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    arrs = (o, h, l, c, m.minervini_lab_moving_averages(c))
    specs = [("minervini_vcp__pct8_hard_srcmain__long__1d__h40__v1", "pct8_hard", None, None, 40),
             ("minervini_vcp__ma50_trail_srcmain__long__1d__h60__v1", "ma50_trail", None, None, 60)]
    out = mv.symbol_live_cells(m, df, sigs, {}, "long", cost, specs, MODES)
    for tag, ex, _f, _w, maxh in specs:
        ref = mv.walk(m, ex, df, arrs, sigs, "long", cost, None, maxh)  # main.minervini_lab_simulate_trade
        assert _nets(out[(tag, "off")]) == _nets(ref) and ref
    tr = out[(specs[0][0], "live_tr0d5")]
    assert _nets(tr) != _nets(out[(specs[0][0], "off")])
    assert any(t["reason"] == "trail_stop_hit" for t in tr)


def test_minervini_band_loop_reproduces_simulate_trade_when_band_never_binds(m):
    """simulate_trade_band = main.minervini_lab_simulate_trade's own loop: with a stop the band never lifts (a pct8 stop
    sits inside the 10% band) and the plain live mode, every trade's exit bar and price match the real function."""
    import minervini_lab_main_replay_job as mv
    df = mv.synthetic_frame(3)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    mas = m.minervini_lab_moving_averages(c)
    band = bc.make_band(df, "live")
    for sg in mv.baseline_signals(df, "long")[:40]:
        a = m.minervini_lab_simulate_trade("pct8_hard", o, h, l, c, sg, "long", 40, mas)
        b = mv.simulate_trade_band(m, "pct8_hard", o, h, l, c, sg, "long", 40, mas, band, df)
        assert (a is None) == (b is None)
        if a:
            assert a[0] == b[0] and a[1] == pytest.approx(b[1]) and a[2] == b[2]


# ---------------------------------------------------------------- brk20 (1h wired cell via brk20_replay)
def test_brk20_run_modes_keep_single_mode_behaviour():
    import brk20_replay as br
    assert br.run_modes("") == ["off"] and br.run_modes("live") == ["live"] and br.run_modes("live_tr1") == ["live_tr1"]
    assert br.run_modes("trail") == MODES
    assert br.run_modes("live,live_tr2") == ["off", "live", "live_tr2"]


def test_brk20_trail_changes_exits_off_unchanged(m):
    import brk20_replay as br
    assert m.BRK20_1H_LONG_TAG == br.make_tag("long", "1h", 4.0, 4.0)
    df = br.synthetic_frame(1)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    off = br.replay_symbol(m, df, "long", 2, 1, None, cost)
    off2 = br.replay_symbol(m, df, "long", 2, 1, None, cost, "off")
    tr = br.replay_symbol(m, df, "long", 2, 1, None, cost, "live_tr0d5")
    assert off and _nets(off) == _nets(off2)
    assert _nets(tr) != _nets(off) and any(t["reason"] == "trail_stop_hit" for t in tr)
    tags = {bc.band_tag(m.BRK20_1H_LONG_TAG, md) for md in MODES}
    assert len(tags) == len(MODES)


# ---------------------------------------------------------------- O'Neil daily
def _syn_daily(seed=0):
    import minervini_lab_main_replay_job as mv
    return mv.synthetic_frame(seed)


def test_oneil_ext_main_trade_off_unchanged_trail_differs(m):
    import oneil_nonoverlap as onl
    assert onl.band_modes("") == ["off"] and onl.band_modes("trail") == MODES
    df = _syn_daily(0)
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    atr = m.oneil_atr14(h, l, c)
    sig = np.zeros(len(c), bool)
    sig[250::12] = True
    off, _ = onl.nonovl_trades_main(sig, o, h, l, c, atr, 40, 2.0, 1, 0.008)
    off2, _ = onl.nonovl_trades_main(sig, o, h, l, c, atr, 40, 2.0, 1, 0.008, "off")
    tr, _ = onl.nonovl_trades_main(sig, o, h, l, c, atr, 40, 2.0, 1, 0.008, "live_tr0d5")
    assert off and off == off2
    assert _nets(tr) != _nets(off) and any(t["reason"] == "trail_stop_hit" for t in tr)
    for tag in (m.ONEIL_LEADERS_1D_TAG, m.ONEIL_RSSCREEN_1D_N200_TAG):
        base = tag.replace("__nonovl__v2", "__v1")
        got = {onl.no.nonovl_tag(bc.band_tag(base, md)) for md in MODES}
        assert tag in got and len(got) == len(MODES)


def test_oneil_replay_wired_cup_tags_parse_and_trail_differs(m):
    import oneil_replay as R
    assert R.run_modes("") == ["off"] and R.run_modes("live") == ["live"] and R.run_modes("trail") == MODES
    for t in (m.ONEIL_CUP_HANDLE_1D_TAG, m.ONEIL_CUP_NOHANDLE_1D_TAG, m.ONEIL_SAUCER_1D_TAG):
        sp = R.parse_tag(t)
        assert sp["tf"] == "1d" and sp["dir"] == "long" and sp["mode"] == "atr"
        assert len({bc.band_tag(t, md) for md in MODES}) == len(MODES)
    df = _syn_daily(0)
    sp = R.parse_tag("oneil_pivot__breakout__long__1d__atr2_chase10_h40_rsnone__v2")
    off = R.replay_symbol(df, None, sp, 0.008, 0, True)
    off2 = R.replay_symbol(df, None, sp, 0.008, 0, True, "off")
    tr = R.replay_symbol(df, None, sp, 0.008, 0, True, "live_tr0d5")
    assert off and _nets(off) == _nets(off2)
    assert _nets(tr) != _nets(off)
