"""B-985: swingminrr brk20_gatetarget SHORT 1h atr3_rr4 beside the gate cell (paper-only; real leg stays fail-closed)."""
from contextlib import closing

import main
import strategy_registry as sr
from tests.test_swingminrr_gate_short_1h_wiring import _bars, _breakdown_frame, _fresh_db

GT = "swingminrr__brk20_gatetarget__short__1h__atr3_rr4__v1"
G = "swingminrr__brk20_gate__short__1h__atr3_rr4__v1"


def test_cells_registered_mapped_owed_and_closed(monkeypatch):
    # No View 1 override for these tags here (another test in the same process may leave one loaded).
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", set())
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: sr.VIABLE_OVERRIDES)
    names = {s.name for s in sr.REGISTRY}
    assert set(main.SWINGMINRR_SHORT_1H_CELLS) == {G, GT}
    for t in (G, GT):
        assert t in names and main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t in main.REPLAY_FAILED_TAGS  # B-1396c: main.py replay 40575438117 below floor
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is False
    assert main.SWINGMINRR_SHORT_1H_CELLS[GT] == 4.0 and main.SWINGMINRR_SHORT_1H_CELLS[G] is None
    assert main.SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED is False


def test_exit_target_stop_first_and_timeout():
    stop, tgt = 110.0, 80.0
    r = main.swingminrr_gate_short_exit_reason(_bars([(100, 101, 79, 90)]), stop, target=tgt)
    assert r == ("target_hit", 80.0)
    r = main.swingminrr_gate_short_exit_reason(_bars([(100, 111, 79, 90)]), stop, target=tgt)
    assert r[0] == "stop_hit"                      # stop tested before the target inside a bar
    r = main.swingminrr_gate_short_exit_reason(_bars([(100, 101, 95, 99)] * 31), stop, target=tgt)
    assert r == ("max_hold_timeout", 99.0)
    # the gate cell (no target) ignores a low through the would-be target
    assert main.swingminrr_gate_short_exit_reason(_bars([(100, 101, 79, 90)]), stop) is None


def test_pos_exit_uses_target_only_for_gatetarget_cell():
    bars = _bars([(100, 101, 70, 90)])
    for tag, want in ((GT, "short_swing_target_hit"), (G, None)):
        pos = {"strategy": tag, "entry_day": "2024-01-31 15:15", "entry_price": 100.0, "initial_stop_loss": 105.0}
        res = main._swingminrr_gate_short_exit(bars, pos)  # risk 5 -> target 80
        assert (res[0] if res else None) == want


def test_try_entry_falls_back_to_gate_cell_when_none_viable():
    _fresh_db()
    with closing(main.get_db()) as conn:
        tag = main._swingminrr_gate_short_try_entry(conn, "ZZTEST.NS", _breakdown_frame(), 1_000_000, 0.01, "2024-02-01", 1.0)
        assert tag == G
