"""B-1190: main.py cup 3C-cheat 1h LONG port matches pattern_lab's base_cup_cheat_3c rule, always has a stop, not wired."""
import ast
import pathlib
import re
import sys

import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "scripts"))
import main as app  # noqa: E402
import pattern_lab as pl  # noqa: E402


def _cup(seed, n_pre=30, tail=10):
    """Left rim ~100, drop to ~80, recovery to ~96, tight pause, then a break close."""
    rng = np.random.default_rng(seed)
    path = np.r_[
        np.full(n_pre, 100.0),
        np.full(20, 100.0),
        np.linspace(100, 80, 15),
        np.linspace(80, 96, 14),
        np.full(11, 96.0),
        [98.0],
        np.full(tail, 98.0),
    ]
    c = path * (1 + rng.normal(0, 0.002, len(path)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.003, np.minimum(o, c) * 0.997
    return pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=1000.0),
                        index=pd.date_range("2025-01-01", periods=len(c), freq="h"))


def _lab(df):
    o, h, l, c, v = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
    return pl.r_bases(o, h, l, c, v)["base_cup_cheat_3c"][0]


def test_rule_matches_pattern_lab_on_every_bar():
    fired = 0
    for seed in range(12):
        df = _cup(seed)
        lab = _lab(df)
        for t in range(70, len(df)):
            got = app.cup_cheat_3c_fires(df.iloc[:t + 1])
            assert got == bool(lab[t]), (seed, t)
            fired += got
    assert fired > 0, "synthetic cup never triggered: the parity test would be vacuous"
    rng = np.random.default_rng(5)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    o = np.r_[c[0], c[:-1]]
    r = pd.DataFrame(dict(Open=o, High=np.maximum(o, c) * 1.002, Low=np.minimum(o, c) * 0.998, Close=c, Volume=1000.0))
    lab = _lab(r)
    assert all(app.cup_cheat_3c_fires(r.iloc[:t + 1]) == bool(lab[t]) for t in range(70, 300))


def test_signal_always_has_stop():
    for seed in range(12):
        df = _cup(seed)
        for t in range(70, len(df)):
            if app.cup_cheat_3c_fires(df.iloc[:t + 1]):
                sig = app.cup_cheat_3c_entry_signal(df.iloc[:t + 1], "base__cup_cheat_3c__long__1h__atr4_h30__v1")
                assert sig and 0 < sig["stop_loss"] < sig["entry_price"]
                assert abs(sig["entry_price"] - sig["stop_loss"] - 4 * sig["atr_at_entry"]) < 1e-9
                assert app.cup_cheat_3c_entry_signal(df.iloc[:t + 1], "base__cup_cheat_3c__long__1h__atrnone_h30__v1") is None
                return
    raise AssertionError("no signal")


def test_cells_and_short_guard():
    assert len(app.CUP_CHEAT_1H_CELLS) == 9 and all("__long__" in t for t in app.CUP_CHEAT_1H_CELLS)
    assert app.cup_cheat_3c_entry_signal(_cup(0).iloc[:40], "base__cup_cheat_3c__long__1h__atr4_h30__v1") is None


def test_exit_stop_gap_and_timeout():
    df = _cup(0)
    e = 60
    lo = float(df["Low"].iloc[e + 1])
    assert app.cup_cheat_3c_exit_reason(df.iloc[:e + 2], e, lo + 1.0, 30) == ("cup_cheat_stop_loss", lo + 1.0)
    assert app.cup_cheat_3c_exit_reason(df.iloc[:e + 2], e, 1.0, 30) is None
    assert app.cup_cheat_3c_exit_reason(df.iloc[:e + 4], e, 1.0, 3)[0] == "cup_cheat_max_hold_timeout"


def test_parses_and_only_b1266_wiring_references_port():
    src = (R / "main.py").read_text()
    ast.parse(src)
    a = src.index("# ---- B-1190 Minervini cup")
    b = src.index("# ---- B-1130 envelope 5% fade")
    # B-1266 intentionally wires two PFnet>=1 cells (tests/test_cup_cheat_wiring_b1266.py); the references must stay in the
    # B-1266 block, never in the research-port-free parts of the swing scan elsewhere
    outside = src[:a] + src[b:]
    c = outside.index("# ---- B-1266")
    d = outside.index("def _run_long_swing_1h_pass(")
    assert not re.search(r"\bcup_cheat_3c_\w+\(|\bCUP_CHEAT_1H_CELLS\b", outside[:c] + outside[d:])
