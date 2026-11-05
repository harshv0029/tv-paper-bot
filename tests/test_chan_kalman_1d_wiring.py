"""B-1467: chan_kalman v1 band LONG 1d cell wired into the live swing scan (main.py replay run 41881365947).
Registry/gate/mapping, signal parity with the replayed port, stop on every trade, exit adapter, scan wiring."""
import inspect

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

T = main.CHAN_KALMAN_1D_LONG_TAG


def _frame(c, end="2026-10-30"):
    c = np.asarray(c, float)
    idx = pd.bdate_range(end=end, periods=len(c))
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": np.full(len(c), 1e5)}, index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d") for d in idx]
    return df


def _dip_frame():
    rng = np.random.default_rng(3)
    c = 100 * np.exp(rng.normal(0, 0.01, 300).cumsum())
    c[-1] = c[-2] * 0.85  # sharp drop below the adaptive mean
    return _frame(c)


def test_registry_gate_mapping_and_owner_bar():
    names = {s.name: s for s in sr.REGISTRY}
    m = names[T].metrics
    assert m.pfnet > 1.0 and m.n_trades >= 30 and m.avg_held_bars <= 30
    assert names[T.replace("__v1", "_segoos__v1")].metrics.pfnet > 1.0
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[T] == T
    assert T not in main.REPLAY_OWED_TAGS
    assert main._is_strategy_viable_for_real_money(T, check_switch=False) is True
    short = T.replace("__long__", "__short__")
    assert names[short].metrics.pfnet < 1.0 and short not in main._STRATEGY_TAG_TO_REGISTRY_NAME
    assert main._strategy_hold_spec(T)[0] == 40


def test_signal_parity_and_stop_below_entry():
    df = _dip_frame()
    z, ve, k, _h = main.CHAN_KALMAN_1D_CELLS[T]
    ref = main.chan_kalman_band_v1_entry_signal(df, "1d", "long", z=z, ve=ve, atr_mult=k)
    sig = main.chan_kalman_1d_long_entry_signal(df, T)
    assert ref is not None and sig is not None
    assert sig["entry_price"] == pytest.approx(ref["close"])
    assert sig["stop_loss"] == pytest.approx(ref["close"] - 4.0 * ref["atr"])
    assert 0 < sig["stop_loss"] < sig["entry_price"]
    assert main.chan_kalman_1d_long_entry_signal(df, "nope") is None
    assert main.chan_kalman_1d_long_entry_signal(df.iloc[:30], T) is None
    flat = _frame(np.full(300, 100.0))
    assert main.chan_kalman_1d_long_entry_signal(flat, T) is None


def test_exit_adapter_stop_state_and_hold():
    df = _dip_frame()
    ed = df["Date"].iloc[-1]
    assert main._chan_kalman_1d_exit_adapter(df, ed, 50.0, 1.0, 0.0, T)[0] is None  # no bar after entry yet
    c = df["Close"].to_numpy()
    nxt = _frame(np.append(c, c[-1] * 0.5), end="2026-11-02")
    assert main._chan_kalman_1d_exit_adapter(nxt, ed, c[-1] * 0.7, 1.0, 0.0, T)[0] == "chan_kalman_stop"
    up = _frame(np.append(c, c[-2] * 1.05), end="2026-11-02")  # snaps back above the mean -> state exit
    assert main._chan_kalman_1d_exit_adapter(up, ed, c[-1] * 0.5, 1.0, 0.0, T)[0] == "chan_kalman_state_exit"


def test_scan_wiring_and_exit_branch():
    src = inspect.getsource(main._run_swing_scan_pass)
    assert src.index("_pl1d_try_entry(conn") < src.index("_chan_kalman_1d_try_entry(conn")
    assert 'pos["strategy"] in CHAN_KALMAN_1D_CELLS' in src
    ent = inspect.getsource(main._chan_kalman_1d_try_entry)
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in ent
    assert "_is_strategy_wired(tag" in ent


def test_blocked_trigger_when_gate_closed(monkeypatch):
    main._strategy_blocked_triggers.clear()
    monkeypatch.setattr(main, "chan_kalman_1d_long_entry_signal",
                        lambda df, t: {"entry_price": 10.0, "stop_loss": 9.0, "atr_at_entry": 0.25})
    monkeypatch.setattr(main, "_is_strategy_wired", lambda t, check_switch=True: False)
    before = main._strategy_scan_counts.get(T, 0)
    assert main._chan_kalman_1d_try_entry(None, "X.NS", None, 1e5, 0.01, "2026-10-30", 1.0) is False
    assert main._strategy_scan_counts.get(T, 0) > before
    assert main._strategy_blocked_triggers.get(T, 0) == 1
