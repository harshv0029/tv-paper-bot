"""B-1244: chan cells must feed _record_strategy_scan so /strategy-scan-activity and /entry-funnel show scans_today."""
import numpy as np
import pandas as pd
import main


def _prep(monkeypatch):
    main._strategy_scan_counts.clear()
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda *a, **k: True)
    idx = pd.date_range("2026-10-14 09:15", periods=5, freq="5min")
    df = pd.DataFrame({"Close": np.ones(5)}, index=idx)
    monkeypatch.setattr(main, "_chan_short_frame", lambda d, t: df)
    monkeypatch.setattr(main, "_chan_live_masks", lambda i, iv: None)
    monkeypatch.setattr(main, "chan_kalman_series", lambda c, ve: None)
    monkeypatch.setattr(main, "chan_kalman_band_long_entry_signal", lambda *a, **k: None)
    monkeypatch.setattr(main, "chan_kalman_band_short_entry_signal", lambda *a, **k: None)
    return df


def test_chan_long_cells_record_scans(monkeypatch):
    df = _prep(monkeypatch)
    main._chan_long_try_entry(None, "X.NS", df, 0, 1.0, "2026-10-14", "5m", 1e5, 1.0, 1.0, "INR", {})
    for t in main.CHAN_LONG_CELLS:
        assert main._strategy_scan_counts.get(t) == 1


def test_chan_short_cells_record_scans_for_their_interval(monkeypatch):
    df = _prep(monkeypatch)
    main._chan_short_try_entry(None, "X.NS", df, 0, df, 1.0, "2026-10-14", "5m", 1e5, 1.0, 1.0, "INR", {})
    want = [t for t in main.CHAN_SHORT_CELLS if main.CHAN_SHORT_CELL_INTERVAL[t] == "5m"]
    assert want and all(main._strategy_scan_counts.get(t) == 1 for t in want)
    assert not any(main._strategy_scan_counts.get(t) for t in main.CHAN_SHORT_CELLS
                   if main.CHAN_SHORT_CELL_INTERVAL[t] != "5m")
