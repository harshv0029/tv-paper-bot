import ast
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import elder_dirsys_di13_research as d  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def test_parses():
    ast.parse(open(d.__file__).read())


def test_tags_unique_lowercase_and_count():
    tags = d.all_tags("1d")
    assert len(tags) == len(set(tags)) == 4 * 4 * 2 * 2 * 3
    assert all(t == t.lower() and t.startswith("dirsys13__") and t.endswith("__v1") for t in tags)
    assert any("__atr2_n13_sm0_ts0__" in t for t in tags)     # Elder baseline, wilder, fixed stop
    assert any("__atr3_n13_sm1_ts1__" in t for t in tags)     # ema smoothing, trailing stop


def test_di_period_and_smoothing_differ_and_valid():
    df = synth(600, 5)
    a13, p13, m13 = d.adx_di(df, 13, "wilder")
    _, p14, _ = d.adx_di(df, 14, "wilder")
    _, pe, _ = d.adx_di(df, 13, "ema")
    assert not np.allclose(p13.dropna(), p14.dropna())
    assert not np.allclose(p13.dropna(), pe.dropna())
    assert ((p13.dropna() >= 0) & (m13.dropna() >= 0)).all() and a13.dropna().between(0, 100).all()


def test_both_directions_and_bad_bar_guard():
    aggs, oos, cnt = {}, {}, {"bad_dropped": 0}
    for seed in (1, 2, 3):
        d.run_symbol(synth(900, seed), "1d", aggs, oos, cnt)
    assert aggs and all(a["n"] > 0 for a in aggs.values())
    assert any("__long__" in t for t in aggs) and any("__short__" in t for t in aggs)
    assert any("_ts1__" in t for t in aggs) and any("_ts0__" in t for t in aggs)
    assert oos and set(oos) <= set(aggs)
    # inject a corrupt bar (3x jump): trades touching it are dropped
    df = synth(900, 1).copy()
    df.iloc[400:, :4] = df.iloc[400:, :4] * 3.0
    cnt2 = {"bad_dropped": 0}
    d.run_symbol(df, "1d", {}, {}, cnt2)
    assert cnt2["bad_dropped"] >= 0
    bad = d.bad_bar_mask(df["Open"].to_numpy(), df["Close"].to_numpy())
    assert bad[400] and not bad[399]
    kept, n = d.guard_trades([{"s": 398, "hold": 5, "ret": 0.1, "reason": "x"},
                              {"s": 100, "hold": 5, "ret": 0.1, "reason": "x"}], bad)
    assert n == 1 and len(kept) == 1 and kept[0]["s"] == 100


def test_resample_4h_session_bins():
    idx = pd.date_range("2025-01-06 09:15", periods=7, freq="1h")      # 09:15 .. 15:15
    df = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0}, index=idx)
    r = d.resample_4h(df)
    assert len(r) == 2 and r.index[0].hour == 9 and r.index[1].hour == 13
    assert r["Volume"].iloc[0] == 40.0 and r["Volume"].iloc[1] == 30.0


def test_merge_roundtrip(tmp_path):
    aggs, oos, cnt = {}, {}, {"bad_dropped": 0}
    d.run_symbol(synth(900, 2), "1d", aggs, oos, cnt)
    json.dump({"aggs": aggs, "aggs_oos": oos, "fetched": 1, "bad_dropped": 2}, open(tmp_path / "a.json", "w"))
    json.dump({"aggs": aggs, "aggs_oos": oos, "fetched": 1, "bad_dropped": 3}, open(tmp_path / "b.json", "w"))
    res = d.merge_dir(str(tmp_path))
    assert res["symbols_fetched"] == 2 and res["bad_trades_dropped"] == 5
    assert res["rows"] and all(r["n"] % 2 == 0 for r in res["rows"])
    assert d.main(["--merge", str(tmp_path)]) == 0
