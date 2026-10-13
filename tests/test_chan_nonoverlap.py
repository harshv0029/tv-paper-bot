import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_nonoverlap as no
import chan_research as cr


def test_tag_naming():
    old = "chan_tsm__lookback_sign__long__1d__atr1d5_hold5_lb20__v1"
    assert no.nonovl_tag(old) == "chan_tsm__lookback_sign__long__1d__atr1d5_hold5_lb20__nonovl__v2"
    assert no.nonovl_tag(old) != old


def test_fifo_filter_drops_overlaps_and_keeps_order():
    tr = [(1, 5, 9, 0.01, "max_hold"), (1, 3, 7, 0.02, "stop"), (-1, 8, 12, 0.03, "max_hold"), (1, 10, 14, 0.0, "stop")]
    kept = no.fifo_filter(tr)
    assert [(t[1], t[2]) for t in kept] == [(3, 7), (8, 12)]
    assert not no.has_overlap(kept) and no.has_overlap(tr)


def test_cell_trades_are_non_overlapping_and_reduce_signals():
    n = 60
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.5, n))
    o, h, l = c.copy(), c + 1, c - 1
    atr = np.full(n, 2.0)
    sig = np.zeros(n)
    sig[5:50] = 1                      # a signal every bar
    kept, raw = no.cell_trades(o, h, l, c, atr, sig, 4.0, 5, None, None)
    assert raw > len(kept) > 0 and not no.has_overlap(kept)


def test_matches_chan_simulate_on_ts_cell():
    n = 80
    rng = np.random.default_rng(2)
    c = 100 + np.cumsum(rng.normal(0, 1.0, n))
    o, h, l = c.copy(), c + 1, c - 1
    atr = np.full(n, 2.0)
    sig = cr.sig_tsm(c, 10)
    ref = cr.simulate(o, h, l, c, atr, sig, 1.5, 5)
    kept, _ = no.cell_trades(o, h, l, c, atr, sig, 1.5, 5, None, None, gap=1)
    assert [(t[0], t[1], t[2]) for t in kept] == [(t[0], t[1], t[2]) for t in ref]


def test_agg_metrics_and_merge():
    a, b = no.Agg(), no.Agg()
    a.add([0.1, -0.05], [0.108, -0.042], [2, 3], {"stop": 1, "max_hold": 1})
    b.add([0.05], [0.058], [4], {"max_hold": 1})
    a.merge_dict(b.to_dict())
    m = a.metrics()
    assert m["n"] == 3 and m["win_pct"] == 66.7 and abs(m["pfnet"] - 3.0) < 1e-9
    assert m["avg_hold_bars"] == 3.0 and m["exit_reasons"] == {"stop": 1, "max_hold": 2}
    assert no.Agg().metrics() is None


def test_strict_fifo_allows_at_least_as_many_trades_as_simulate():
    n = 80
    rng = np.random.default_rng(2)
    c = 100 + np.cumsum(rng.normal(0, 1.0, n))
    o, h, l = c.copy(), c + 1, c - 1
    atr = np.full(n, 2.0)
    sig = cr.sig_tsm(c, 10)
    strict, _ = no.cell_trades(o, h, l, c, atr, sig, 1.5, 5, None, None)
    ref = cr.simulate(o, h, l, c, atr, sig, 1.5, 5)
    assert len(strict) >= len(ref) and not no.has_overlap(strict)


def test_4h_uses_session_resample_helper_b991():
    import inspect
    import pandas as pd
    assert no.resample_1h_to_4h.__module__ == "resample_4h"
    assert "resample_1h_to_4h(df)" in inspect.getsource(no.run)
    idx = pd.DatetimeIndex(["2026-10-12 09:15", "2026-10-12 10:15", "2026-10-12 11:15", "2026-10-12 12:15",
                            "2026-10-12 13:15", "2026-10-12 14:15", "2026-10-12 15:15"])
    df = pd.DataFrame({"Open": range(7), "High": range(1, 8), "Low": range(7), "Close": range(7), "Volume": 1}, index=idx)
    out = no.resample_1h_to_4h(df)
    assert len(out) == 2 and out["Volume"].tolist() == [4, 3]


def test_workflow_accepts_4h_b991():
    y = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "chan-nonoverlap.yml")).read()
    assert "intervals" in y and "fromJSON" in y
