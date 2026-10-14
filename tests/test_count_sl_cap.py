import json
import sys

sys.path.insert(0, "scripts")
import count_sl_cap as c  # noqa: E402
import strategy_registry as sr  # noqa: E402


def _fake(name, pf, hrs):
    m = sr.Metrics(pfnet=pf, pfgross=pf, win_rate_pct=40, n_trades=100, avg_held_hrs=hrs)
    return type("S", (), {"name": name, "metrics": m})()


def test_buckets(tmp_path):
    side = tmp_path / "s.json"
    side.write_text(json.dumps({"a": 1.5, "b": 3.0}))
    reg = [_fake("a", 1.2, 6.25), _fake("b", 1.2, 6.25), _fake("c", 1.2, 6.25),
           _fake("d", 0.95, 6.25), _fake("e", 1.5, 6.25 * 9), _fake("f", 1.5, None)]
    r = c.count(5, 2.0, side, reg)
    assert r["pass"] == ["a"] and r["over_cap"] == ["b"] and r["unknown_stop"] == ["c"]
    assert r["hold_unknown"] == ["f"]


def test_real_registry_runs():
    r = c.count(5, 2.0, None)
    assert isinstance(r["unknown_stop"], list)
