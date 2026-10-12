import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import portfolio_ledger_research as L  # noqa: E402


def test_long_add_after_stop_to_breakeven():
    r = L.pyramid_position(1, 100, 95, 40, 10000, [(105, 10, 100)])  # first-unit risk 200 = 2%
    assert r["accepted"] and r["stop"] == 100


def test_add_with_stop_still_below_cost_rejected():
    r = L.pyramid_position(1, 100, 95, 40, 10000, [(105, 10, 96)])
    assert r["rejected"][0][2] == "not_breakeven"


def test_short_mirror_and_no_average_down():
    r = L.pyramid_position(-1, 100, 105, 40, 10000, [(104, 10, 105)])
    assert r["rejected"][0][2] == "average_down"
    r = L.pyramid_position(-1, 100, 105, 40, 10000, [(95, 10, 100)])
    assert r["accepted"] and r["stop"] == 100


def test_risk_cap_and_oversized_first():
    r = L.pyramid_position(1, 100, 95, 20, 10000, [(105, 400, 96.5)])
    assert r["rejected"] and r["rejected"][0][2] in ("risk_cap", "not_breakeven")
    r = L.pyramid_position(1, 100, 95, 20, 10000, [(110, 1000, 105)])
    assert r["rejected"][0][2] == "risk_cap"
    with pytest.raises(ValueError):
        L.pyramid_position(1, 100, 95, 100, 10000, [])


def test_worst_first_long_and_short():
    pos = [dict(id="a", side=1, qty=1, entry=100, mark=110, margin=10),
           dict(id="b", side=1, qty=1, entry=100, mark=90, margin=10),
           dict(id="c", side=-1, qty=1, entry=100, mark=95, margin=10)]
    assert L.liquidate_worst_first(pos, 15) == ["b", "c"]
    assert L.liquidate_worst_first(pos, 0) == []


def test_margin_call_exits_worst_first_and_noop():
    ps = [{"id": "a", "side": 1, "qty": 10, "entry": 100, "mark": 90, "margin": 500},
          {"id": "b", "side": -1, "qty": 10, "entry": 100, "mark": 90, "margin": 500}]
    assert L.margin_call_exit(ps, 10000, 1000, 900) == []
    assert L.margin_call_exit(ps, 10000, 500, 900) == ["a"]


def test_correlation_screen_blocks_correlated():
    base = [float(i % 7) for i in range(40)]
    r = {"A": base, "B": [x * 2 for x in base], "C": [float((i * 3) % 5) for i in range(40)]}
    out = L.correlation_screen(r, ["B", "C", "Z"], ["A"], max_corr=0.9)
    assert "B" not in out and "Z" in out
