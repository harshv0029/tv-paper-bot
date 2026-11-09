"""B-1483: O'Neil replay with the RS rank computed inside the live NIFTY-200 swing population (RS_UNIVERSE=n200)."""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "scripts"))
_spec = importlib.util.spec_from_file_location("oneil_replay_b1483", R / "scripts" / "oneil_replay.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def test_rsn_param_inserted_in_key_order_and_parses():
    t = "oneil_cup_handle__breakout__long__1d__atr2_chase10_h60_rs80__v2"
    assert rp.add_rsn_param(t) == "oneil_cup_handle__breakout__long__1d__atr2_chase10_h60_rs80_rsn200__v2"
    q = "oneil_cup_handle__breakout__long__1d__atr2_chase10_h60_rsqual1__v2"
    assert rp.add_rsn_param(q) == "oneil_cup_handle__breakout__long__1d__atr2_chase10_h60_rsn200_rsqual1__v2"
    tr = "oneil_double_bottom__breakout__long__1d__chase5_h40_rsnone_trl3__v2"
    out = rp.add_rsn_param(tr)
    assert out.endswith("_rsnone_rsn200_trl3__v2") or out.endswith("_rsn200_rsnone_trl3__v2")
    assert rp.add_rsn_param(rp.add_rsn_param(t)) == rp.add_rsn_param(t)  # idempotent
    sp = rp.parse_tag(rp.add_rsn_param(t))
    assert sp["rs"] == "80" and sp["hold"] == 60  # the new param never changes the replayed rule


def test_n200_fetches_whole_watchlist_but_trades_only_the_shard_slice():
    class App:
        SWING_WATCHLIST = [f"S{i:02d}.NS" for i in range(10)]

        @staticmethod
        def _load_nse_universe_from_file():
            return [f"F{i:03d}.NS" for i in range(30)]

    fetch, trade = rp.rs_universe_split(App, 1, 3, "n200")
    assert fetch == sorted(App.SWING_WATCHLIST) and trade == fetch[1::3]
    fetch_f, trade_f = rp.rs_universe_split(App, 1, 3, "full")
    assert fetch_f == trade_f == sorted(App._load_nse_universe_from_file())[1::3]
    # union of the n200 shards' trade slices is the whole watchlist, with no overlap
    allt = sum((rp.rs_universe_split(App, s, 3, "n200")[1] for s in range(3)), [])
    assert sorted(allt) == sorted(App.SWING_WATCHLIST) and len(set(allt)) == len(allt)


def test_run_specs_trade_set_limits_traded_symbols_not_rs_population(monkeypatch):
    seen = []

    def fake_replay(df, rs_series, sp, cost, slip, use_main, mode, cache):
        seen.append(rs_series.name)
        return []

    monkeypatch.setattr(rp, "replay_symbol", fake_replay)
    idx = pd.bdate_range("2022-01-03", periods=300)
    data = {s: pd.DataFrame({"Open": np.linspace(10, 20 + k, 300), "High": np.linspace(10.5, 21 + k, 300),
                             "Low": np.linspace(9.5, 19 + k, 300), "Close": np.linspace(10, 20 + k, 300),
                             "Volume": np.full(300, 1e5)}, index=idx) for k, s in enumerate(["A.NS", "B.NS", "C.NS"])}
    spec = dict(rp.parse_tag("oneil_pivot__breakout__long__1d__atr3_chase10_h40_rs80__v2"), band_cap="off")
    rp.run_specs([spec], data, 0.008, trade_set={"B.NS"})
    assert seen == ["B.NS"]
