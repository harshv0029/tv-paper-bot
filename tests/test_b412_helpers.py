import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import b412_helpers as H  # noqa: E402
import minervini_lab as lab  # noqa: E402


def test_tags_follow_grammar():
    assert H.be_tag("gap_and_go", "swing", "long", 1.0) == "gap_and_go__swing__long__1d__be1d0r__v1"
    assert H.lab_tag("pct8_hard") == "minervini_vcp__pct8_hard__long__1d__h60__v1"
    assert H.lab_tag_replay("rr3").endswith("__h60__v2")


def test_parse_lab_variant():
    assert H.parse_lab_variant("pct8_hard_f_ext_le5_on") == ("pct8_hard", "ext_le5", "on")
    assert H.parse_lab_variant("base_f_base_depth_le25_off") == ("base", "base_depth_le25", "off")
    assert H.parse_lab_variant("rr3") == ("rr3", None, None)


def test_ratchet_long_and_short():
    assert H.ratcheted_stop(100, 90, 109.9, 1.0) == 90
    assert H.ratcheted_stop(100, 90, 110.0, 1.0) == 100
    assert H.ratcheted_stop(100, 110, 90.1, 1.0, "short") == 110
    assert H.ratcheted_stop(100, 110, 90.0, 1.0, "short") == 100
    assert H.ratcheted_stop(100, 100, 120, 1.0) == 100  # zero risk: unchanged


def test_metrics_all_fields_and_no_inf():
    t = [{"gross": .1, "net": .09, "held": 5, "reason": "a"}, {"gross": -.05, "net": -.06, "held": 3, "reason": "b"}]
    m = H.metrics(t)
    assert m["n"] == 2 and m["win_pct"] == 50.0 and abs(m["pfnet"] - 0.09 / 0.06) < 1e-9
    assert set(m["exit_reasons"]) == {"a", "b"} and m["avg_held_bars"] == 4.0
    assert H.metrics([{"gross": .1, "net": .09, "held": 1, "reason": "a"}])["pfnet"] is None
    assert H.metrics([])["n"] == 0


def _frame(seed, n=500):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    o = c * (1 + rng.normal(0, 0.01, n))
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    return o, h, l, c


def test_simulate_matches_lab_run_variant():
    for seed in range(4):
        o, h, l, c = _frame(seed)
        df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c})
        for i in (230, 300, 380):
            sig = (i, c[i], c[i] * 0.93, c[i] * 0.02)
            for v in lab.VARIANTS:
                if v.startswith("regime"):
                    continue
                a = lab.run_variant(v, df, sig, np.ones(len(c), bool), 0.008)
                b = H.simulate_lab_exit(v, o, h, l, c, sig, 0.008, lab.MAXH)
                if a is None:
                    assert b is None
                else:
                    assert abs(a[0] - b[0]) < 1e-12 and a[1] == b[1], (v, seed, i)
