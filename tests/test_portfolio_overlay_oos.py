import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
import portfolio_overlay_oos as o  # noqa: E402
import portfolio_overlay_research as p  # noqa: E402
from test_elder_indicators_research import synth  # noqa: E402


def _tr(day, ret=0.05, rf=0.02, price=10.0):
    return [day * 86400, day * 86400 + 5 * 86400, ret, rf, 3, price, 1e6, "x"]


def test_parses():
    ast.parse(open(o.__file__).read())


def test_split_is_chronological_and_disjoint():
    tr = [_tr(d) for d in range(100)]
    w, cut = o.windows(tr, 60)
    assert len(w["is"]) == 60 and len(w["oos"]) == 40
    assert max(t[0] for t in w["is"]) < cut <= min(t[0] for t in w["oos"])


def test_overlays_filter():
    tr = [_tr(1, price=10), _tr(2, price=50), _tr(3, rf=0.09, price=10)]
    assert len(o.overlay_trades("pricebucket", tr)) == 2
    assert all(t[3] <= 0.04 for t in o.overlay_trades("passtrade4", tr))


def test_merge_end_to_end_and_tags(tmp_path):
    st = {}
    for s in (1, 2, 3, 4):
        p.collect_symbol(synth(900, s), st)
    json.dump({"fetched": 4, "universe": 4, "streams": st}, open(tmp_path / "collect_0.json", "w"))
    res = o.merge(str(tmp_path), str(tmp_path / "r.json"), 60)
    tags = [r["tag"] for r in res["rows"]]
    assert tags and len(tags) == len(set(tags))
    assert all(re.fullmatch(r"[a-z0-9_]+", t) and t.startswith("pfoos__") for t in tags)
    assert {r["window"] for r in res["rows"]} == {"full", "is", "oos"}
    assert {r["direction"] for r in res["rows"]} <= {"long", "short"}
    for r in res["rows"]:
        for k in ("n", "pfnet", "pf_gross", "win_pct", "avg_hold_bars", "universe"):
            assert k in r
    for r in res["rows"]:
        if r["overlay"] == "base" and r["window"] == "full":
            parts = sum(x["n"] for x in res["rows"] if x["overlay"] == "base" and x["direction"] == r["direction"]
                        and x["atr"] == r["atr"] and x["window"] in ("is", "oos"))
            assert parts == r["n"]
