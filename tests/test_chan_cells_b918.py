"""B-918: every wired chan short cell is a registry entry mapped 1:1; manage uses the row's own cell; long port mirrors short."""
import numpy as np
import pandas as pd

import main
import strategy_registry as sr


def test_cells_registered_mapped_and_distinct():
    names = {d.name for d in sr.REGISTRY}
    assert len(main.CHAN_SHORT_CELLS) == 12  # B-965: +3 ve1e-4 z2 cells; B-980: +3 15m cells
    for t in main.CHAN_SHORT_CELLS:
        assert t in names, t
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert ("__short__5m__" in t or "__short__15m__" in t) and t.endswith("_fl1515__v2")
    assert next(iter(main.CHAN_SHORT_CELLS)) == main.CHAN_SHORT_TAG  # live cell stays first in the cascade


def test_manage_stop_flatten_per_cell():
    ts = pd.DatetimeIndex(["2026-10-14 05:00"], tz="UTC")
    df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]})
    for tag in main.CHAN_SHORT_CELLS:
        row = {"stop_loss": 110.0, "entry_price": 100.0, "entry_ts": 0, "strategy": tag}
        assert main._chan_short_manage(None, "X", row, df, ts, "5m", 600, 111.0, False) == "stop_hit"
        assert main._chan_short_manage(None, "X", row, df, ts, "5m", 15 * 60 + 10, 99.0, False) == "flatten_1515"


def _frame(seed=5):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-08-03", periods=8):
        t = pd.Timestamp(d.date()).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        idx += [t + pd.Timedelta(minutes=5 * k) for k in range(75)]
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, len(idx))))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.001, "Low": np.minimum(o, c) * 0.999,
                         "Close": c, "Volume": 1e5}, index=pd.DatetimeIndex(idx))


def test_long_port_fires_and_exits():
    df = _frame()
    fired = 0
    for i in range(30, len(df)):
        sl = df.iloc[:i + 1]
        a = main.chan_kalman_band_long_entry_signal(sl, "5m", 1.0, 1e-3, 2.5, masks=main._chan_live_masks(sl.index, "5m"))
        if a:
            fired += 1
            assert a["atr"] > 0 and a["atr_mult"] == 2.5
    assert fired > 0
    last = df.iloc[-1]
    r = main.chan_kalman_band_long_exit_reason(df, "5m", len(df) - 1, float(last["Open"]), float(last["Low"]) + 1.0)
    assert r and r[0] == "stop"


def test_live_masks_allow_midday_entry_and_match_full_day():
    df = _frame()
    full = main.chan_flatten_masks(df.index, "5m")
    # partial last day: raw masks block the last two bars (the live bug), live masks equal the full-day masks
    part = df.iloc[:-40]
    raw = main.chan_flatten_masks(part.index, "5m")
    live = main._chan_live_masks(part.index, "5m")
    assert raw[1][-1] and not live[1][-1]
    assert np.array_equal(live[1], full[1][:len(part)])
    assert np.array_equal(live[0], full[0][:len(part)])
