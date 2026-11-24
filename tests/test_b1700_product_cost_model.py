"""B-1700 (user 2026-11-24 IST "Yes, build it"): viability and wiring judge each strategy's PFnet at its product's
real round-trip cost (intraday 0.10%, delivery 0.35%; F&O/MCX keep 0.8%), re-priced from the stored 0.8% run."""
from types import SimpleNamespace

import main
import strategy_registry as sr

M = SimpleNamespace(pfgross=1.583, pfnet=1.138, win_rate_pct=33.78)  # macddiv hist 1h pooled run (0.8%)
THIN = SimpleNamespace(pfgross=1.10, pfnet=0.95, win_rate_pct=45.0)  # loses at 0.8%, edge only before cost


def _d(asset, m=M):
    return SimpleNamespace(metrics=m, asset_class=asset)


def test_cost_table():
    assert sr.product_cost_pct(sr.AssetClass.EQUITY_INTRADAY) == 0.10
    assert sr.product_cost_pct(sr.AssetClass.EQUITY_SWING) == 0.35
    assert sr.product_cost_pct(sr.AssetClass.OPTIONS) == sr.BASE_COST_PCT == 0.8
    assert sr.product_cost_pct(None) == 0.8


def test_reprice_identity_and_direction():
    assert sr.repriced_pfnet(M, 0.8) == 1.138  # same cost reproduces the stored value
    assert sr.repriced_pfnet(M, 0.8) == main._pfnet_with_extra_cost(M, 0)  # same algebra as B-1659
    lo, mid = sr.repriced_pfnet(M, 0.10), sr.repriced_pfnet(M, 0.35)
    assert 1.138 < mid < lo <= M.pfgross
    assert sr.repriced_pfnet(M, 0.0) == round(M.pfgross, 3)  # zero cost -> gross PF
    assert sr.repriced_pfnet(SimpleNamespace(pfgross=None, pfnet=1.0, win_rate_pct=50), 0.1) is None


def test_effective_pfnet_by_product():
    assert sr.effective_pfnet(_d(sr.AssetClass.OPTIONS)) == 1.138  # F&O unchanged
    assert sr.effective_pfnet(_d(sr.AssetClass.EQUITY_SWING)) == sr.repriced_pfnet(M, 0.35)
    assert sr.effective_pfnet(_d(sr.AssetClass.EQUITY_INTRADAY, THIN)) > 1.0  # viable at real intraday cost
    assert sr.effective_pfnet(_d(sr.AssetClass.FUTURES, THIN)) == 0.95  # still not viable at 0.8%
    assert sr.effective_pfnet(SimpleNamespace(metrics=None, asset_class=None)) is None
    unpriceable = SimpleNamespace(pfgross=0.0, pfnet=1.07, win_rate_pct=50.7)
    assert sr.effective_pfnet(_d(sr.AssetClass.EQUITY_INTRADAY, unpriceable)) == 1.07  # falls back to stored


def test_is_viable_and_is_wired_use_effective(monkeypatch):
    monkeypatch.setattr(sr, "VIABLE_STACK_ACTIVE", False)
    m = sr.Metrics(pfnet=0.95, pfgross=1.10, win_rate_pct=45.0, n_trades=100)
    intr = sr.StrategyDef(name="b1700_i", asset_class=sr.AssetClass.EQUITY_INTRADAY,
                          categories=(sr.TradeCategory.BUY,), timeframe="5m", status=sr.StrategyStatus.RESEARCH, metrics=m)
    fut = sr.StrategyDef(name="b1700_f", asset_class=sr.AssetClass.FUTURES,
                         categories=(sr.TradeCategory.FUTURES,), timeframe="5m", status=sr.StrategyStatus.RESEARCH, metrics=m)
    assert intr.is_viable() is True and intr.is_wired() is True
    assert fut.is_viable() is False and fut.is_wired() is False


def test_view1_criteria_and_fail_factors_use_effective(monkeypatch):
    m = sr.Metrics(pfnet=0.95, pfgross=1.10, win_rate_pct=45.0, n_trades=100, avg_held_hrs=1.0)
    d = sr.StrategyDef(name="b1700_view1", asset_class=sr.AssetClass.EQUITY_INTRADAY,
                       categories=(sr.TradeCategory.BUY,), timeframe="5m", status=sr.StrategyStatus.RESEARCH, metrics=m)
    monkeypatch.setattr(sr, "REGISTRY", [d])
    crit = {"pf_min": 1.0, "pf_max": 99.0, "min_trades": 30, "max_hold_hrs": None}
    assert main._names_meeting_criteria(crit) == {"b1700_view1"}
    assert main._slot_fail_factors(crit, m) == ["pfnet"]  # stored 0.95 fails
    assert main._slot_fail_factors(crit, m, main._sr_effective_pfnet(d)) == []  # real-cost PFnet passes


def test_dp_verdict_uses_delivery_cost(monkeypatch):
    strat = SimpleNamespace(metrics=M, asset_class=sr.AssetClass.EQUITY_SWING)
    monkeypatch.setitem(main._STRATEGY_TAG_TO_REGISTRY_NAME, "b1700_dp_tag", "b1700_dp_reg")
    monkeypatch.setattr(main, "_registry_entry", lambda n: strat if n == "b1700_dp_reg" else None)
    v = main._dp_charge_verdict("b1700_dp_tag", 10, 1000.0)  # DP 0.236%
    assert v["pfnet_with_dp"] == sr.repriced_pfnet(M, 0.35 + 0.236) and "at 0.35%" in v["detail"]
    small = main._dp_charge_verdict("b1700_dp_tag", 1, 183.0)  # DP 12.9% still blocks
    assert small["ok"] is False


def test_nan_pfgross_falls_back_to_stored():
    nan = SimpleNamespace(pfgross=float("nan"), pfnet=1.827, win_rate_pct=47.2)  # live chan_kalman 5m run
    assert sr.repriced_pfnet(nan, 0.10) is None
    assert sr.effective_pfnet(_d(sr.AssetClass.EQUITY_INTRADAY, nan)) == 1.827
