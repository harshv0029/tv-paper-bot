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
    wired = {c[1] for c in main._PATTERN_LIVE_CELLS}
    assert set(out) <= wired and {"starc_fade", "weekly_reversal&donchian_2wk_fade", "donchian_8wk_fade"} <= set(out)
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


def test_every_generated_cell_resolves_has_a_stop_and_is_long_daily():
    pl = main._pattern_lab()
    sigs = pl.all_signals(pl.clean_bars(_df(400)[["Open", "High", "Low", "Close", "Volume"]]))
    keys = set(sigs) | {k.replace("__", "_") for k in sigs}
    assert len(main._PATTERN_LIVE_CELLS) >= 4
    for tag, rule, hold, k in main._PATTERN_LIVE_CELLS:
        assert k > 0 and hold in (5, 10, 20, 30), tag      # never a position without a protective stop
        assert "__long__1d__" in tag, tag
        for part in rule.split("&"):
            assert part in keys, (tag, part)               # every wired rule exists in the backtest's own rule code


def test_live_list_has_unique_tags_and_best_first():
    tags = [c[0] for c in main._PATTERN_LIVE_CELLS]
    assert len(tags) == len(set(tags))
