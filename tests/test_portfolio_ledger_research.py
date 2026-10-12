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


def _tr(i, side, ed, xd, entry, stop, marks):
    return {"id": i, "side": side, "entry_date": ed, "exit_date": xd, "entry": entry, "stop": stop, "marks": marks}


def test_marked_ledger_refuses_no_stop_and_runs_long_short():
    dates = ["d1", "d2", "d3"]
    ts = [_tr("a", 1, "d1", "d3", 100, 95, {"d3": 110}), _tr("b", -1, "d1", "d3", 100, 105, {"d3": 90}),
          _tr("c", 1, "d1", "d3", 100, None, {"d3": 200})]
    r = L.simulate_marked_ledger(ts, dates)
    assert r["n_refused"] == 1 and r["n_closed"] == 2 and r["final_equity"] > 1.0


def test_marked_ledger_worst_first_make_room_only_for_loser():
    dates = ["d1", "d2", "d3"]
    ts = [_tr("w", 1, "d1", "d3", 100, 90, {"d2": 105}), _tr("l", 1, "d1", "d3", 100, 90, {"d2": 95}),
          _tr("n", 1, "d2", "d3", 50, 45, {})]
    r = L.simulate_marked_ledger(ts, dates, max_open=2, margin_exit=False)
    assert r["closes"][0][0] == "l" and r["closes"][0][3] == "worst_first_make_room"
    winners = [_tr("w1", 1, "d1", "d3", 100, 90, {"d2": 105}), _tr("w2", 1, "d1", "d3", 100, 90, {"d2": 106}),
               _tr("n", 1, "d2", "d3", 50, 45, {})]
    r2 = L.simulate_marked_ledger(winners, dates, max_open=2, margin_exit=False)
    assert all(c[3] != "worst_first_make_room" for c in r2["closes"])


def test_marked_ledger_margin_call_exits_worst_never_tops_up():
    dates = ["d1", "d2", "d3"]
    ts = [_tr("x", 1, "d1", "d3", 100, 50, {"d2": 60}), _tr("y", 1, "d1", "d3", 100, 50, {"d2": 120})]
    r = L.simulate_marked_ledger(ts, dates, margin_frac=5.0, risk_frac_of_eq=0.5)
    assert r["closes"][0][0] == "x" and r["closes"][0][3] == "margin_call_exit"


def test_correlation_screen_blocks_correlated():
    base = [float(i % 7) for i in range(40)]
    r = {"A": base, "B": [x * 2 for x in base], "C": [float((i * 3) % 5) for i in range(40)]}
    out = L.correlation_screen(r, ["B", "C", "Z"], ["A"], max_corr=0.9)
    assert "B" not in out and "Z" in out


def test_ledger_trades_from_collect_feeds_marked_ledger():
    streams = {"b|long|2": [[1, 3, 0.1, 0.05, 2, 100.0, 1e6, "x", "A"]],
               "b|short|2": [[1, 3, 0.1, 0.05, 2, 100.0, 1e6, "x", "B"], [1, 3, 0.1, 0.0, 2, 100.0, 1e6, "x", "C"]]}
    paths = {"b|long|2": [[[1, 2, 3], [100.0, 105.0, 110.0]]],
             "b|short|2": [[[1, 2, 3], [100.0, 95.0, 90.0]], [[1, 2, 3], [100.0, 95.0, 90.0]]]}
    lt = L.ledger_trades_from_collect(streams, paths, "b|long|2")
    assert lt[0]["side"] == 1 and abs(lt[0]["stop"] - 95.0) < 1e-9 and lt[0]["marks"][2] == 105.0
    st = L.ledger_trades_from_collect(streams, paths, "b|short|2")
    assert st[0]["side"] == -1 and abs(st[0]["stop"] - 105.0) < 1e-9 and st[1]["stop"] is None
    r = L.simulate_marked_ledger(lt + st, [1, 2, 3])
    assert r["n_refused"] == 1 and r["n_closed"] == 2 and r["final_equity"] > 1.0
