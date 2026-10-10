"""Pattern-lab swing cells wired live (gap_runaway, starc_fade, donchian_8wk_fade)."""
import numpy as np
import pandas as pd
import main


def _df(n=300, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    o = c * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * 1.004
    l = np.minimum(o, c) * 0.996
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e5, "Date": idx.strftime("%Y-%m-%d")}, index=idx)


def test_fresh_signals_returns_only_wired_rules():
    out = main.pattern_fresh_long_signals(_df())
    assert set(out) == {"gap_runaway", "starc_fade", "donchian_8wk_fade", "envelope_0d05_fade"}
    assert all(isinstance(v, bool) for v in out.values())


def test_starc_fires_on_a_crash_bar():
    df = _df()
    df.iloc[-1, df.columns.get_loc("Close")] = float(df["Close"].iloc[-2]) * 0.88
    df.iloc[-1, df.columns.get_loc("Low")] = float(df["Close"].iloc[-1]) * 0.995
    df.iloc[-1, df.columns.get_loc("High")] = float(df["Open"].iloc[-1]) * 1.001
    df.iloc[-1, df.columns.get_loc("Open")] = float(df["Close"].iloc[-2]) * 0.99
    assert main.pattern_fresh_long_signals(df)["starc_fade"] is True


def test_exit_reasons():
    df = _df(30)
    assert main.pattern_cell_exit_reason(df, "2024-01-01", 1e9, 20) == "stop_hit"
    assert main.pattern_cell_exit_reason(df, "2024-01-01", 0.0, 20) == "max_hold_timeout"
    assert main.pattern_cell_exit_reason(df, "2024-02-01", 0.0, 20) is None


def test_cells_tags_all_mapped_for_the_gate():
    for tag, *_ in main._PATTERN_LIVE_CELLS:  # incl. ETF cells
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[tag] == tag
