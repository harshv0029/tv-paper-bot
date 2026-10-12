import json
import os
import sys
import types

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import elder_indicators_research as er
import universe_pin as up

UNIVERSE = [f"S{i:02d}.NS" for i in range(20)]


def _df(seed):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, 200))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6},
                        index=pd.date_range("2022-01-01", periods=200))


def _fake_main(fail):
    m = types.ModuleType("main")
    m._load_nse_universe_from_file = lambda: list(UNIVERSE)
    m.fetch_ohlc = lambda s, p, i: None if s in fail else _df(int(s[1:3]))
    return m


def _args(tmp, pin="", shard=0, nshards=2, tol=0.002):
    return types.SimpleNamespace(family="x", shard=shard, nshards=nshards, interval="1d", period="5y",
                                 out=str(tmp), pin_file=pin, pin_tolerance=tol)


@pytest.fixture
def fake_run(monkeypatch):
    def run_symbol(df, family, interval, aggs):  # deterministic per-symbol contribution
        aggs["sum"] = aggs.get("sum", 0) + float(df["Close"].iloc[-1])
    monkeypatch.setattr(er, "run_symbol", run_symbol)


def _shards(tmp, fail, pin="", tol=0.002):
    sys.modules["main"] = _fake_main(fail)
    try:
        for sh in (0, 1):
            er._main_shard(_args(tmp, pin, shard=sh, tol=tol))
    finally:
        del sys.modules["main"]
    return [json.load(open(tmp / f"x_{sh}.json")) for sh in (0, 1)]


def test_pinned_rerun_identical_despite_flaky_fetch(tmp_path, fake_run):
    pa = _shards(tmp_path / "a", fail={"S03.NS"})  # first run: one symbol failed to fetch
    fetched = up.merge_fetched(pa)
    assert "S03.NS" not in fetched and len(fetched) == 19
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps({"fetched_symbols": fetched}))
    pb = _shards(tmp_path / "b", fail=set(), pin=str(pin))  # S03 would fetch now, but is outside the pin
    assert up.merge_fetched(pb) == fetched
    assert sum(p["aggs"]["sum"] for p in pa) == pytest.approx(sum(p["aggs"]["sum"] for p in pb), rel=1e-12)
    assert all(p["pinned"] for p in pb)


def test_unpinned_runs_drift(tmp_path, fake_run):
    pa = _shards(tmp_path / "a", fail={"S03.NS"})
    pb = _shards(tmp_path / "b", fail=set())
    assert up.merge_fetched(pa) != up.merge_fetched(pb)


def test_pinned_drift_beyond_tolerance_fails_loudly(tmp_path, fake_run):
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps(UNIVERSE))
    with pytest.raises(up.PinDriftError):
        _shards(tmp_path / "c", fail={"S01.NS", "S03.NS", "S05.NS"}, pin=str(pin), tol=0.002)
    p = _shards(tmp_path / "d", fail={"S01.NS"}, pin=str(pin), tol=0.5)
    assert any("S01.NS" in x["pin_missing"] for x in p)


def test_load_pin_formats_and_empty(tmp_path):
    f = tmp_path / "l.json"
    f.write_text(json.dumps(["B", "A", "A"]))
    assert up.load_pin(str(f)) == ["A", "B"]
    assert up.load_pin("") is None
    f.write_text(json.dumps({"fetched_symbols": []}))
    with pytest.raises(up.PinDriftError):
        up.load_pin(str(f))
    assert up.select_universe(["Z", "Y"], None) == ["Y", "Z"]
