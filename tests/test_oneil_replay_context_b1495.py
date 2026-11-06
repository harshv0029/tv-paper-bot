"""B-1495a: the O'Neil band_cap/classic replay gets the ^NSEI index and the RS population the live pass provides,
so leaders/rsline/rsscreen can fire (run 42025478119 had n=0 for all three)."""
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import main  # noqa: E402
import swing_classic_main_replay as cl  # noqa: E402
import swing_bandcap_replay as sbr  # noqa: E402


def _frame(seed, n=600):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
    d = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"Date": d, "Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e5})


def test_prepare_sets_index_and_rs_population(monkeypatch):
    syms = [f"S{k}.NS" for k in range(12)]
    monkeypatch.setattr(main, "NSE_FULL_UNIVERSE", syms)
    frames = {s: _frame(k) for k, s in enumerate(syms[:6])}
    fetched = []

    def fetch(s):
        fetched.append(s)
        return _frame(99) if s == "^NSEI" else _frame(int(s[1:-3]))
    cl.prepare_oneil(main, frames, fetch=fetch)
    assert main._ONEIL_DAILY_IDX["close"] is not None
    assert "^NSEI" in fetched and set(fetched) - {"^NSEI"} == set(syms[6:])  # loaded frames reused
    m = main._ONEIL_RS_PASS["1w"]
    assert m is not None and set(m.columns) <= set(syms)
    main._ONEIL_DAILY_IDX["close"] = None
    main._ONEIL_RS_PASS.update({"1d": None, "1w": None})


def test_symbol_threaded_to_the_live_entry_fn():
    assert "symbol" in inspect.signature(cl.replay_symbol).parameters
    assert "oneil_swing_entry_signal(win, tag, symbol)" in inspect.getsource(cl._entry)
    assert "symbol=sym" in inspect.getsource(sbr.replay) and "cl.prepare_oneil(real, frames)" in inspect.getsource(sbr.run)
