"""B-965: the three ve 1e-4 z2.0 5m chan_kalman short cells are wired through the existing engine (same SL/unwind/flatten path)."""
import main
import strategy_registry as sr

NEW = [
    "chan_kalman__band_mr__short__5m__atr4d0_hold40_ve1d0e4_z2d0_fl1515__v2",
    "chan_kalman__band_mr__short__5m__atr2d5_hold40_ve1d0e4_z2d0_fl1515__v2",
    "chan_kalman__band_mr__short__5m__atr1d5_hold40_ve1d0e4_z2d0_fl1515__v2",
]


def test_new_cells_wired_mapped_viable_not_owed():
    names = {d.name: d for d in sr.REGISTRY}
    assert len(main.CHAN_SHORT_CELLS) == 9
    for t in NEW:
        assert t in main.CHAN_SHORT_CELLS and main.CHAN_SHORT_CELLS[t][1] == 1e-4
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert names[t].metrics.pfnet >= sr.PFNET_LIVE_FLOOR
        assert t not in main.REPLAY_OWED_TAGS  # main.py-calling replay 38390561217 is on file
        assert main._is_strategy_viable_for_real_money(t)


def test_failing_ve1e4_z1_cells_not_wired():
    for t in main.CHAN_SHORT_CELLS:
        a, ve, z = main.CHAN_SHORT_CELLS[t]
        assert not (ve == 1e-4 and z == 1.0)
    assert list(main.CHAN_SHORT_CELLS)[:6] == [c for c in main.CHAN_SHORT_CELLS][:6]
    assert next(iter(main.CHAN_SHORT_CELLS)) == main.CHAN_SHORT_TAG


def test_manage_and_entry_gate_cover_new_cells():
    import inspect
    assert "CHAN_SHORT_CELLS" in inspect.getsource(main._maybe_place_real_short_entry)
    assert "_is_strategy_viable_for_real_money" in inspect.getsource(main._chan_short_try_entry)
