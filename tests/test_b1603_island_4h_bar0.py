"""B-1603: BAR0_ONLY=1 replays the 4h island cells on bucket-0 (09:15-13:15 IST) signals only, the subset the live 4h
long leg actually enters; tags carry _b0 and never collide with the all-signal 4h tags."""
import os
import sys
import types

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import island_tf_dir_sweep_replay as R  # noqa: E402


def test_b0_tags_distinct_and_only_4h(monkeypatch):
    monkeypatch.setenv("BAR0_ONLY", "1")
    t4 = R.cell_specs("4h", (4.0,))
    assert all("_within8_b0__" in t for t in t4) and all(v["b0"] for v in t4.values())
    assert not any("_b0" in t for t in R.cell_specs("1d", (4.0,)))
    monkeypatch.setenv("BAR0_ONLY", "")
    assert not any("_b0" in t for t in R.cell_specs("4h", (4.0,)))


def test_is_bar0():
    assert R.is_bar0("2026-01-05 09:15:00+05:30")
    assert not R.is_bar0("2026-01-05 13:15:00+05:30")
    assert R.is_bar0("2026-01-05 03:45:00+00:00")  # 09:15 IST in UTC


def test_replay_skips_bar1_signals(monkeypatch):
    n = R.MIN_BARS + 10
    dates = [("2026-01-05 09:15:00+05:30" if i % 2 == 0 else "2026-01-05 13:15:00+05:30") for i in range(n)]
    df = pd.DataFrame({"Date": dates, "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0})
    sig = {"entry_price": 100.0, "atr_at_entry": 1.0}
    k0, k1 = R.MIN_BARS, R.MIN_BARS + 1  # even -> bar 0, odd -> bar 1
    monkeypatch.setattr(R, "collect_signals", lambda m, d, f, dr: {k0: sig, k1: sig})
    seen = []
    monkeypatch.setattr(R, "run_trade", lambda m, d, k, *a: (seen.append(k) or ({"gross": 0, "net": 0, "held": 1, "reason": "x"}, k + 1)))
    m = types.SimpleNamespace(brk20_stop_price=lambda ep, atr, k, d: ep - 2 if d == "long" else ep + 2)
    spec = {"filter": "none", "dir": "long", "tf": "4h", "atr": 4.0, "b0": True}
    R.replay_symbol(m, df, {"t": spec}, 0.008)
    assert seen == [k0]
    seen.clear()
    R.replay_symbol(m, df, {"t": dict(spec, b0=False)}, 0.008)
    assert seen == [k0, k1]
