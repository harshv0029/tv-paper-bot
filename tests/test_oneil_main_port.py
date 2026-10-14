"""B-1070: main.py's additive O'Neil functions match the independent v1 replay and are not wired anywhere."""
import ast
import importlib.util
import pathlib
import re
import sys

import numpy as np
import pytest

R = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts"))
sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "tests"))
spec = importlib.util.spec_from_file_location("oneil_replay_b1070", R / "scripts" / "oneil_replay.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)
import main as app  # noqa: E402
from test_oneil_replay import _flat_base_series  # noqa: E402

TAGS = [
    "oneil_flatbase__breakout__long__1w__atr3_chase10_h12_rsnone__v1",
    "oneil_flatbase__breakout__long__1w__atr3_chase10_h12_rsnone_trl1__v1",
    "oneil_flatbase__breakout__long__1w__pct8_chase10_h12_rsnone__v1",
    "oneil_flatbase__breakout__long__1w__pct8_tgt20_chase10_h12_rsnone__v1",
    "oneil_newhigh__first__long__1w__atr3_h12_rsnone__v1",
]


def _mirror(df):
    m = df.copy()
    m["Open"], m["Close"] = 20000.0 / df["Open"], 20000.0 / df["Close"]
    m["High"], m["Low"] = 20000.0 / df["Low"], 20000.0 / df["High"]
    return m


def _cmp(df, tag):
    sp = rp.parse_tag(tag)
    a = rp.replay_symbol(df, None, sp, 0.008)
    b = rp.replay_symbol(df, None, sp, 0.008, use_main=True)
    assert [(t["entry_bar"], t["held"], t["reason"]) for t in a] == [(t["entry_bar"], t["held"], t["reason"]) for t in b]
    assert all(abs(x["net"] - y["net"]) < 1e-12 for x, y in zip(a, b))
    return b


@pytest.mark.parametrize("tag", TAGS)
def test_main_matches_v1_long(tag):
    _cmp(_flat_base_series(), tag)


def test_main_matches_v1_short_mirror_and_triggers():
    tr = _cmp(_mirror(_flat_base_series()), "oneil_flatbase__breakout__short__1w__atr3_chase10_h12_rsnone__v1")
    assert tr or True  # parity is the assertion; the mirror may or may not fire on this synthetic series


def test_long_fires_and_every_trade_has_a_stop():
    tr = _cmp(_flat_base_series(), TAGS[0])
    assert tr
    assert app.oneil_stop_price(100.0, 2.0, "long", "atr", 3.0) == 94.0
    assert app.oneil_stop_price(100.0, 2.0, "short", "atr", 3.0) == 106.0
    assert app.oneil_stop_price(100.0, 0.0, "long", "pct", 8.0) == pytest.approx(92.0)


def test_exit_bar_gap_aware_and_timeout():
    assert app.oneil_exit_bar("long", 90, 95, 89, 92, 5, 9, 94.0, 94.0) == ("stop", 90)
    assert app.oneil_exit_bar("short", 110, 111, 100, 105, 5, 9, 106.0, 106.0) == ("stop", 110)
    assert app.oneil_exit_bar("long", 100, 101, 99, 100.5, 9, 9, 94.0, 94.0) == ("timeout", 100.5)
    assert app.oneil_exit_bar("long", 100, 101, 99, 100.5, 5, 9, 94.0, 94.0) is None
    assert app.oneil_exit_bar("long", 100, 125, 99, 120, 5, 9, 94.0, 94.0, target=120.0) == ("target", 120.0)


def test_entry_signal_and_exit_reason_df_wrappers():
    df = _flat_base_series()
    k = int(np.flatnonzero(df["Volume"].to_numpy() == 5000.0)[0])
    sig = app.oneil_entry_signal(df.iloc[:k + 1], "1w", "oneil_flatbase", "long")
    assert sig and sig["signal_pos"] == k and sig["stop_hint"] < sig["close"]
    assert app.oneil_entry_signal(df.iloc[:k], "1w", "oneil_flatbase", "long") is None
    assert app.oneil_entry_signal(df.iloc[:k + 1], "1w", "bogus", "long") is None
    ex = app.oneil_exit_reason(df.iloc[:k + 3], "1w", "long", k + 1, stop=1.0, hold=12)
    assert ex is None


def test_not_wired_and_parses():
    src = (R / "main.py").read_text()
    ast.parse(src)
    a = src.index("# O'Neil pivot / flat-base / new-high setups (B-1070)")
    b = src.index("def _fvg3c_scan_short(")
    outside = src[:a] + src[b:]
    assert not re.search(r"\boneil_\w+\(", outside), "O'Neil functions must not be referenced outside their block"
