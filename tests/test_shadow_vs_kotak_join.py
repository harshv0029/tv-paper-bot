import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import shadow_vs_kotak_join as j  # noqa: E402


def fill(sym, side, q, px, t, st="complete"):
    return {"trdSym": sym, "trnsTp": side, "fldQty": str(q), "avgPrc": str(px), "ordSt": st, "ordDtTm": t}


def sh(tag, sym, d, taken=1, **kw):
    r = {"strategy_tag": tag, "symbol": sym, "direction": d, "taken": taken, "day": "2026-10-07", "hard_gate": 0, "reason": "x"}
    r.update(kw)
    return r


def test_symbol_norm():
    assert j.norm_symbol("RELIANCE.NS") == j.norm_symbol("RELIANCE-EQ") == "RELIANCE"


def test_long_trip_net_after_cost_and_prediction():
    s = [sh("gap_and_go", "AAA.NS", "long", predicted_net_pct=2.0)]
    f = [fill("AAA-EQ", "B", 100, 100.0, "07-Oct-2026 09:20:00"), fill("AAA-EQ", "S", 100, 105.0, "08-Oct-2026 10:00:00")]
    r = j.join(s, f)
    t = r["tags"]["gap_and_go"]
    assert t["gross_inr"] == 500.0 and t["cost_inr"] == 80.0 and t["net_inr"] == 420.0
    assert t["win_pct"] == 100.0 and t["realised_net_pct_avg"] == 4.2
    assert t["realised_minus_predicted_pct"] == 2.2
    assert r["shadow_taken_without_kotak_roundtrip"]["gap_and_go"] == 0


def test_short_trip_and_partial_fifo_and_open_qty():
    s = [sh("range_short", "BBB.NS", "short")]
    f = [fill("BBB-EQ", "S", 10, 200.0, "07-Oct-2026 09:30:00"), fill("BBB-EQ", "B", 4, 210.0, "07-Oct-2026 11:00:00")]
    r = j.join(s, f)
    t = r["tags"]["range_short"]
    assert t["round_trips"] == 1 and t["gross_inr"] == -40.0 and t["win_pct"] == 0.0
    assert r["open_qty_by_symbol"] == {"BBB": 6}


def test_rejected_ignored_and_unattributed():
    f = [fill("CCC-EQ", "B", 5, 50.0, "07-Oct-2026 09:30:00", st="rejected"),
         fill("DDD-EQ", "B", 5, 50.0, "07-Oct-2026 09:30:00"), fill("DDD-EQ", "S", 5, 51.0, "07-Oct-2026 10:30:00")]
    r = j.join([], f)
    assert r["tags"] == {} and len(r["unattributed_kotak_roundtrips"]) == 1 and "CCC" not in r["open_qty_by_symbol"]


def test_ambiguous_tags_not_merged_and_skips_counted():
    s = [sh("a", "EEE.NS", "long"), sh("b", "EEE.NS", "long"),
         sh("a", "FFF.NS", "long", taken=0, hard_gate=1), sh("a", "FFF.NS", "long", taken=0)]
    f = [fill("EEE-EQ", "B", 1, 10.0, "07-Oct-2026 09:30:00"), fill("EEE-EQ", "S", 1, 11.0, "07-Oct-2026 10:30:00")]
    r = j.join(s, f)
    assert list(r["tags"]) == ["AMBIGUOUS"]
    assert r["shadow_skipped_by_tag"]["a"] == {"hard_gate": 1, "discretionary": 1}


def test_cli_roundtrip(tmp_path, capsys):
    sp, fp = tmp_path / "s.json", tmp_path / "f.json"
    sp.write_text(json.dumps([sh("t", "GGG.NS", "long")]))
    fp.write_text(json.dumps({"data": [fill("GGG-EQ", "B", 2, 10.0, "07-Oct-2026 09:30:00"),
                                       fill("GGG-EQ", "S", 2, 12.0, "07-Oct-2026 10:30:00")]}))
    assert j.main(["--shadow", str(sp), "--fills", str(fp)]) == 0
    assert json.loads(capsys.readouterr().out)["tags"]["t"]["round_trips"] == 1
