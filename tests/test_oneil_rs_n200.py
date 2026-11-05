"""B-1468: RS ranked inside the live swing watchlist - replay/main parity and the rsn200 tag param."""
import json
import os
import sys
import types

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import main  # noqa: E402
import oneil_ext_research as ox  # noqa: E402
import oneil_nonoverlap as on  # noqa: E402
import oneil_research as orx  # noqa: E402


def _closes(n_sym=12, n=700, freq="B", seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03", periods=n, freq=freq)
    data = {f"S{i}.NS": 100 * np.exp(np.cumsum(rng.normal(0.0005 * (i - 6), 0.02, n))) for i in range(n_sym)}
    df = pd.DataFrame(data, index=idx)
    df.iloc[:40, 2] = np.nan  # late lister
    df.iloc[300:305, 5] = np.nan  # gap
    return df


def test_main_rs_rank_equals_replay_rs_rank_1d_and_1w():
    for tf, freq in (("1d", "B"), ("1w", "W-FRI")):
        c = _closes(freq=freq)
        ref = orx.rs_rank_matrix(c, orx.CFG[tf]["rs_lb"])
        got = main.oneil_rs_rank_series(c, tf)
        pd.testing.assert_frame_equal(ref, got)
        got2 = main.oneil_rs_rank_series({s: c[s] for s in c.columns}, tf)
        pd.testing.assert_frame_equal(ref, got2)
        assert main.ONEIL_RS_LB[tf] == orx.CFG[tf]["rs_lb"]
        v = got.to_numpy()
        v = v[~np.isnan(v)]
        assert v.size and v.min() >= 1 and v.max() <= 99


def test_swing_pass_helper_skips_bad_frames_and_matches():
    c = _closes()
    frames = {s: pd.DataFrame({"Close": c[s], "Open": c[s]}) for s in c.columns}
    frames["BAD.NS"] = None
    frames["EMPTY.NS"] = pd.DataFrame()
    got = main.oneil_rs_rank_for_swing_pass(frames, "1d")
    pd.testing.assert_frame_equal(orx.rs_rank_matrix(c, 252), got)
    assert main.oneil_rs_rank_for_swing_pass({}, "1d").empty


def test_rsn200_tag_param_only_when_requested():
    spec = ("mainentry", "long", ("oneil_rsscreen", "top", "rs"), 1, 2.0)
    holds = orx.CFG["1d"]["holds"]
    t0, _ = on.cell_tag(spec, "1d", "long", ox.EX["1d"], holds)
    t1, _ = on.cell_tag(spec, "1d", "long", ox.EX["1d"], holds, "200")
    assert t0 == "oneil_rsscreen__top__long__1d__atr2_h40_rs90_srcmain__v1"
    assert t1 == "oneil_rsscreen__top__long__1d__atr2_h40_rs90_rsn200_srcmain__v1"
    for sp in on.CELL_SETS["pivot_tight"][:1] + on.CELL_SETS["leaders"][:1] + on.CELL_SETS["exit_six"][:1]:
        a, _ = on.cell_tag(sp, "1d", sp[1], ox.EX["1d"], holds)
        b, _ = on.cell_tag(sp, "1d", sp[1], ox.EX["1d"], holds, "200")
        assert "rsn" not in a and "rsn200" in b


def test_n200_shard_fetches_whole_watchlist_trades_own_slice(monkeypatch, tmp_path):
    wl = [f"W{i}.NS" for i in range(9)]
    n = 600
    idx = pd.date_range("2021-01-04", periods=n, freq="B")
    rng = np.random.default_rng(1)

    def mk():
        c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
        return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)

    frames = {s: mk() for s in wl}
    requested = []

    def fake_download(tick, **kw):
        if isinstance(tick, str):
            raise RuntimeError("no index")
        requested.extend(tick)
        return pd.concat({s: frames[s] for s in tick}, axis=1)

    def no_full():
        raise AssertionError("full universe must not be loaded for rs_universe=n200")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=fake_download))
    monkeypatch.setattr(main, "SWING_WATCHLIST", wl)
    monkeypatch.setattr(main, "_load_nse_universe_from_file", no_full)
    seen = []

    def spy(df, idx_series, rs_series, *a, **_kw):
        seen.append((df.name, a[-1], int(rs_series.notna().sum())))

    monkeypatch.setattr(on, "run_symbol", spy)
    rc = on.main(["run", "--tf", "1d", "--shard", "1", "--nshards", "3", "--cells", "ext_main",
                  "--rs_universe", "n200", "--out", str(tmp_path)])
    assert rc == 0
    assert sorted(requested) == sorted(wl)
    assert sorted(s for s, _, _ in seen) == sorted(wl[1::3])
    assert all(r == "200" and k > 0 for _, r, k in seen)
    with open(tmp_path / "oneil_nonovl_1d_1.json") as f:
        meta = json.load(f)
    assert meta["rs_universe"] == "n200" and meta["rs_population"] == 9 and meta["fetched"] == 3
