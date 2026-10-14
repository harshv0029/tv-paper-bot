import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import option_greeks as og  # noqa: E402


@pytest.mark.parametrize("right", ["C", "P"])
@pytest.mark.parametrize("sigma", [0.1, 0.25, 0.6, 1.2])
@pytest.mark.parametrize("K", [90.0, 100.0, 115.0])
def test_iv_roundtrip(right, sigma, K):
    S, T = 100.0, 30 / 365.0
    px = og.bs_price(S, K, T, og.RISK_FREE_RATE, sigma, right)
    iv = og.implied_vol(px, S, K, T, right)
    if px < 1e-6:
        return
    assert iv is not None and abs(iv - sigma) < 1e-3


def test_put_call_parity():
    S, K, T, r, s = 100.0, 105.0, 0.1, og.RISK_FREE_RATE, 0.3
    c, p = og.bs_price(S, K, T, r, s, "C"), og.bs_price(S, K, T, r, s, "P")
    assert abs((c - p) - (S - K * math.exp(-r * T))) < 1e-9


def test_delta_bounds_and_sign():
    gc = og.greeks(100, 100, 0.1, 0.2, "C")
    gp = og.greeks(100, 100, 0.1, 0.2, "P")
    assert 0 < gc["delta"] < 1 and -1 < gp["delta"] < 0
    assert abs((gc["delta"] - gp["delta"]) - 1.0) < 1e-12
    assert gc["gamma"] > 0 and gc["vega"] > 0 and gc["theta_per_day"] < 0


def test_delta_matches_finite_difference():
    S, K, T, s, r = 100.0, 100.0, 0.2, 0.25, og.RISK_FREE_RATE
    h = 0.01
    fd = (og.bs_price(S + h, K, T, r, s, "C") - og.bs_price(S - h, K, T, r, s, "C")) / (2 * h)
    assert abs(fd - og.greeks(S, K, T, s, "C")["delta"]) < 1e-5


def test_arbitrage_violating_price_returns_none():
    assert og.implied_vol(0.5, 100, 90, 0.1, "C") is None  # below intrinsic 10
    assert og.implied_vol(150, 100, 90, 0.1, "C") is None  # above spot
    assert og.implied_vol(1.0, 100, 100, 0.0, "C") is None  # expired


def test_enrich_row_does_not_mutate_input_and_flags_model():
    row = {"premium": 3.5, "spot": 100.0, "strike": 100.0, "dte_days": 7, "right": "C", "oi": 123}
    snap = dict(row)
    out = og.enrich_row(row)
    assert row == snap and out["oi"] == 123 and out["model"] == "bs_european" and out["rate"] == 0.065
    assert out["iv"] and 0 < out["delta"] < 1


def test_enrich_row_unsolvable_keeps_none():
    out = og.enrich_row({"premium": 0.1, "spot": 100.0, "strike": 90.0, "dte_days": 7, "right": "C"})
    assert out["iv"] is None and out["delta"] is None


def test_matches_options_pricing_bs_price_if_importable():
    op = pytest.importorskip("options_pricing")
    for right in ("C", "P"):
        assert abs(op.bs_price(100, 105, 0.1, 0.065, 0.3, right) - og.bs_price(100, 105, 0.1, 0.065, 0.3, right)) < 1e-12
