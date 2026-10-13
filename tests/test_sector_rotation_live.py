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
    picks = main.sector_rotation_picks(dfs)
    assert picks[0] == "A4.NS" and len(picks) == main.SECTOR_ROT_N and all(p.startswith("A") for p in picks)


def test_no_pick_when_breadth_low(monkeypatch):
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: {f"A{i}.NS": "Tech" for i in range(5)})
    dfs = {f"A{i}.NS": _df([100.0] * 30 + [90.0]) for i in range(5)}
    assert main.sector_rotation_picks(dfs) == []


def test_exit_reasons():
    df = _df([100.0] * 25)
    assert main.sector_rotation_exit_reason(df, "2025-01-01", 101.0) == "stop_hit"
    assert main.sector_rotation_exit_reason(df, "2025-01-01", 50.0) == "max_hold_timeout"
    assert main.sector_rotation_exit_reason(df, "2025-01-20", 50.0) is None


# ---- fade-short family port ----
def _bars(o, h, c):
    return pd.DataFrame({"Open": o, "High": h, "Low": o, "Close": c})


def test_fade_short_picks_param_override_matches_default(monkeypatch):
    smap = {f"A{i}.NS": "Tech" for i in range(6)}
    monkeypatch.setattr(main, "_sector_of_symbol", lambda: smap)
    dfs = {f"A{i}.NS": _df([100.0] * 30 + [100 + i + 1]) for i in range(6)}
    assert main.sector_rotation_fade_short_picks(dfs, main.SECTOR_ROT_L, 2) == ["A5.NS", "A4.NS"]
    assert main.sector_rotation_picks(dfs) == main.sector_rotation_picks(dfs, L=main.SECTOR_ROT_L, N=main.SECTOR_ROT_N)


def test_fade_short_stop_requires_valid_atr():
    assert main.sector_rotation_fade_short_stop(100, 2, 1.5) == 103.0
    assert main.sector_rotation_fade_short_stop(100, 2, None) is None   # atrnone refused
    assert main.sector_rotation_fade_short_stop(100, 0, 1.5) is None


def test_fade_short_exit_fills_and_time_exit():
    b = _bars([100, 108], [101, 112], [100, 110])
    assert main.sector_rotation_fade_short_exit_reason(b, 105.0, 3, "stop") == ("stop_hit", 105.0, 2)
    assert main.sector_rotation_fade_short_exit_reason(b, 105.0, 3, "gap_aware") == ("stop_hit", 108.0, 2)
    assert main.sector_rotation_fade_short_exit_reason(b, 111.0, 3, "close") is None
    flat = _bars([100] * 3, [101] * 3, [99, 98, 97])
    assert main.sector_rotation_fade_short_exit_reason(flat, 110.0, 3) == ("max_hold_timeout", 97.0, 3)
    assert main.sector_rotation_fade_short_exit_reason(flat, 110.0, 1) == ("max_hold_timeout", 99.0, 1)
