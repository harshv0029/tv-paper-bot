"""WIRE-NEXT batch: 19 tags (island v1/gap05/segis/segoos cells + swingminrr minervini_vcp LONG 1d atr1d5) wired into
the live swing scan. Own tags, real ATR stop always attached, reasoned exits, no new kill switch, PFnet gate.
The port is NOT replayed through a main.py-calling replay (owed)."""
import csv
import inspect
import pathlib

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr
from tests.test_island_swing_wiring import _frame, _island, _after

CSV = pathlib.Path(__file__).resolve().parent.parent / "docs/backtest_data/wiring_final_binary_1844.csv"


def _csv_tags():
    with open(CSV) as f:
        return [r["tag"] for r in csv.DictReader(f) if r["basis"].startswith("WIRE-NEXT")]


def test_all_19_csv_tags_wired_mapped_viable_and_exit_covered(tmp_path, monkeypatch):
    # No explorer stack in this DB: the gate then follows the PFnet floor (an earlier test's stack must not leak in).
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    main.init_db()
    tags = _csv_tags()
    assert len(tags) == 19 and len(set(tags)) == 19
    covered = set(main.ISLAND_ALL_TAGS) | set(main.SWINGMINRR_TAGS)
    for t in tags:
        assert t in covered, t
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t  # own registry name, never merged
        assert main._is_strategy_viable_for_real_money(t, check_switch=False) is (t not in main.REPLAY_OWED_TAGS)  # replay-verified tags re-open (2026-10-12)
        assert t in main._SWING_SL_RULES
        assert next(s for s in sr.REGISTRY if s.name == t).metrics.pfnet >= sr.PFNET_LIVE_FLOOR


def test_island_gap05_signal_and_filter_mapping():
    df = _island()
    # large gaps relative to ATR: gap05 fires
    for t in main.ISLAND_GAP05_TAGS:
        sig = main.island_swing_entry_signal(df, t)
        if sig:
            assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 1.5 * sig["atr_at_entry"])
            assert sig["filter"] == "gap05"
    # every tag has a filter, and the three plain-filter families map consistently
    for t in main.ISLAND_ALL_TAGS:
        assert main._ISLAND_FILTER_OF_TAG[t] in ("none", "px20", "turn1cr", "gap05")
    assert main._ISLAND_FILTER_OF_TAG["reversal__island__long__1d__atr1d5_within8__v1"] == "none"
    assert main._ISLAND_FILTER_OF_TAG["reversal__island_turn1cr__long__1d__atr1d5_within8__segoos__v2"] == "turn1cr"


def test_gap05_requires_half_atr_gaps():
    df = _island()
    n = len(df)
    # wipe ATR down (tiny ranges) then a gap-up that clears the gap-down high by < 0.5 ATR must NOT fire gap05
    # but still fires the plain variant.
    assert main.island_bottom_signal_on_last_bar(df)
    d2 = df.copy()
    j = n - 1
    d2.iloc[j, d2.columns.get_loc("Low")] = 91.05   # Low > High[j-1]=91 and > gap-down high 90, margin 1.05
    d2.iloc[j, d2.columns.get_loc("High")] = 200.0  # huge range inflates ATR at j (a[j-1] unaffected)
    a = main._brk20_atr_series(d2["High"].to_numpy(float), d2["Low"].to_numpy(float), d2["Close"].to_numpy(float))
    needs = 0.5 * a[j - 1]
    fires05 = main.island_bottom_signal_on_last_bar(d2, min_gap_atr=0.5)
    assert fires05 == ((91.05 - 90.0) >= needs)
    assert main.island_bottom_signal_on_last_bar(d2) is True


def _vcp_df(n=120, base=100.0, room_high=None):
    c = np.full(n, base)
    h, l = c + 1.0, c - 1.0
    if room_high is not None:
        h[n - 30] = room_high
    return _frame(c.copy(), h, l, c)


def test_swingminrr_entry_gate_and_stop(monkeypatch):
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", lambda df, rs_percentile=None: {"entry_price": 1.0})
    near = _vcp_df()   # prior 60-bar high 101 vs px 100: room 1, risk 1.5 x ~2 = 3 -> every gate fails
    assert main.swingminrr_vcp_entry_signal(near, main.SWINGMINRR_BASE_TAG) is not None
    for t in main.SWINGMINRR_TAGS[:3]:
        assert main.swingminrr_vcp_entry_signal(near, t) is None
    sig = main.swingminrr_vcp_entry_signal(near, main.SWINGMINRR_BASE_TAG)
    assert sig["stop_loss"] == pytest.approx(sig["entry_price"] - 1.5 * sig["atr_at_entry"])
    far = _vcp_df(room_high=140.0)  # room 40 >= 4 x 3
    for t in main.SWINGMINRR_TAGS:
        assert main.swingminrr_vcp_entry_signal(far, t) is not None, t
    # no VCP signal -> never fires
    monkeypatch.setattr(main, "minervini_vcp_entry_signal", lambda df, rs_percentile=None: None)
    for t in main.SWINGMINRR_TAGS:
        assert main.swingminrr_vcp_entry_signal(far, t) is None
    assert main.swingminrr_vcp_entry_signal(far, "bogus") is None


def test_swingminrr_exit_adapter_stop_and_timeout():
    df = _vcp_df()
    day = df["Date"].iloc[-1]
    px = 100.0
    atr = 2.0
    stop = px - 1.5 * atr
    assert main._swingminrr_exit_adapter(df, day, stop, atr, px)[0] is None
    up = _after(df, [(px, px + 1, px - 0.5, px + 0.5)])
    assert main._swingminrr_exit_adapter(up, day, stop, atr, px)[0] is None
    hit = _after(df, [(px, px + 1, stop - 1, stop)])
    assert main._swingminrr_exit_adapter(hit, day, stop, atr, px)[0] == "swingminrr_stop_loss"
    # no EMA rule exit: falling closes above the stop do not exit before the 30-bar timeout
    fall = _after(df, [(px, px + 0.1, px - 0.3, px - 0.1 * (k + 1)) for k in range(10)])
    assert main._swingminrr_exit_adapter(fall, day, stop, atr, px)[0] is None
    flat = _after(df, [(px, px + 0.2, px - 0.2, px)] * 31)
    assert main._swingminrr_exit_adapter(flat, day, stop, atr, px)[0] == "swingminrr_max_hold_timeout"
    short = _after(df, [(px, px + 0.2, px - 0.2, px)] * 30)
    assert main._swingminrr_exit_adapter(short, day, stop, atr, px)[0] is None


def test_scan_wiring_no_new_switch_sl_attached_reasoned_exit():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert "_swingminrr_exit_adapter" in src and "ISLAND_ALL_TAGS" in src
    assert src.index("_swingminrr_try_entry") < src.index('"minervini_vcp_be3r"', src.index("_swingminrr_try_entry"))
    assert "_maybe_place_real_swing_exit(conn, symbol, reason=" in src
    for fn in (main._swingminrr_try_entry, main._island_swing_try_entry):
        body = inspect.getsource(fn)
        assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in body
        assert 'sig["stop_loss"]' in body
    assert ("_is_strategy_viable_for_real_money" in inspect.getsource(main._swingminrr_try_entry) or "_is_strategy_wired" in inspect.getsource(main._swingminrr_try_entry))
    assert not any("swingminrr" in n.lower() or "wirenext" in n.lower() for n in dir(main)
                   if n.startswith("is_real_") or n.endswith("_TRADING_ENABLED"))
