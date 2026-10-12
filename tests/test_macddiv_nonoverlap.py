import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import elder_indicators_research as er
import macddiv_nonoverlap as no


def test_tag_naming():
    old = "macddiv__line_any__long__1h__atr1d5_w5__v1"
    assert no.nonovl_tag(old) == "macddiv__line_any__long__1h__atr1d5_w5__nonovl__v2"
    assert er.make_tag("macddiv", "line_any", "long", "1h", {"w": 5, "atr": 1.5}) == old


def test_fifo_filter_strict():
    tr = [{"entry_i": 5, "exit_i": 9}, {"entry_i": 3, "exit_i": 7}, {"entry_i": 8, "exit_i": 12},
          {"entry_i": 10, "exit_i": 14}]
    kept = no.fifo_filter(tr)
    assert [(t["entry_i"], t["exit_i"]) for t in kept] == [(3, 7), (8, 12)]
    assert no.has_overlap(tr) and not no.has_overlap(kept)


def test_cell_trades_non_overlapping_and_match_simulate():
    n = 80
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 0.8, n))
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1.0},
                      index=pd.date_range("2026-01-01", periods=n, freq="h"))
    entry = np.zeros(n, bool)
    entry[10:60] = True
    z = np.zeros(n, bool)
    sig = {"long": entry, "short": z, "exit_long": z, "exit_short": z,
           "long_lvl": np.full(n, np.nan), "short_lvl": np.full(n, np.nan)}
    kept, raw = no.cell_trades(df, sig, "long", 3.0)
    assert raw > len(kept) > 0 and not no.has_overlap(kept)
    # er.simulate already enforces one position per symbol; the independent+FIFO path must agree with it
    ref = er.simulate(df, sig, "long", 3.0, {})
    assert [round(t["ret"], 10) for t in kept] == [round(t["ret"], 10) for t in ref]
    assert [t["hold"] for t in kept] == [t["hold"] for t in ref]
