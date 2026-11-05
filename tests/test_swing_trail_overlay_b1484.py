"""B-1484 (user 2026-11-05): trailing-stop overlays on the fixed-stop swing families (scripts/swing_bandcap.py)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import swing_bandcap as bc  # noqa: E402
import swing_bandcap_replay as sbr  # noqa: E402


def setup_function(_):
    bc.reset_trail()


def test_modes_and_tags():
    assert set(bc.TRAIL_MODES) <= set(bc.MODES)
    assert bc.normalize_mode("live_tr2") == "live_tr2"
    with pytest.raises(SystemExit):
        bc.normalize_mode("live_tr9")
    t = "gap__runaway__long__1d__atr4_h20__v1"
    assert bc.band_tag(t, "live") == "gap__runaway__long__1d__atr4_h20_rsbandfloor__v1"
    assert bc.band_tag(t, "live_tr1d5") == "gap__runaway__long__1d__atr4_h20_rsbandfloor_trailr1d5__v1"
    assert bc.band_tag(t, "live_be1") == "gap__runaway__long__1d__atr4_h20_rsbandfloor_trailbe1r__v1"
    assert bc.band_tag("gap_and_go", "live_tr2") == "gap_and_go__rsbandfloor__trailr2"
    # every trail tag is distinct (naming grammar: a variant is its own strategy)
    tags = {bc.band_tag(t, m) for m in bc.MODES}
    assert len(tags) == len(bc.MODES)


def test_be_cost_matches_main_cost_model():
    import main
    assert bc.BE_COST == pytest.approx(main.ROUND_TRIP_COST_PCT / 100.0)


def test_chandelier_long_raises_never_lowers_and_ignores_first_prev():
    ep, s0 = 100.0, 90.0  # R = 10
    # first prev_close (pre-entry session on 1h bars) is never used even if high
    assert bc.trailed_stop("live_tr1", "long", s0, 130.0, ep) == pytest.approx(90.0)
    assert bc.trailed_stop("live_tr1", "long", s0, 105.0, ep) == pytest.approx(95.0)   # peak 105 - 10
    assert bc.trailed_stop("live_tr1", "long", s0, 120.0, ep) == pytest.approx(110.0)  # peak 120 - 10
    assert bc.trailed_stop("live_tr1", "long", s0, 101.0, ep) == pytest.approx(110.0)  # never lowers
    assert bc.trailed_stop("live", "long", s0, 101.0, ep) == s0                       # fixed mode unchanged


def test_chandelier_short_mirror():
    ep, s0 = 100.0, 110.0
    bc.trailed_stop("live_tr2", "short", s0, 99.0, ep)  # first prev ignored
    assert bc.trailed_stop("live_tr2", "short", s0, 85.0, ep) == pytest.approx(105.0)  # 85 + 2x10
    assert bc.trailed_stop("live_tr2", "short", s0, 95.0, ep) == pytest.approx(105.0)


def test_breakeven_long():
    ep, s0 = 100.0, 90.0
    bc.trailed_stop("live_be1", "long", s0, 100.0, ep)
    assert bc.trailed_stop("live_be1", "long", s0, 109.0, ep) == s0                    # below 1R
    assert bc.trailed_stop("live_be1", "long", s0, 110.0, ep) == pytest.approx(100.8)  # entry + cost
    assert bc.trailed_stop("live_be1", "long", s0, 104.0, ep) == pytest.approx(100.8)


def test_trail_needs_entry_price():
    with pytest.raises(ValueError):
        bc.trailed_stop("live_tr1", "long", 90.0, 100.0, None)


def test_resting_stop_exit_trail_reason():
    ep = 100.0
    assert bc.resting_stop_exit("live_tr1", "long", 90.0, 100.0, 101, 99, 102, entry_price=ep) is None
    bc.resting_stop_exit("live_tr1", "long", 90.0, 108.0, 108, 107, 109, entry_price=ep)  # peak 108 -> stop 98
    hit = bc.resting_stop_exit("live_tr1", "long", 90.0, 104.0, 103, 97, 104, entry_price=ep)
    assert hit == (pytest.approx(98.0), "trail_stop_hit")
    # fixed live mode on the same bar: no hit (low 97 > stop 90 and band floor)
    assert bc.resting_stop_exit("live", "long", 90.0, 104.0, 103, 97, 104) is None


def test_reset_between_passes():
    bc.trailed_stop("live_tr1", "long", 90.0, 100.0, 100.0)
    bc.trailed_stop("live_tr1", "long", 90.0, 120.0, 100.0)
    bc.reset_trail()
    assert bc.trailed_stop("live_tr1", "long", 90.0, 120.0, 100.0) == pytest.approx(90.0)


def test_driver_modes_and_fixed_families():
    assert sbr.run_modes("trail") == ["off", "live"] + list(bc.TRAIL_MODES)
    assert sbr.run_modes("live") == ["off", "live"]
    assert sbr.run_modes("off") == ["off"]
    assert sbr.run_modes("live,live_tr2") == ["off", "live", "live_tr2"]
    fams = sbr.parse_families("fixed")
    assert "power_play" not in fams and "primary_base" not in fams and "island" in fams
