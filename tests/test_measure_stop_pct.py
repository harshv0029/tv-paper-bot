import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import measure_stop_pct as m  # noqa: E402


def test_parse_mult():
    assert m.parse_atr_mult("fvg3c__valid_retest__short__5m__atr2d5_bt60__v1") == 2.5
    assert m.parse_atr_mult("a__b__long__1d__atr3__v1") == 3.0
    assert m.parse_atr_mult("a__b__long__1d__atrnone__v1") is None
    assert m.parse_atr_mult("gap_and_go") is None
    assert m.tag_tf("a__b__long__1h__atr3__v1") == "1h"


def test_atr_pct_and_derive():
    h, lo, c = [101] * 30, [99] * 30, [100] * 30
    assert abs(m.atr_pct_series(h, lo, c) - 2.0) < 1e-9
    assert m.atr_pct_series(h[:5], lo[:5], c[:5]) is None
    d = m.derive(["a__b__long__1d__atr2d5__v1", "a__b__long__1d__atrnone__v1", "a__b__long__5m__atr2__v1"],
                 {"1d": {"median_atr_pct": 1.0}})
    assert d == {"a__b__long__1d__atr2d5__v1": 2.5}
