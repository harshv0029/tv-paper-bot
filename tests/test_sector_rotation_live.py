"""B-336/B-348: live sector-rotation momentum entry/exit (validated n200 cell atr6d0_h20_l5_n1)."""
import numpy as np
import pandas as pd
import main


def _df(closes):
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="D")
    c = np.array(closes, float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1, "Date": idx.strftime("%Y-%m-%d")}, index=idx)


def test_picks_top_stock_of_strongest_breadth_sector(monkeypatch):
    smap = {f"A{i}.NS": "Tech" for i in range(5)} | {f"B{i}.NS": "Bank" for i in range(5)}
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: smap)
    flat = [100.0] * 30
    dfs = {}
    for i in range(5):  # Tech: all up over 5 days, A3 the biggest
        dfs[f"A{i}.NS"] = _df(flat + [100 + 2 * (i + 1)] * 1)
    for i in range(5):  # Bank: mostly down
        dfs[f"B{i}.NS"] = _df(flat + [95.0])
    # make the 5-day lookback real: last close vs close 5 bars ago
    for k, df in dfs.items():
        assert len(df) == 31
    assert main.sector_rotation_picks(dfs) == ["A4.NS"]


def test_no_pick_when_breadth_low(monkeypatch):
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {f"A{i}.NS": "Tech" for i in range(5)})
    dfs = {f"A{i}.NS": _df([100.0] * 30 + [90.0]) for i in range(5)}
    assert main.sector_rotation_picks(dfs) == []


def test_exit_reasons():
    df = _df([100.0] * 25)
    assert main.sector_rotation_exit_reason(df, "2025-01-01", 101.0) == "stop_hit"
    assert main.sector_rotation_exit_reason(df, "2025-01-01", 50.0) == "max_hold_timeout"
    assert main.sector_rotation_exit_reason(df, "2025-01-20", 50.0) is None
