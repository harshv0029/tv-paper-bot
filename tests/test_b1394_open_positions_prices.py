"""B-1394: /real-open-positions prices rows concurrently within one time budget, live-feed LTP first."""
import sys
import time
import types
from unittest.mock import patch

import pandas as pd

import main


def _feed(ticks):
    m = types.ModuleType("kotak_live_feed")
    m.get_live_ticks = lambda: ticks
    return m


def test_live_tick_used_without_network():
    with patch.dict(sys.modules, {"kotak_live_feed": _feed({"A.NS": {"ltp": 10.5}})}), \
         patch.object(main, "fetch_ohlc", side_effect=AssertionError("no fetch needed")):
        assert main._open_positions_prices(["A.NS"], {}) == {"A.NS": 10.5}


def test_slow_fetch_is_cut_by_budget_and_others_still_priced():
    def fake(sym, *_a, **_k):
        if sym == "SLOW.NS":
            time.sleep(3)
        return pd.DataFrame({"Close": [1.0, 2.0]})
    t0 = time.time()
    with patch.dict(sys.modules, {"kotak_live_feed": _feed({})}), patch.object(main, "fetch_ohlc", side_effect=fake):
        out = main._open_positions_prices(["SLOW.NS", "B.NS", "C.NS"], {}, budget_s=0.5)
    assert time.time() - t0 < 2
    assert out == {"B.NS": 2.0, "C.NS": 2.0}


def test_fetch_error_leaves_symbol_unpriced():
    with patch.dict(sys.modules, {"kotak_live_feed": _feed({})}), \
         patch.object(main, "fetch_ohlc", side_effect=RuntimeError("yahoo down")):
        assert main._open_positions_prices(["X.NS"], {}) == {}
