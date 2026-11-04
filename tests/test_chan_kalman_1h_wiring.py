"""B-1465/B-1467: chan_kalman v1 band LONG 1h cell wired into the 1h leg of the swing engine (main.py replay run
41886040481). Registry/gate/mapping, signal parity, stop on every trade, exit adapter, 1h chain wiring."""
import inspect

import numpy as np
import pandas as pd
import pytest

import main
import strategy_registry as sr

T = main.CHAN_KALMAN_1H_LONG_TAG


def _frame(c, start="2026-09-01 09:15"):
    c = np.asarray(c, float)
    idx = pd.date_range(start=start, periods=len(c), freq="h")
    df = pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c, "Volume": np.full(len(c), 1e5)},
                      index=idx)
    df["Date"] = [d.strftime("%Y-%m-%d %H:%M") for d in idx]
    return df


def _dip_frame():
    rng = np.random.default_rng(5)
    c = 100 * np.exp(rng.normal(0, 0.004, 300).cumsum())
    c[-1] = c[-2] * 0.93
    return _frame(c)


def test_registry_gate_mapping_and_owner_bar():
    names = {s.name: s for s in sr.REGISTRY}
    m = names[T].metrics
    assert m.pfnet > 1.0 and m.n_trades >= 30
    assert names[T.replace("__v1", "_segoos__v1")].metrics.pfnet > 1.0
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[T] == T
    assert T not in main.REPLAY_OWED_TAGS
    assert main._is_strategy_viable_for_real_money(T, check_switch=False) is True
    assert main._strategy_hold_spec(T) == (40, "1h")


def test_signal_parity_and_stop_below_entry():
    df = _dip_frame()
    z, ve, k, _h = main.CHAN_KALMAN_1H_CELLS[T]
    ref = main.chan_kalman_band_v1_entry_signal(df, "1h", "long", z=z, ve=ve, atr_mult=k)
    sig = main.chan_kalman_1h_long_entry_signal(df, T)
    assert ref is not None and sig is not None
    assert sig["entry_price"] == pytest.approx(ref["close"])
    assert sig["stop_loss"] == pytest.approx(ref["close"] - 4.0 * ref["atr"])
    assert 0 < sig["stop_loss"] < sig["entry_price"]
    assert main.chan_kalman_1h_long_entry_signal(df, "nope") is None
    assert main.chan_kalman_1h_long_entry_signal(df.iloc[:30], T) is None
    assert main.chan_kalman_1h_long_entry_signal(_frame(np.full(300, 100.0)), T) is None


def test_exit_stop_and_state_exit():
    df = _dip_frame()
    pos = {"strategy": T, "entry_day": df["Date"].iloc[-1], "initial_stop_loss": 50.0}
    assert main._chan_kalman_long_1h_exit(df, pos) is None  # no bar after the signal bar yet
    c = df["Close"].to_numpy()
    down = _frame(np.append(c, c[-1] * 0.5))
    r = main._chan_kalman_long_1h_exit(down, dict(pos, initial_stop_loss=c[-1] * 0.8))
    assert r[0] == "chan_kalman_stop"
    up = _frame(np.append(c, c[-2] * 1.03))
    assert main._chan_kalman_long_1h_exit(up, dict(pos, initial_stop_loss=c[-1] * 0.5))[0] == "chan_kalman_state_exit"


def test_1h_chain_wiring_and_daily_pass_skip():
    src = inspect.getsource(main._run_long_swing_1h_pass)
    assert src.index("_cup_cheat_long_1h_try_entry(conn") < src.index("_chan_kalman_long_1h_try_entry(conn")
    assert "_chan_kalman_long_1h_exit(df, pos)" in src
    assert "CHAN_KALMAN_1H_CELLS" in inspect.getsource(main._run_swing_scan_pass)
    assert "CHAN_KALMAN_1H_CELLS" in inspect.getsource(main._scan_only_1h_long_cells)
    assert T in main._with_held_1h_long_symbols.__code__.co_names or "CHAN_KALMAN_1H_CELLS" in inspect.getsource(
        main._with_held_1h_long_symbols)
    ent = inspect.getsource(main._chan_kalman_long_1h_try_entry)
    assert "_maybe_place_real_swing_entry(conn, symbol, qty, entry_price, stop_loss, tag)" in ent
    assert "_is_strategy_wired(tag" in ent


def test_blocked_trigger_when_gate_closed(monkeypatch):
    main._strategy_blocked_triggers.clear()
    monkeypatch.setattr(main, "chan_kalman_1h_long_entry_signal",
                        lambda df, t: {"entry_price": 10.0, "stop_loss": 9.0, "atr_at_entry": 0.25})
    monkeypatch.setattr(main, "_is_strategy_wired", lambda t, check_switch=True: False)
    assert main._chan_kalman_long_1h_try_entry(None, "X.NS", None, 1e5, 0.01) is None
    assert main._strategy_blocked_triggers.get(T, 0) == 1
