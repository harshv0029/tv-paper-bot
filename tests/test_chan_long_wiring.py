"""B-960: chan_kalman band LONG 5m wired into the buy engine (9 cells, PFnet-descending cascade)."""
import pandas as pd

import main
import strategy_registry as sr

EXPECTED = [
    "chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z1d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z1d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr4d0_hold40_ve10d0e4_z2d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr1d5_hold40_ve10d0e4_z1d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr2d5_hold40_ve10d0e4_z2d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr4d0_hold40_ve1d0e4_z2d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr2d5_hold40_ve1d0e4_z2d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr1d5_hold40_ve10d0e4_z2d0_fl1515__v2",
    "chan_kalman__band__long__5m__atr1d5_hold40_ve1d0e4_z2d0_fl1515__v2",
]


def test_nine_cells_in_pfnet_order_and_failing_cells_absent():
    assert list(main.CHAN_LONG_CELLS) == EXPECTED
    assert not any("ve1d0e4_z1d0" in t for t in main.CHAN_LONG_CELLS)
    pf = {d.name: d.metrics.pfnet for d in sr.REGISTRY if d.metrics}
    vals = [pf[t] for t in EXPECTED]
    assert vals == sorted(vals, reverse=True)
    assert vals[0] == 1.827


def test_registry_metrics_and_mapping():
    by = {d.name: d for d in sr.REGISTRY}
    for t, (n, w, h) in zip(EXPECTED, [(6149, 47.2, 0.491), (6218, 46.5, 0.461), (434, 49.5, 0.737), (6323, 44.6, 0.422),
                                       (444, 48.2, 0.707), (10150, 41.0, 0.26), (10169, 40.6, 0.251),
                                       (451, 43.7, 0.611), (10184, 39.7, 0.237)]):
        m = by[t].metrics
        assert (m.n_trades, m.win_rate_pct, m.avg_held_hrs) == (n, w, h)
        assert sr.TradeCategory.BUY in by[t].categories
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert t not in main.REPLAY_OWED_TAGS


def test_manage_stop_and_flatten():
    ts = pd.DatetimeIndex(["2026-10-14 05:00"], tz="UTC")
    df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]})
    for tag in main.CHAN_LONG_CELLS:
        row = {"stop_loss": 90.0, "entry_price": 100.0, "entry_ts": 0, "strategy": tag}
        assert main._chan_long_manage(row, df, ts, "5m", 600, 89.0, False) == "stop_hit"
        assert main._chan_long_manage(row, df, ts, "5m", 15 * 60 + 10, 101.0, False) == "flatten_1515"
        assert main._chan_long_manage(row, df, ts, "5m", 600, 101.0, True) == "daily_loss_cap_hit"


def test_ownership_and_cutoffs():
    assert not set(main.CHAN_LONG_CELLS) & set(main.CHAN_SHORT_CELLS)
    assert all("__long__" in t for t in main.CHAN_LONG_CELLS)
    assert main.CHAN_LONG_ENTRY_CUTOFF_MIN == 15 * 60
    assert main.CHAN_LONG_FLATTEN_START_MIN == 15 * 60 + 10


def test_wiring_sources_present():
    import inspect
    assert "_chan_long_try_entry" in inspect.getsource(main._auto_signal_core)
    assert "CHAN_LONG_CELLS" in inspect.getsource(main._auto_signal_core)
    src = inspect.getsource(main._maybe_place_real_entry)
    assert "entry_sl_failed_unwind" in src and "CHAN_LONG_ENTRY_CUTOFF_MIN" in src
    assert "_chan_long_flatten_due" in (inspect.getsource(main._scheduler_tick) + inspect.getsource(main._scan_equity_symbol_sync))


def test_stack_change_flips_next_entry_gate():
    import json
    import os
    import tempfile
    import time
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    tag = EXPECTED[0]

    def _stack(label):
        with main.get_db() as c:
            c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (?,?,?)",
                      (time.time(), label, json.dumps([])))
            c.commit()

    _stack("pfnet(1.1-100), min(30), maxhold(any)")
    assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is True
    _stack("pfnet(1.9-100), min(30), maxhold(any)")  # no cell reaches 1.9: next entry must be refused with no reload call
    assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is False
    _stack("pfnet(1.1-100), min(30), maxhold(any)")
    assert main._is_strategy_viable_for_real_money(tag, check_switch=False) is True


def test_real_entry_rechecks_stack_before_order():
    import inspect
    src = inspect.getsource(main._maybe_place_real_entry)
    assert src.index("_load_viable_overrides()") < src.index("place_real_entry(kotak_symbol")


def test_b962_fresh_stack_read_precedes_every_real_entry_order():
    import re
    src = open("main.py").read()
    for call in ("place_real_short_entry(kotak_symbol, qty, ltp)", "place_real_entry(kotak_symbol, qty, ltp)"):
        for m in re.finditer(re.escape("kotak_real_orders." + call), src):
            window = src[max(0, m.start() - 1500):m.start()]
            assert "_load_viable_overrides()" in window, call


def test_swing_long_unwinds_when_entry_sl_fails():
    src = open("main.py").read()
    i = src.index("unwinding at market (no trade without SL)")
    assert 'reason="entry_sl_failed_unwind"' in src[i:i + 900]
