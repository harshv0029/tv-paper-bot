import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import oneil_ext_research as ox  # noqa: E402
import oneil_research as orx  # noqa: E402

GRAMMAR = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*__[a-z0-9_]+?__(long|short)__(1d|1w)__[a-z0-9_]+__v1(__x__.+)?$")


def _flat(n, px=100.0):
    o = np.full(n, px)
    return o.copy(), o * 1.005, o * 0.995, o.copy(), np.full(n, 1e5)


def _trade(side=1, **kw):
    o, h, l, c, v = _flat(40)
    atr = np.full(40, 2.0)
    sig = np.zeros(40, bool)
    sig[5] = True
    for k, a in kw.items():
        arr = {"o": o, "h": h, "l": l, "c": c, "v": v}[k[0]]
        for i, val in a.items():
            arr[i] = val
    return o, h, l, c, v, atr, sig


def test_every_trade_has_a_stop_base_mode():
    o, h, l, c, v, atr, sig = _trade(l={10: 90.0})
    rows = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "base", 0, None, 1, 0.008, ox.EX["1d"])
    assert rows[0][3] == "stop" and rows[0][1] < 0  # stopped at 94, never rides to timeout


def test_belock_never_back_into_loss():
    # +20% pop then a drop to ~entry: breakeven lock exits at entry (gross ~0), base mode would lose more
    o, h, l, c, v, atr, sig = _trade(h={8: 125.0}, l={12: 93.0})
    base = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "base", 0, None, 1, 0.0, ox.EX["1d"])
    lock = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "belock", 15, None, 1, 0.0, ox.EX["1d"])
    assert lock[0][1] >= -1e-9 and lock[0][1] > base[0][1]


def test_scaled_loss_cut_averages_legs():
    o, h, l, c, v, atr, sig = _trade(l={10: 88.0})
    rows = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "sc", 0, None, 1, 0.0, ox.EX["1d"])
    assert rows[0][3].endswith("+half5") and abs(rows[0][1] - (-0.075)) < 1e-9


def test_state_exit_fires_at_next_open_and_short_side():
    o, h, l, c, v, atr, sig = _trade(o={16: 110.0})
    ex = np.zeros(40, bool)
    ex[15] = True
    rows = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "ma10w", 0, ex, 1, 0.0, ox.EX["1d"])
    assert rows[0][3] == "ma10w" and abs(rows[0][1] - 0.10) < 1e-9
    o, h, l, c, v, atr, sig = _trade(h={10: 108.0})
    rs = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "base", 0, None, -1, 0.0, ox.EX["1d"])
    assert rs[0][3] == "stop" and rs[0][1] < 0  # short has its own stop above entry


def test_dull_and_six_time_stops():
    o, h, l, c, v, atr, sig = _trade()
    rows = ox.simulate_x(sig, o, h, l, c, v, atr, 20, 3.0, "dull", 10, None, 1, 0.0, ox.EX["1d"])
    assert rows[0][3] == "dull" and rows[0][2] == 10


def test_mirror_is_reciprocal():
    o, h, l, c, v = _flat(10)
    mo, mh, ml, mc, mi, mrs = ox.mirror(o, h, l, c, None, np.full(10, 80.0))
    assert np.allclose(mc, 1 / c) and (mh >= ml).all() and np.allclose(mrs, 20.0) and mi is None


def _pattern_df():
    # long pole (+120%), tight flag, breakout on volume
    n = 360
    c = np.concatenate([np.linspace(50, 52, 300), np.linspace(52, 115, 25), np.full(33, 112.0) + np.sin(np.arange(33)) * 2, [125, 126]])
    c = c[:n] if len(c) >= n else np.r_[c, np.full(n - len(c), 126.0)]
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.004, np.minimum(o, c) * 0.996
    v = np.full(len(c), 1e5)
    v[-61:] = 4e5
    return o, h, l, c, v


def test_bull_signals_shapes_and_keys():
    o, h, l, c, v = _pattern_df()
    idx = np.linspace(100, 120, len(c))
    rs = np.full(len(c), 90.0)
    E, brk, F, X = ox.bull_signals(o, h, l, c, v, idx, rs, orx.CFG["1d"], ox.EX["1d"])
    assert all(len(a) == len(c) for a in list(E.values()) + list(F.values()) + list(X.values()))
    assert ("oneil_hft", "breakout", "na") in E and ("oneil_leaders", "firsthigh", "na") in E
    assert ("rswarn", 70) in X and ("ma200ext", 100) in X
    assert not np.isnan(brk.astype(float)).any()


def test_process_symbol_tags_grammar_both_directions():
    rng = np.random.default_rng(7)
    n = 900
    c = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.02, n)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.01, np.minimum(o, c) * 0.99
    v = rng.uniform(1e5, 3e5, n) * (1 + 3 * (rng.random(n) < 0.05))
    ix = pd.date_range("2020-01-01", periods=n, freq="B")
    df = pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=v), index=ix)
    idx = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))), index=ix)
    rs = pd.Series(rng.uniform(1, 99, n), index=ix)
    cells = {}
    ox.process_symbol(df, idx, rs, orx.CFG["1d"], ox.EX["1d"], 0.008, "1d", cells)
    assert cells
    assert all(GRAMMAR.match(t) for t in cells), [t for t in cells if not GRAMMAR.match(t)][:3]
    dirs = {t.split("__")[2] for t in cells}
    assert dirs == {"long", "short"}
    s = orx.finalize(cells, min_n=1)
    assert all("pfgross" in m and "win_pct" in m and "avg_held_bars" in m and "exit_reasons" in m for m in s.values())
