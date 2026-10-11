"""Pure-helper and driver tests for scripts/confidence_threshold_sweep.py (B-421)."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import confidence_threshold_sweep as c  # noqa: E402
import main  # noqa: E402


def _closes(slope, n=60, noise=0.2, seed=1):
    rng = np.random.default_rng(seed)
    return 100 + slope * np.arange(n) + rng.normal(0, noise, n)


def _gate(closes, d, thr):
    return c.gate_passes(closes, d, thr, main._trend_confidence, main._moving_average)


def test_threshold_zero_is_ungated():
    assert _gate(_closes(-1.0), "long", 0)
    assert _gate(_closes(1.0), "short", 0)


def test_direction_awareness():
    up, down = _closes(1.0), _closes(-1.0)
    assert _gate(up, "long", 95) and not _gate(up, "short", 50)
    assert _gate(down, "short", 95) and not _gate(down, "long", 50)


def test_too_short_history_fails_closed():
    assert not _gate(_closes(1.0, n=10), "long", 50)


def test_threshold_monotone():
    up = _closes(0.05, noise=1.0, seed=3)
    passed = [_gate(up, "long", t) for t in c.THRESHOLDS]
    assert passed == sorted(passed, reverse=True)  # once it fails it keeps failing


def test_tag_grammar():
    spec = c.STRATEGIES["gap_and_go_short"]
    assert c.make_tag(spec, 70) == "gap_and_go__confgate__short__1d__cf70_smaf9_smas21__v1"
    assert c.make_tag(spec, 0).startswith("gap_and_go__confgate__short__1d__cf0_")
    tags = {c.make_tag(s, t) for s in c.STRATEGIES.values() for t in c.THRESHOLDS}
    assert len(tags) == len(c.STRATEGIES) * len(c.THRESHOLDS)


def test_every_strategy_resolves_to_real_main_functions():
    for s in c.STRATEGIES.values():
        assert callable(getattr(main, s.entry_fn)) and callable(getattr(main, s.exit_fn))
    assert not set(c.EXEMPT_MEAN_REVERSION) & set(c.STRATEGIES)


def test_sharding_partitions():
    syms = [f"S{i}.NS" for i in range(101)]
    parts = [c.shard_symbols(syms, k, 3) for k in range(3)]
    assert sorted(sum(parts, [])) == sorted(syms)
    assert all(not set(a) & set(b) for i, a in enumerate(parts) for b in parts[i + 1:])


def test_acc_merge_equals_pooled():
    trades = [{"net_pnl": 10, "gross_pnl": 12, "held_days": 3, "exit_reason": "a"},
              {"net_pnl": -5, "gross_pnl": -3, "held_days": 1, "exit_reason": "b"},
              {"net_pnl": 20, "gross_pnl": 22, "held_days": 5, "exit_reason": "a"}]
    one, x, y = c.Acc(), c.Acc(), c.Acc()
    for t in trades:
        one.add(t)
    x.add(trades[0])
    y.add(trades[1])
    y.add(trades[2])
    z = c.Acc()
    z.merge_dict(x.to_dict())
    z.merge_dict(y.to_dict())
    assert z.to_dict() == one.to_dict()
    m = c.metrics_from_sums(one.total)
    assert m["n"] == 3 and abs(m["pf_net"] - 30 / 5) < 1e-9 and abs(m["win_rate_pct"] - 200 / 3) < 1e-9
    assert c.metrics_from_sums(c._zero())["pf_net"] is None


def test_best_threshold_meeting_floor():
    rows = {0: {"pf_net": 1.0, "n": 5}, 50: {"pf_net": 1.2, "n": 4}, 70: {"pf_net": 1.5, "n": 3},
            90: {"pf_net": 0.9, "n": 1}, 95: {"pf_net": None, "n": 0}}
    assert c.best_threshold_meeting_floor(rows, 1.1) == 70
    assert c.best_threshold_meeting_floor(rows, 9.0) is None


def _frame(n=320):
    close = 100 + 0.5 * np.arange(n) + np.random.default_rng(0).normal(0, 0.3, n)
    return pd.DataFrame({"Date": pd.date_range("2020-01-01", periods=n).astype(str), "Open": close,
                         "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1e6})


def _exit(sub, label, stop, atr, running):
    return ("max_hold_timeout" if len(sub) % 7 == 0 else None), running


def test_replay_gate_blocks_wrong_direction():
    long_spec = c.STRATEGIES["power_play_long"]
    short_spec = c.STRATEGIES["power_play_short"]

    def long_entry(sub):
        px = float(sub["Close"].iloc[-1])
        return {"entry_price": px, "stop_loss": px - 3, "atr_at_entry": 1.0}

    def short_entry(sub):
        px = float(sub["Close"].iloc[-1])
        return {"entry_price": px, "stop_loss": px + 3, "atr_at_entry": 1.0}

    res = c.replay_symbol("X.NS", _frame(), long_spec, (0, 95), 2.0, 400000.0, c.DEFAULT_COST_MODEL,
                          long_entry, _exit, main._trend_confidence, main._moving_average)
    assert res[0]
    res_s = c.replay_symbol("X.NS", _frame(), short_spec, (0, 95), 2.0, 400000.0, c.DEFAULT_COST_MODEL,
                            short_entry, _exit, main._trend_confidence, main._moving_average)
    assert res_s[0] and not res_s[95]  # uptrend: the short gate blocks every entry


def test_run_and_merge_end_to_end(tmp_path, monkeypatch):
    frames = {"A.NS": _frame(), "B.NS": _frame()}
    monkeypatch.setattr(c, "fetch_universe",
                        lambda syms, p, i, chunk_size=250: {s: frames[s] for s in syms if s in frames})
    monkeypatch.setattr(main, "_load_nse_universe_from_file", lambda: ["A.NS", "B.NS", "C.NS"])
    monkeypatch.setattr(main, "power_play_entry_signal", lambda sub: {
        "entry_price": float(sub["Close"].iloc[-1]), "stop_loss": float(sub["Close"].iloc[-1]) - 3,
        "atr_at_entry": 1.0})
    monkeypatch.setattr(main, "power_play_exit_reason",
                        lambda sub, e, s, a, r: ("max_hold_timeout" if len(sub) % 9 == 0 else None, r))
    outs = []
    for k in range(2):
        out = tmp_path / f"s{k}.json"
        c.main(["run", "--strategy", "power_play_long", "--shard", str(k), "--nshards", "2", "--out", str(out)])
        outs.append(str(out))
    merged = tmp_path / "m.json"
    c.main(["merge", "--inputs", *outs, "--out", str(merged)])
    data = json.loads(merged.read_text())
    cells = data["strategies"]["power_play_long"]["cells"]
    assert [x["threshold"] for x in cells] == list(c.THRESHOLDS)
    assert cells[0]["n"] > 0
    assert cells[0]["tag"] == "power_play__confgate__long__1d__cf0_smaf9_smas21__v1"
    assert "exit_reasons" in cells[0]
    assert data["strategies"]["power_play_long"]["symbols_fetched"] == 2
