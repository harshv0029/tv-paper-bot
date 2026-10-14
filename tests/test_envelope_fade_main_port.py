"""B-1130: main.py envelope 5% fade 1h port matches pattern_lab's rule, always has a stop, is not wired."""
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


def _df(n=120, seed=3, drop=False):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.004, n))
    if drop:
        c[-1] = c[-22:-1].mean() * 0.93
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    return pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=1000.0),
                        index=pd.date_range("2026-01-01", periods=n, freq="h"))


def test_rule_matches_pattern_lab_on_every_prefix():
    df = _df(drop=True)
    o, h, l, c, v = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close", "Volume"))
    lg, sh = pl.r_bands(o, h, l, c, v)["envelope_0d05_fade"]
    for t in range(40, len(df)):
        sub = df.iloc[:t + 1]
        assert app.envelope_fade_fires(sub, "long") == bool(lg[t])
        assert app.envelope_fade_fires(sub, "short") == bool(sh[t])
    assert lg[-1]


def test_signal_always_has_stop_and_is_directional():
    df = _df(drop=True)
    tag = "envelope__0d05_fade__long__1h__atr6_h30__v1"
    sig = app.envelope_fade_entry_signal(df, tag)
    assert sig and 0 < sig["stop_loss"] < sig["entry_price"]
    assert abs(sig["entry_price"] - sig["stop_loss"] - 6 * sig["atr_at_entry"]) < 1e-9
    assert app.envelope_fade_entry_signal(df, tag.replace("long", "short")) is None
    assert app.envelope_fade_entry_signal(df, "envelope__0d05_fade__long__1h__atrnone_h30__v1") is None
    assert app.envelope_fade_entry_signal(_df(), tag) is None
    assert len(app.ENVELOPE_1H_CELLS) == 12 and all(k > 0 for _d, k, _h in app.ENVELOPE_1H_CELLS.values())


def test_exit_stop_gap_and_timeout():
    df = _df(40)
    e = 30
    low = float(df["Low"].iloc[e + 1])
    assert app.envelope_fade_exit_reason(df.iloc[:e + 2], "long", e, low + 1.0, 30) == ("envelope_stop_loss", low + 1.0)
    assert app.envelope_fade_exit_reason(df.iloc[:e + 2], "long", e, 1.0, 30) is None
    assert app.envelope_fade_exit_reason(df.iloc[:e + 4], "long", e, 1.0, 3)[0] == "envelope_max_hold_timeout"
    hi = float(df["High"].iloc[e + 1])
    assert app.envelope_fade_exit_reason(df.iloc[:e + 2], "short", e, hi - 1.0, 30)[0] == "envelope_stop_loss"


def test_not_wired_and_parses():
    src = (R / "main.py").read_text()
    ast.parse(src)
    a = src.index("# ---- B-1130 envelope 5% fade")
    b = src.index("def chan_kalman_band_long_entry_signal(")
    # B-1264 (2026-10-14): the two long cells that cleared the floor in the main.py replay ARE now wired, in their own block only.
    c = src.index("# ---- B-1264: envelope 5% fade LONG 1h")
    d = src.index("def _run_long_swing_1h_pass(")
    assert not re.search(r"\benvelope_fade_\w+\(|\bENVELOPE_1H_CELLS\b", (src[:a] + src[b:c] + src[d:]))
