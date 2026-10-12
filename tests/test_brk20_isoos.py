"""brk20 IS/OOS split harness (B-798): bucketing, cutoff, verdict, exact merge. Synthetic data only."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import brk20_isoos as I  # noqa: E402
import brk20_replay as R  # noqa: E402
import main


def test_cutoff_fraction_and_explicit():
    today = dt.date(2026, 10, 12)
    assert I.split_cutoff("1d", today=today, frac=0.6) == (today - dt.timedelta(days=730)).isoformat()
    assert I.split_cutoff("1h", today=today, frac="") == (today - dt.timedelta(days=292)).isoformat()
    assert I.split_cutoff("1d", split_date="2024-05-01") == "2024-05-01"


def test_bucket_by_entry_date_including_intraday_stamps():
    tr = [{"entry_date": "2024-04-30"}, {"entry_date": "2024-05-01 09:15:00"}, {"entry_date": "2025-01-01"}]
    ins, oos = I.bucket(tr, "2024-05-01")
    assert len(ins) == 1 and len(oos) == 2


def test_dated_replay_matches_plain_replay_on_synthetic():
    df = R.synthetic_frame(3)
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    for d in ("long", "short"):
        a = R.replay_symbol(main, df, d, 3.0, 3.0, 1.0, cost)
        b = I.replay_symbol_dated(main, df, d, 3.0, 3.0, 1.0, cost)
        assert [(t["net"], t["held"], t["reason"]) for t in a] == [(t["net"], t["held"], t["reason"]) for t in b]
        assert all("entry_date" in t for t in b)


def test_is_plus_oos_equals_pooled():
    df = R.synthetic_frame(5)
    cost = main.ROUND_TRIP_COST_PCT / 100.0
    tr = I.replay_symbol_dated(main, df, "long", 3.0, 3.0, None, cost)
    ins, oos = I.bucket(tr, str(df["Date"].iloc[400]))
    pooled, a, b = R.agg_new(), R.agg_new(), R.agg_new()
    R.agg_add(pooled, tr)
    R.agg_add(a, ins)
    R.agg_add(b, oos)
    R.agg_merge(a, b)
    assert a["n"] == pooled["n"] == len(tr)
    assert abs(a["sum_net"] - pooled["sum_net"]) < 1e-12


def test_verdict_flags():
    ok = {"n": 100, "pfnet": 1.5}
    thin = {"n": 5, "pfnet": 9.0}
    low = {"n": 100, "pfnet": 0.9}
    assert I.verdict(ok, ok, 1.1)["holds_out_of_sample"]
    assert not I.verdict(ok, thin, 1.1)["holds_out_of_sample"]
    assert not I.verdict(ok, low, 1.1)["holds_out_of_sample"]
    assert not I.verdict(ok, thin, 1.1)["oos_n_enough"]


def test_run_and_merge_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("INTERVAL", "1d")
    monkeypatch.setenv("DIRECTION", "short")
    monkeypatch.setenv("CELLS", json.dumps([{"atr": 3, "rr": 3, "be": None}]))
    monkeypatch.setenv("SPLIT_DATE", "2022-06-01")
    monkeypatch.setenv("SYMBOL_LIMIT", "3")
    I.run()
    out = I.merge("out")
    r = out["rows"][0]
    assert r["cutoff"] == "2022-06-01" and r["tag"].endswith("atr3_rr3__v1")
    assert "holds_out_of_sample" in r["derived"]
