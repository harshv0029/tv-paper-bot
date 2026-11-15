"""B-1597: main.tri_desc_entry_signal is the exact port of elder_patterns_research.d_triangle(kind="desc") (long on df,
short on the reciprocal mirror flip(df)), always carries a stop on the correct side, is not wired into any live entry
path, and the main.py-function replay driver + workflow run end to end on synthetic data."""
import os
import re
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import elder_patterns_research as ep  # noqa: E402
import tri_desc_main_replay as tr  # noqa: E402
import main as m  # noqa: E402


def _frames():
    return [tr.synthetic_frame(s, n=400) for s in (1, 2, 3)]


@pytest.mark.parametrize("direction", ["long", "short"])
@pytest.mark.parametrize("vol", [False, True])
def test_detector_parity_vs_harness(direction, vol):
    fired = 0
    for df in _frames():
        src = df if direction == "long" else ep.flip(df)
        ent, _ex = ep.d_triangle(src, kind="desc", vol=vol, look=m.TRIDESC_LOOK, tol=m.TRIDESC_TOL)
        ent = ent.fillna(False).to_numpy(dtype=bool)
        got = np.array([m.tri_desc_signal_on_last_bar(df.iloc[:k + 1], direction, vol) for k in range(len(df))])
        assert (got == ent).all(), np.flatnonzero(got != ent)[:10]
        fired += int(ent.sum())
    assert fired > 0, "synthetic triangles should fire the harness detector"


def test_tags_grammar_and_count():
    pat = re.compile(r"^consol__tri_desc__(long|short)__(1d|4h|1h|15m)__atr(1d5|2|3)_vol[01]__v2$")
    assert len(m.TRIDESC_ALL_TAGS) == 2 * 4 * 3 * 2 == len(set(m.TRIDESC_ALL_TAGS))
    assert all(pat.match(t) for t in m.TRIDESC_ALL_TAGS)


def test_stop_always_set_and_on_correct_side():
    seen = {"long": 0, "short": 0}
    for df in _frames():
        for tag in [t for t in m.TRIDESC_ALL_TAGS if "__1d__" in t]:
            d, _tf, am, _v = m.tridesc_params_of_tag(tag)
            for k in range(30, len(df)):
                s = m.tri_desc_entry_signal(df.iloc[:k + 1], tag)
                if not s:
                    continue
                seen[d] += 1
                assert s["direction"] == d and s["stop_loss"] is not None
                if d == "long":
                    assert 0 < s["stop_loss"] < s["entry_price"]
                else:
                    assert s["stop_loss"] > s["entry_price"]
                assert abs(abs(s["entry_price"] - s["stop_loss"]) - am * s["atr_at_entry"]) < 1e-9
    assert seen["long"] > 0 and seen["short"] > 0
    assert m.tri_desc_entry_signal(_frames()[0], "not_a_tag") is None


def test_not_wired_into_live_entry_paths():
    src = open(os.path.join(ROOT, "main.py")).read()
    uses = [mm.start() for mm in re.finditer(r"tri_desc_entry_signal\(|TRIDESC_ALL_TAGS", src)]
    defs = src.index("def tri_desc_entry_signal(")
    assert all(abs(u - defs) < 6000 for u in uses), "tri_desc must stay a pure port (no scheduler/engine hook)"


def test_replay_synthetic_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("INTERVAL", "1d")
    monkeypatch.setenv("SYMBOL_LIMIT", "2")
    monkeypatch.chdir(tmp_path)
    res = tr.run()
    tags = tr.tags_for_interval(m, "1d")
    assert set(res["cells"]) == set(tags) | {tr.trail_tag(t, s) for t in tags for s in tr.TRAIL_RULES}
    out = tr.merge(str(tmp_path / "out"), str(tmp_path / "all.json"))
    assert {"tag", "n", "pfnet", "pf_gross", "win_pct", "avg_hold_bars", "exit_reasons"} <= set(out["rows"][0])
    assert sum(r["n"] for r in out["rows"]) > 0
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    for trs in tr.replay_symbol(m, tr.synthetic_frame(5, n=300), tags[:2], cost).values():
        for t in trs:
            assert t["held"] >= 0 and abs(t["gross"] - t["net"] - cost) < 1e-12


def test_workflow_references_script():
    wf = open(os.path.join(ROOT, ".github", "workflows", "tri-desc-main-replay.yml")).read()
    assert "scripts/tri_desc_main_replay.py run" in wf and "scripts/tri_desc_main_replay.py merge" in wf
    assert "interval" in wf and "period" in wf
