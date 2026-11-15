"""B-1600 (c): the 12 island LONG 1d _tfs cells (all PFnet > 1.00, main.py-function sweep run 43692422951) are wired
first in ISLAND_ALL_TAGS with their own ATR k for the stop and for the exit adapter's entry recovery."""
import main


def test_tfs_cells_first_and_mapped():
    assert main.ISLAND_ALL_TAGS[:12] == main.ISLAND_TFS_LONG_1D_TAGS
    assert len(set(main.ISLAND_ALL_TAGS)) == len(main.ISLAND_ALL_TAGS)
    for t in main.ISLAND_TFS_LONG_1D_TAGS:
        assert main._ISLAND_FILTER_OF_TAG[t] in ("gap05", "none", "px20", "turn1cr")
        assert main._ISLAND_ATR_OF_TAG[t] in (1.5, 2.5, 4.0)
    assert main._ISLAND_FILTER_OF_TAG["reversal__island_gap05_tfs__long__1d__atr2d5_within8__nonovl__v2"] == "gap05"
    assert main._ISLAND_ATR_OF_TAG["reversal__island_px20_tfs__long__1d__atr4_within8__nonovl__v2"] == 4.0


def test_tfs_cells_pass_replay_gate():
    rows = {t: pf for t, n, pf in main._replay_rows() if n >= 1}
    for t in main.ISLAND_TFS_LONG_1D_TAGS:
        assert rows[t] > 1.0 and t not in main.REPLAY_OWED_TAGS


def test_stop_uses_tag_atr(monkeypatch):
    import numpy as np
    monkeypatch.setattr(main, "island_filters_passed", lambda df: {"none": True, "px20": True, "turn1cr": True})
    monkeypatch.setattr(main, "island_bottom_signal_on_last_bar", lambda df, **k: True)
    monkeypatch.setattr(main, "_brk20_atr_series", lambda h, l, c: np.full(len(c), 2.0))
    import pandas as pd
    df = pd.DataFrame({"Open": [100.0] * 30, "High": [101.0] * 30, "Low": [99.0] * 30, "Close": [100.0] * 30})
    s4 = main.island_swing_entry_signal(df, "reversal__island_none_tfs__long__1d__atr4_within8__nonovl__v2")
    s15 = main.island_swing_entry_signal(df, main.ISLAND_NONE_TAG)
    assert s4["stop_loss"] == main.brk20_stop_price(100.0, 2.0, 4.0, "long") < s15["stop_loss"]


def test_exit_adapter_recovers_entry_with_tag_atr(monkeypatch):
    import pandas as pd
    seen = []
    monkeypatch.setattr(main, "brk20_min_rr_exit_reason", lambda d, fd, ep, st, di: (seen.append(ep), (None, None))[1])
    dates = pd.date_range("2026-11-02", periods=3, freq="D").strftime("%Y-%m-%d")
    df = pd.DataFrame({"Date": dates, "Open": [100] * 3, "High": [101] * 3, "Low": [99] * 3, "Close": [100] * 3})
    main._island_swing_exit_adapter(df, "2026-11-02", 92.0, 2.0, 100.0, atr_mult=4.0)
    assert seen and set(seen) == {100.0}  # stop 92 + 4 x 2
    seen.clear()
    main._island_swing_exit_adapter(df, "2026-11-02", 97.0, 2.0, 100.0)
    assert set(seen) == {100.0}  # legacy default k = 1.5
