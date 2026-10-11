import ast, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_research as cr


def test_day_returns_stop_and_close():
    E = np.array([100.0, 100.0]); o = E.copy()
    h = np.array([101.0, 101.0]); l = np.array([97.0, 99.5]); c = np.array([99.0, 100.5]); A = np.array([2.0, 2.0])
    g, hit = cr.day_returns(E, o, h, l, c, A, 1.0, 1)
    assert hit.tolist() == [True, False]
    assert abs(g[0] + 0.02) < 1e-9 and abs(g[1] - 0.005) < 1e-9
    gs, hs = cr.day_returns(E, o, np.array([103.0, 100.5]), l, c, A, 1.0, -1)
    assert hs.tolist() == [True, False] and abs(gs[0] + 0.02) < 1e-9


def test_gap_aware_exit_uses_open_through_stop():
    g, hit = cr.day_returns([100.0], [95.0], [96.0], [94.0], [95.5], [2.0], 1.0, 1, gap_aware=True)
    assert hit[0] and abs(g[0] + 0.05) < 1e-9


def test_simulate_stop_hold_and_state_exit():
    n = 12
    o = np.full(n, 100.0); h = o + 1; l = o - 1; c = o.copy()
    atr = np.full(n, 2.0)
    sig = np.zeros(n); sig[2] = 1
    tr = cr.simulate(o, h, l, c, atr, sig, 1.5, 4)
    assert tr[0][0] == 1 and tr[0][4] == "max_hold" and tr[0][2] - tr[0][1] == 3
    l2 = l.copy(); l2[4] = 96.0
    tr = cr.simulate(o, h, l2, c, atr, sig, 1.5, 4)
    assert tr[0][4] == "stop" and abs(tr[0][3] + 0.03) < 1e-9
    ex = np.zeros(n, bool); ex[5] = True
    tr = cr.simulate(o, h, l, c, atr, sig, 1.5, 8, exit_long=ex)
    assert tr[0][4] == "state_exit" and tr[0][2] == 5


def test_stats_pfnet_and_gross():
    s = cr.stats([0.02, -0.01, 0.03, -0.01], [0.03, 0.0, 0.04, 0.0], [1, 2, 3, 4], {"stop": 2})
    assert s["pfnet"] == 2.5 and s["n"] == 4 and s["win_pct"] == 50.0 and s["avg_hold_bars"] == 2.5


def test_half_life_mean_reverting_vs_trend():
    rng = np.random.default_rng(1)
    y = np.zeros(400)
    for i in range(1, 400):
        y[i] = 0.8 * y[i - 1] + rng.normal()
    lam, hl = cr.half_life(y)
    assert lam < 0 and 1 < hl < 6
    lam2, hl2 = cr.half_life(np.cumsum(rng.normal(size=400)) + np.arange(400))
    assert hl2 > 30


def test_signals_symmetry_and_shape():
    c = np.r_[np.linspace(100, 120, 60), np.linspace(120, 90, 60)]
    s = cr.sig_tsm(c, 20)
    assert s[30] == 1 and s[-1] == -1
    a = cr.sig_alexander(c, 0.1)
    assert (a == 1).any() and (a == -1).any()
    z = cr.sig_zmr(np.sin(np.arange(300) / 3.0) * 5 + 100, "fixed20")[0]
    assert (z == 1).any() and (z == -1).any()


def test_tag_grammar():
    t = cr.tag("chan_gap", "buy_on_gap", "long", "1d", {"top": 10, "atr": cr.kfmt(1.5)})
    assert t == "chan_gap__buy_on_gap__long__1d__atr1d5_top10__v1"
    assert t.islower() and len(t.split("__")) == 6


def test_select_xs_top_and_decile():
    rows = {"date": [1, 1, 1, 2], "score": [-0.05, -0.02, 0.01, -0.03]}
    for k in cr.KS:
        rows[f"G{k}"] = [0.01, 0.02, 0.03, 0.04]
        rows[f"S{k}"] = [0, 1, 0, 0]
    net, gross, hit = cr.select_xs("gapz_long", rows, {}, 0.008, top=1)[1.5]
    assert len(net) == 2 and abs(net[0] - 0.002) < 1e-9
    net, _, _ = cr.select_xs("dec_long", rows, {"1": 30, "2": 10}, 0.008)[1.5]
    assert len(net) == 4           # ceil(10% of 30)=3 on day 1, 1 on day 2
    net, _, _ = cr.select_xs("dec_short", rows, {"1": 10, "2": 10}, 0.008)[1.5]
    assert len(net) == 2           # 1 per day, highest score


def test_ts_cells_both_directions_and_no_stopless_cell():
    assert all(k > 0 for k in cr.KS)
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, .01, 400)))
    o = np.r_[c[0], c[:-1]]; h = np.maximum(o, c) * 1.005; l = np.minimum(o, c) * .995
    atr = cr.atr_arr(h, l, c)
    cells = list(cr.ts_cells(o, h, l, c, atr, "1d"))
    fams = {x[0] for x in cells}
    assert {"chan_tsm", "chan_alexander", "chan_shape", "chan_ema_regime", "chan_updays", "chan_zmr"} <= fams
    sides = {t[0] for f, v, p, s, H, xl, xs in cells for t in cr.simulate(o, h, l, c, atr, s, 1.5, H, xl, xs)}
    assert sides == {1, -1}


def test_gap_momentum_both_dirs():
    rng = np.random.default_rng(5)
    c = 100 * np.exp(np.cumsum(rng.normal(0, .01, 300)))
    o = c * (1 + rng.normal(0, .02, 300)); h = np.maximum(o, c) * 1.01; l = np.minimum(o, c) * .99
    out = cr.gap_momentum_cells(o, h, l, c, cr.atr_arr(h, l, c))
    assert any("__long__" in t for t in out) and any("__short__" in t for t in out)


def test_script_parses():
    ast.parse(open(os.path.join(os.path.dirname(cr.__file__), "chan_research.py")).read())
