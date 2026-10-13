"""B-1001: pl1d SHORT mirror (research-only) helpers and replay driver."""
import os
import sys

import numpy as np
import pandas as pd

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import pl1d_short_main_replay as rp  # noqa: E402

STARC = "starc__fade_full__short__1d__atr2d5_h20__v1"
GAP = "gap__runaway__short__1d__atr4_h20__v1"


def _daily(o, h, l, c):
    n = len(c)
    return pd.DataFrame({"Date": pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d"),
                         "Open": np.asarray(o, float), "High": np.asarray(h, float), "Low": np.asarray(l, float),
                         "Close": np.asarray(c, float), "Volume": 1e6})


def _flat(n=80, px=100.0, spread=1.0):
    c = np.full(n, px)
    return c.copy(), c + spread, c - spread, c.copy()


def test_cells_are_short_tagged_not_live_and_not_in_long_cells():
    assert set(main.PL1D_SHORT_CELLS) == {STARC, GAP}
    assert all("__short__" in t for t in main.PL1D_SHORT_CELLS)
    assert not set(main.PL1D_SHORT_CELLS) & set(main.PL1D_CELLS)


def test_starc_short_fires_on_spike_up_with_stop_above():
    o, h, l, c = _flat()
    c[-1], h[-1] = 112.0, 113.0
    sig = main.pl1d_short_entry_signal(_daily(o, h, l, c), STARC)
    assert sig and sig["direction"] == "short" and sig["stop_loss"] > sig["entry_price"]
    assert main.pl1d_short_entry_signal(_daily(*_flat()), STARC) is None


def test_gap_short_fires_on_gap_down_below_ma50():
    o, h, l, c = _flat()
    o[-1], h[-1], l[-1], c[-1] = 97.5, 98.0, 95.0, 96.0
    sig = main.pl1d_short_entry_signal(_daily(o, h, l, c), GAP)
    assert sig and sig["stop_loss"] > sig["entry_price"]
    assert main.pl1d_short_entry_signal(_daily(*_flat()), GAP) is None


def test_exit_stop_gap_aware_and_timeout():
    n = 30
    o, h, l, c = _flat(n)
    df = _daily(o, h, l, c)
    day = df["Date"].iloc[0]
    # first bar after entry pierces stop: fills at the stop
    h2 = h.copy(); h2[1] = 120.0
    r, px = main.pl1d_short_exit_reason(_daily(o, h2, l, c), day, 110.0, 20)
    assert r == "pl1d_short_stop_loss" and px == 110.0
    # later bar gaps over the stop: covers at the worse open
    o3, h3 = o.copy(), h.copy(); o3[5] = 115.0; h3[5] = 116.0
    r, px = main.pl1d_short_exit_reason(_daily(o3, h3, l, c), day, 110.0, 20)
    assert r == "pl1d_short_stop_loss" and px == 115.0
    r, px = main.pl1d_short_exit_reason(df, day, 110.0, 20)
    assert r == "pl1d_short_max_hold_timeout" and px == 100.0
    assert main.pl1d_short_exit_reason(df.iloc[:5], day, 110.0, 20) == (None, None)


def test_replay_short_pnl_sign_and_stop_attached():
    row = rp.short_trade_row(100.0, 90.0, 3, "x", 0.008, 1, 4)
    assert abs(row["gross"] - 0.10) < 1e-9 and abs(row["net"] - 0.092) < 1e-9
    o, h, l, c = _flat(90)
    c[70], h[70] = 112.0, 113.0
    out = rp.replay_symbol(main, _daily(o, h, l, c), [STARC], 0.008)
    assert out[STARC] and out[STARC][0]["reason"] in ("pl1d_short_stop_loss", "pl1d_short_max_hold_timeout",
                                                      "data_end_forced_close")
