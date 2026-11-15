"""B-1604: PAIRED_DAILY_CLOSE=1 books each intraday chan_gap candidate twice, at the live 15:15 exit and at the 15:30
daily close, with identical entry and stop walk, so the exit-time effect is measured on one candidate set."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_gap_tf_sweep as sw  # noqa: E402


def test_xd_tag_distinct_grammar():
    a, b = sw.tag_for("short", "1h", 1.5), sw.tag_for("short", "1h", 1.5, xd=True)
    assert a != b and b == "chan_gap__short_on_gap__short__1h__atr1d5_top10_xd1530__v1"
    assert len(b.split("__")) == 6


def _run(tmp_path, monkeypatch, paired, interval="1h"):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.chdir(tmp_path)
    for k, v in {"DIRECTION": "short", "INTERVAL": interval, "SYMBOL_LIMIT": "4", "PAIRED_DAILY_CLOSE": paired}.items():
        monkeypatch.setenv(k, v)
    sw.run()
    return json.load(open(tmp_path / "out" / f"chan_gap_tf_short_{interval}_s0.json"))["candidates"]


def test_paired_twins_share_stops_and_differ_only_on_close(tmp_path, monkeypatch):
    cands = _run(tmp_path, monkeypatch, "1")
    twins = 0
    for c in cands:
        for tag, (reason, px) in c["res"].items():
            if tag.endswith("_xd1530__v1"):
                continue
            x = c["res"].get(tag.replace("__v1", "_xd1530__v1"))
            if x is None:
                continue
            twins += 1
            if reason == "stop":
                assert x == [reason, px]
            else:
                assert x[0] == "close"
    assert twins > 0


def test_unpaired_has_no_twins(tmp_path, monkeypatch):
    cands = _run(tmp_path, monkeypatch, "")
    assert not any(t.endswith("_xd1530__v1") for c in cands for t in c["res"])


def test_paired_ignored_on_1d(tmp_path, monkeypatch):
    cands = _run(tmp_path, monkeypatch, "1", "1d")
    assert not any(t.endswith("_xd1530__v1") for c in cands for t in c["res"])


def test_rawd_tag_grammar():
    from scripts import chan_gap_tf_sweep as cg
    assert cg.tag_for("short", "1h", 2.5, raw=True) == "chan_gap__short_on_gap__short__1h__atr2d5_top10_rawd__v1"
    assert cg.tag_for("short", "1h", 2.5, raw=True, xd=True) == "chan_gap__short_on_gap__short__1h__atr2d5_top10_rawd_xd1530__v1"


def test_rawd_env_switches_tags_and_records_dopen_ratio(monkeypatch):
    import main as m
    from scripts import chan_gap_tf_sweep as cg
    monkeypatch.setenv("RAW_DAILY", "1")
    daily, intr = cg.synthetic_pair(3, "1h")
    out = cg.day_candidates(m, daily, intr, "short", "1h", (2.5,)) + cg.day_candidates(m, daily, intr, "long", "1h", (2.5,))
    for _d, sig, res in out:
        assert all("_rawd" in t for t in res)
        assert sig["dopen_ratio"] is None or sig["dopen_ratio"] > 0
