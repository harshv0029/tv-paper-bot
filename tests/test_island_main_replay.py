"""B-881: the island main.py replay driver runs on synthetic symbols and covers every ISLAND_ALL_TAGS tag once."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import island_main_replay as ir  # noqa: E402
import main as m  # noqa: E402


def test_every_tag_in_exactly_one_chunk():
    seen = []
    for c in ir.CHUNKS:
        seen += ir.tags_for_chunk(m, c)
    assert sorted(seen) == sorted(m.ISLAND_ALL_TAGS)
    assert len(seen) == len(set(seen))


def test_replay_synthetic_symbols_all_tags():
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    tags = list(m.ISLAND_ALL_TAGS)
    split = ir.make_split_ts("", 0.6)
    total = {t: 0 for t in tags}
    for seed in (1, 2, 3):
        df = ir.synthetic_frame(seed)
        res = ir.replay_symbol(m, df, tags, cost, split)
        assert set(res) == set(tags)
        for t, trs in res.items():
            total[t] += len(trs)
            for tr in trs:
                assert tr["held"] >= 0 and abs(tr["gross"] - tr["net"] - cost) < 1e-12
    nonovl = "reversal__island_none__long__1d__atr1d5_within8__nonovl__v2"
    assert total[nonovl] > 0, "synthetic islands should fire the real detector"
    assert total[nonovl.replace("nonovl", "segis")] + total[nonovl.replace("nonovl", "segoos")] == total[nonovl]
    v1 = "reversal__island_none__long__1d__atr1d5_within8__v1"
    assert total[v1] >= total[nonovl]


def test_run_and_merge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("CHUNK", "nonovl")
    monkeypatch.chdir(tmp_path)
    ir.run()
    out = ir.merge(str(tmp_path / "out"), str(tmp_path / "all.json"))
    assert out["rows"] and all(r["chunk"] == "nonovl" for r in out["rows"])
    assert {"n", "win_pct", "pfnet", "pfgross", "avg_held_hours", "exit_reasons"} <= set(out["rows"][0]["metrics"])
