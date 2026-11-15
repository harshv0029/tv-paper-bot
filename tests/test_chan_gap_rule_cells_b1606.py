"""B-1606: RULE_CELLS=1 replays the live long cap5/fit5 stop-rule cells in the chan_gap sweep, with the stop taken from
the real main.chan_gap_stop_for, so they can be re-measured on raw prices with the live 15:15 exit."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import chan_gap_tf_sweep as sw  # noqa: E402


def test_rule_tag_grammar():
    assert sw.rule_tag("1h", "cap5", raw=True) == "chan_gap__buy_on_gap__long__1h__atr4d0cap5_top10_rawd__v1"
    assert sw.rule_tag("1h", "fit5", raw=True, ic=True) == "chan_gap__buy_on_gap__long__1h__fit5_top10_rawd_ic1530__v1"
    assert all(len(sw.rule_tag("1h", r).split("__")) == 6 for r in ("cap5", "fit5"))


def test_rule_live_tags_exist_in_main():
    import main
    for t in sw.RULE_LIVE_TAGS.values():
        assert t in main.CHAN_GAP_LONG_CELLS


def _run(tmp_path, monkeypatch, direction):
    monkeypatch.chdir(tmp_path)
    for k, v in {"SYNTHETIC": "1", "DIRECTION": direction, "INTERVAL": "1h", "SYMBOL_LIMIT": "4",
                 "RULE_CELLS": "1"}.items():
        monkeypatch.setenv(k, v)
    sw.run()
    return json.load(open(tmp_path / "out" / f"chan_gap_tf_{direction}_1h_s0.json"))["candidates"]


def test_rule_cells_emitted_for_long(tmp_path, monkeypatch):
    cands = _run(tmp_path, monkeypatch, "long")
    tags = {t for c in cands for t in c["res"]}
    assert sw.rule_tag("1h", "cap5") in tags
    # cap5 never trades more often than the base candidate set, and fit5 can skip days
    n_cap = sum(sw.rule_tag("1h", "cap5") in c["res"] for c in cands)
    n_fit = sum(sw.rule_tag("1h", "fit5") in c["res"] for c in cands)
    assert n_cap == len(cands) and n_fit <= n_cap


def test_rule_cells_off_for_short(tmp_path, monkeypatch):
    cands = _run(tmp_path, monkeypatch, "short")
    assert not any("cap5" in t or "fit5" in t for c in cands for t in c["res"])
