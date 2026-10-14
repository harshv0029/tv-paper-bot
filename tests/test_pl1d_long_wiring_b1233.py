"""B-1233: pl1d LONG cells (run 38506928246, main.py replay) registered as own _mr rows; gate derives open; stop always attached."""
import inspect
import json
import os

import main
import strategy_registry as sr

_REG = {d.name: d for d in sr.REGISTRY}
EXPECT = {
    "gap__runaway__long__1d__atr4_h20__v1": ("gap__runaway_mr__long__1d__atr4_h20__v1", 12898, 1.2025, 1.379, 46.19, 116.5),
    "starc__fade_full__long__1d__atr2d5_h20__v1": ("starc__fade_full_mr__long__1d__atr2d5_h20__v1", 9093, 1.2215, 1.452, 43.19, 90.4),
}


def test_mr_rows_keep_every_metric_and_research_rows_untouched():
    for tag, (mr, n, net, gross, win, hold) in EXPECT.items():
        assert tag in _REG and mr in _REG
        m = _REG[mr].metrics
        assert m.n_trades == n and abs(m.pfnet - net) < 5e-4 and abs(m.pfgross - gross) < 5e-4
        assert abs(m.win_rate_pct - win) < 1e-6 and abs(m.avg_held_hrs - hold) < 1e-6
        assert sr.TradeCategory.SWING in _REG[mr].categories
        assert "run 38506928246" in m.run_ref and "pl1d_stop_loss" in _REG[mr].evidence and "pl1d_max_hold_timeout" in _REG[mr].evidence
        assert _REG[mr].is_viable()


def test_gate_open_derived_from_json_and_mapping_1to1():
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "backtest_data", "pl1d_long_main_replay_run_38506928246.json")
    assert {r["tag"] for r in json.load(open(f))["rows"]} == set(EXPECT)
    for tag in EXPECT:
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
        assert tag not in main.REPLAY_OWED_TAGS
        assert main._is_strategy_viable_for_real_money(tag, check_switch=False)


def test_stop_always_attached_live():
    assert "stop_loss" in inspect.getsource(main.pl1d_long_entry_signal)
    src = inspect.getsource(main._pl1d_try_entry)
    assert "initial_stop_loss" in src and "_maybe_place_real_swing_entry" in src
    assert "entry_sl_failed_unwind" in inspect.getsource(main._maybe_place_real_swing_entry)
