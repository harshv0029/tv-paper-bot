"""B-1600 (a): island SHORT 1d _tfs cells (main.py-function sweep run 43692422951, pooled PFnet > 1.00) are wired into
the short-swing engine: entry via island_short_entry_signal + brk20_stop_price(k), exit via _short_swing_exit_reason,
replay gate open (sweep file counts as a main.py replay). Real leg still behind SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED."""
import pandas as pd

import main


def test_cells_wired_and_pass_floor():
    for tag, sel, k in main.ISLAND_SHORT_SWING_CELLS:
        assert tag in main.SHORT_SWING_TAGS
        assert main.BRK20_SHORT_SWING_ATR_OF_TAG[tag] == k
        assert sel in main.ISLAND_SHORT_TAGS
        assert "__short__1d__" in tag and "_tfs__" in tag
    rows = {t: pf for t, n, pf in main._replay_rows() if n >= 1}
    for tag, _sel, _k in main.ISLAND_SHORT_SWING_CELLS:
        assert rows[tag] > 1.0
        assert tag in main._replay_verified_tags()
        assert tag not in main.REPLAY_OWED_TAGS


def test_replay_floor_is_strict(monkeypatch):
    monkeypatch.setattr(main, "_replay_rows", lambda: [("a", 5, 1.0), ("b", 5, 1.0001), ("c", 0, 3.0)])
    assert main._replay_verified_tags() == frozenset({"b"})


def test_entry_uses_island_signal_and_sets_stop_per_atr(monkeypatch):
    monkeypatch.setattr(main, "brk20_min_rr_entry_signal", lambda *a, **k: None)
    base = {"entry_price": 100.0, "stop_loss": 103.0, "atr_at_entry": 2.0, "risk": 3.0, "signal_close": 100.0,
            "direction": "short", "filter": "gap05"}
    monkeypatch.setattr(main, "island_short_entry_signal", lambda df, tag: dict(base) if tag == main.ISLAND_SHORT_GAP05_TAG else None)
    tag, sig = main.short_swing_entry_signal(pd.DataFrame())
    assert tag == main.ISLAND_SHORT_SWING_CELLS[0][0]
    assert sig["stop_loss"] == main.brk20_stop_price(100.0, 2.0, 4.0, "short") and sig["stop_loss"] > 100.0
    assert sig["atr_at_entry"] == 2.0


def test_px20_cell_fires_when_gap05_does_not(monkeypatch):
    monkeypatch.setattr(main, "brk20_min_rr_entry_signal", lambda *a, **k: None)
    base = {"entry_price": 50.0, "stop_loss": 52.0, "atr_at_entry": 1.0, "risk": 2.0, "signal_close": 50.0,
            "direction": "short", "filter": "px20"}
    monkeypatch.setattr(main, "island_short_entry_signal", lambda df, tag: dict(base) if tag == main.ISLAND_SHORT_PX20_TAG else None)
    tag, sig = main.short_swing_entry_signal(pd.DataFrame())
    assert tag == "reversal__island_px20_tfs__short__1d__atr4_within8__nonovl__v2"
    assert sig["stop_loss"] > sig["entry_price"]


def test_no_signal_returns_none(monkeypatch):
    monkeypatch.setattr(main, "brk20_min_rr_entry_signal", lambda *a, **k: None)
    monkeypatch.setattr(main, "island_short_entry_signal", lambda df, tag: None)
    assert main.short_swing_entry_signal(pd.DataFrame()) == (None, None)


def test_exit_reason_replays_for_island_tag():
    tag, _sel, k = main.ISLAND_SHORT_SWING_CELLS[0]
    dates = pd.date_range("2026-11-02", periods=6, freq="D").strftime("%Y-%m-%d")
    df = pd.DataFrame({"Date": dates, "Open": [100, 100, 101, 104, 109, 110], "High": [101, 101, 103, 110, 111, 112],
                       "Low": [99, 99, 100, 103, 108, 109], "Close": [100, 100, 102, 109, 110, 111]})
    atr = 2.0
    stop = 100.0 + k * atr
    r = main._short_swing_exit_reason(df, "2026-11-02", stop, atr, tag)
    assert r and r.startswith("short_swing_")


def test_real_leg_still_fail_closed():
    assert main.SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED is False
