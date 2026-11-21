"""B-1659 (user 2026-11-21 IST "Yes"): the flat Kotak DP charge per delivery sell counts in the real swing entry
viability check - PFnet re-priced with 0.8% + DP% must stay > 1.00."""
import inspect
from types import SimpleNamespace

import main

M = SimpleNamespace(pfgross=1.583, pfnet=1.138, win_rate_pct=33.78)  # macddiv hist 1h pooled run


def test_zero_extra_cost_reproduces_pfnet():
    assert main._pfnet_with_extra_cost(M, 0) == 1.138
    assert main._pfnet_with_extra_cost(SimpleNamespace(pfgross=0.0, pfnet=1.07, win_rate_pct=50.7), 0.5) is None


def test_small_position_blocked_large_allowed(monkeypatch):
    monkeypatch.setitem(main._STRATEGY_TAG_TO_REGISTRY_NAME, "dp_test_tag", "dp_test_reg")
    monkeypatch.setattr(main, "_registry_entry", lambda n: SimpleNamespace(metrics=M) if n == "dp_test_reg" else None)
    small = main._dp_charge_verdict("dp_test_tag", 1, 183.0)  # WIPRO 1 sh: DP = 12.9%
    assert small["ok"] is False and small["pfnet_with_dp"] < 1.0 and "needs > 1.00" in small["detail"]
    big = main._dp_charge_verdict("dp_test_tag", 10, 1000.0)  # Rs10,000: DP = 0.236%
    assert big["ok"] is True and big["pfnet_with_dp"] > 1.0
    assert main._dp_charge_verdict("unknown_tag", 1, 100.0) is None


def test_gate_wired_in_swing_entry_and_flagged_viability():
    src = inspect.getsource(main._maybe_place_real_swing_entry)
    assert "_dp_charge_verdict(strategy, qty, ltp)" in src and '"skipped_dp_charge_drag"' in src
    assert main._entry_reject_flag("skipped_dp_charge_drag") == "viability"
