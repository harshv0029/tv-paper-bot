"""B-1493: oneil_shakeout plus3 pm1 (1w) swing cell trails at peak-LTP 0.5R (run 42025478119: 2.979 fixed -> 3.181)."""
import inspect

import pandas as pd
import pytest

import main

TAG = "oneil_shakeout__plus3__long__1w__atr3_h26_pm1_srcmain__nonovl__v2"
TRAILED = "oneil_shakeout__plus3__long__1w__atr3_h26_pm1_rsbandfloor_srcmain_trailltp0d5r__nonovl__v2"


def test_cell_wired_at_half_r_with_its_validated_tag():
    assert main.SWING_PEAK_LTP_TRAIL_CELLS[TAG] == (0.5, TRAILED)
    assert TAG in main.ONEIL_SWING_CELLS  # still entered by the O'Neil scan, exit fn unchanged
    assert main._swing_is_trailing_tag(TAG) and main._sl_kind("swing", TAG) == "Trail"
    assert "0.5R" in main._SWING_SL_RULES[TAG]
    import strategy_registry as r
    m = {s.name: s.metrics for s in r.REGISTRY}
    assert m[TRAILED].pfnet > m[TAG.replace("_srcmain", "_rsbandfloor_srcmain")].pfnet + 0.02
    assert m[TRAILED].n_trades >= 30


def test_other_oneil_cells_stay_fixed():
    for t in main.ONEIL_SWING_CELLS:
        if t != TAG:
            assert t not in main.SWING_PEAK_LTP_TRAIL_CELLS, t


def test_trail_level_and_walk_on_daily_bars():
    assert main._swing_strategy_stop_level(TAG, 90, 2.0, 120, entry_price=100, peak_ltp=120) == pytest.approx(115.0)
    idx = pd.bdate_range("2026-10-01", periods=4)
    df = pd.DataFrame({"Open": [100, 100, 110, 109], "High": [200, 112, 111, 110],
                       "Low": [99, 99, 108, 100], "Close": [100, 110, 109, 101]}, index=idx)
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 90.0, 0.5, "long")
    assert w["hit_idx"] == 3 and w["hit_price"] == pytest.approx(107.0)


def test_trail_walk_runs_before_the_oneil_exit_branch():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert src.index("pos[\"strategy\"] in SWING_PEAK_LTP_TRAIL_CELLS") < src.index("pos[\"strategy\"] in ONEIL_SWING_CELLS")
