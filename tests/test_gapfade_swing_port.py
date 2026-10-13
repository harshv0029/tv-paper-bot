"""gaps fade LONG 1d port parity: main.gapfade_long_entry_signal must fire on exactly the bars the research
v_gap_fade(...)['long'] fires on (same gap / volume / no-new-low rule), the stop is always attached, the exit adapter
follows research order, and the tags are replay-owed (real-money gate closed)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import elder_macd_dirgap_research as er_gap  # noqa: E402
import main  # noqa: E402


def _bars(n=1500, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.03, n))  # frequent gaps
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    v = rng.uniform(1e5, 3e5, n) * np.where(rng.random(n) < 0.15, 3.0, 1.0)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


def test_signal_parity_with_research():
    df = _bars()
    for exhaustion, tag in ((True, main.GAPFADE_EXHAUST_TAG), (False, main.GAPFADE_COMMON_TAG)):
        ref = er_gap.v_gap_fade(df, 5, 1.5, exhaustion)["long"]
        fired = 0
        for j in range(60, len(df)):
            sig = main.gapfade_long_entry_signal(df.iloc[:j + 1], tag)
            assert bool(sig) == bool(ref[j]), (tag, j)
            if sig:
                fired += 1
                assert 0 < sig["stop_loss"] < sig["entry_price"]
        assert fired > 0


def test_unknown_tag_and_tags_replay_owed():
    assert main.gapfade_long_entry_signal(_bars(), "nope") is None
    for t in main.GAPFADE_TAGS:
        assert t in main.REPLAY_OWED_TAGS
        assert t in main._STRATEGY_TAG_TO_REGISTRY_NAME


def test_exit_adapter_stop_rule_timeout():
    df = _bars(120)
    day = str(df.index[60].date())
    stop = float(df["Low"].iloc[61]) + 1.0  # next bar's low is below the stop -> stop_loss
    reason, _ = main._gapfade_exit_adapter(df.iloc[:62], day, stop, 1.0, 100.0)
    assert reason == "gapfade_stop_loss"
    reason, _ = main._gapfade_exit_adapter(df.iloc[:61], day, 1.0, 1.0, 100.0)
    assert reason is None  # no completed bar after entry day yet
    reason, _ = main._gapfade_exit_adapter(df.iloc[:100], day, 1e-6, 1.0, 100.0)
    assert reason in ("gapfade_rule_exit", "gapfade_max_hold_timeout")
