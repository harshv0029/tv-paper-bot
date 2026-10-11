import os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import oneil_patterns as op

CFG = dict(cupmin=35, cupmax=250, saucer_min=100, hmin=5, hmax=20, dbmin=20, dbmax=120, vol=50)


def _bars(close, vol_spike_at=None):
    c = np.asarray(close, float)
    h, l, o = c * 1.003, c * 0.997, c.copy()
    v = np.full(len(c), 1e6)
    if vol_spike_at is not None:
        v[vol_spike_at] = 5e6
    return o, h, l, c, v


def _cup_path():
    pre = np.full(60, 80.0)
    up = np.linspace(80, 100, 20)
    down = np.linspace(100, 78, 25)
    upc = np.linspace(78, 97, 25)
    handle = np.linspace(97, 93, 8)
    return np.concatenate([pre, up, down, upc, handle])


def test_cup_with_handle_fires_on_breakout_only():
    base = _cup_path()
    brk = np.append(base, 101.0)
    o, h, l, c, v = _bars(brk, vol_spike_at=len(brk) - 1)
    sig, piv = op.detect_cup(h, l, c, v, CFG, handle=True)
    assert sig[-1] and not sig[:-1].any()
    assert piv[-1] < 100.5


def test_no_signal_without_volume():
    brk = np.append(_cup_path(), 101.0)
    o, h, l, c, v = _bars(brk)
    sig, _ = op.detect_cup(h, l, c, v, CFG, handle=True)
    assert not sig.any()


def test_v_shape_rejected():
    pre = np.full(60, 80.0)
    path = np.concatenate([pre, np.linspace(80, 100, 20), np.linspace(100, 78, 3), np.linspace(78, 99, 3)])
    path = np.append(path, 101.0)
    o, h, l, c, v = _bars(path, vol_spike_at=len(path) - 1)
    sig, _ = op.detect_cup(h, l, c, v, CFG, handle=False)
    assert not sig.any()


def test_double_bottom_and_no_lookahead():
    pre = np.full(60, 100.0)
    p = np.concatenate([pre, np.linspace(100, 80, 10), np.linspace(80, 95, 15), np.linspace(95, 79.0, 15),
                        np.linspace(79.0, 90, 6)])
    p = np.append(p, 96.0)
    o, h, l, c, v = _bars(p, vol_spike_at=len(p) - 1)
    sig, piv = op.detect_double_bottom(h, l, c, v, CFG)
    assert sig[-1]
    # truncating the future must not change earlier bars
    sig2, _ = op.detect_double_bottom(h[:-1], l[:-1], c[:-1], v[:-1], CFG)
    assert (sig2 == sig[:-1]).all()


def test_pattern_signals_has_both_directions_and_tags():
    o, h, l, c, v = _bars(np.append(_cup_path(), [101.0, 101.5]), vol_spike_at=len(_cup_path()))
    rs = np.full(len(c), 90.0)
    out = op.pattern_signals(o, h, l, c, v, rs, CFG, (0.05, 0.10), ("none", "80"))
    assert any(k[0] == "oneil_cup_handle" and k[2] == "long" for k in out)
    assert out[("oneil_cup_handle", "breakout", "long", 0.1, "qual1")].any()


def test_base_stage_flags_third_base():
    s = np.zeros(300, bool)
    s[[10, 100, 200]] = True
    assert list(op.base_stage(s)[[10, 100, 200]]) == [1, 2, 3]
    assert not op.quality_ok(s)[200]
