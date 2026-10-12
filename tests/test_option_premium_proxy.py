import math

import pytest

import option_premium_proxy as p


def test_put_call_parity():
    s, k, d, iv, r = 25000.0, 25000.0, 5.0, 0.15, p.DEFAULT_RATE
    c, pu = p.bs_price(s, k, d, iv, "call"), p.bs_price(s, k, d, iv, "put")
    t = d / 365.0
    assert c - pu == pytest.approx(s - k * math.exp(-r * t), abs=1e-6)


def test_atm_premium_scale_and_otm_cheaper():
    atm = p.bs_price(25000, 25000, 5, 0.15, "call")
    assert 150 < atm < 400
    assert p.bs_price(25000, 25100, 5, 0.15, "call") < atm


def test_theta_negative_and_accelerates_near_expiry():
    far = p.theta_per_day(25000, 25000, 20, 0.15)
    near = p.theta_per_day(25000, 25000, 2, 0.15)
    assert far < 0 and near < far


def test_delta_bounds_and_expiry_floor():
    assert 0.4 < p.bs_delta(25000, 25000, 5) < 0.6
    assert p.bs_delta(25000, 25000, 5, right="put") < 0
    assert p.bs_price(25100, 25000, 0.0) == pytest.approx(100, abs=1.0)  # no div-by-zero at expiry


def test_strike_for():
    assert p.strike_for(25030, 50, "call") == 25050
    assert p.strike_for(25030, 50, "call", 1) == 25100
    assert p.strike_for(25030, 50, "put", 1) == 25000


def test_validation():
    with pytest.raises(ValueError):
        p.bs_price(0, 100, 1)
    with pytest.raises(ValueError):
        p.bs_price(100, 100, 1, right="x")


def test_cost_positive_and_scales():
    assert p.round_trip_cost(100, 100, 75) > 40
    assert p.round_trip_cost(100, 100, 150) > p.round_trip_cost(100, 100, 75)


def test_flat_market_loses_to_theta_and_costs():
    r = p.simulate_long_option_trade([25000.0] * 40, 3.0, 50, lot_qty=75)
    assert r["label"] == p.PROXY_LABEL
    assert r["net_pnl"] < 0


def test_rally_beats_flat_and_trail_exit():
    up = [25000.0 + 15 * i for i in range(40)]
    r_up = p.simulate_long_option_trade(up, 3.0, 50, lot_qty=75)
    r_flat = p.simulate_long_option_trade([25000.0] * 40, 3.0, 50, lot_qty=75)
    assert r_up["net_pnl"] > r_flat["net_pnl"]
    spike = [25000.0 + 20 * i for i in range(20)] + [25400.0 - 40 * i for i in range(20)]
    assert p.simulate_long_option_trade(spike, 3.0, 50, lot_qty=75)["exit_reason"] == "stop"


def test_put_profits_on_decline():
    down = [25000.0 - 15 * i for i in range(40)]
    assert p.simulate_long_option_trade(down, 3.0, 50, right="put", lot_qty=75)["gross_pnl"] > 0
