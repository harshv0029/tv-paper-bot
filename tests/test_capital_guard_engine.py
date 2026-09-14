"""
Tests for Module 482 - Live Capital Guard Engine (app/risk/capital_guard.py).
See that module's docstring for the DPR source section (16 + the exact
Section 23 severity/action table and pseudocode) and implementation
assumptions.
"""
import sqlite3
import uuid

import pytest

from app.risk.capital_guard import (
    CapitalGuardError,
    CapitalGuardSnapshot,
    DimensionPolicy,
    LiveCapitalGuardEngineService,
    Severity,
)


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    s = LiveCapitalGuardEngineService(conn)
    s.set_policy(
        "PORT-1",
        {
            "exposure": DimensionPolicy(soft_limit="0.5", hard_limit="0.7", critical_limit="0.9"),
            "drawdown": DimensionPolicy(soft_limit="0.1", hard_limit="0.15", critical_limit="0.2"),
            "liquidity": DimensionPolicy(soft_limit="0.3", hard_limit="0.15", critical_limit="0.05"),
        },
        forbid_risk_increase_on_warning=True,
        config_version="v1",
    )
    return s


def _snap(**overrides):
    base = dict(
        portfolio_id="PORT-1",
        exposure="0.2", margin="0.1", drawdown="0.02", correlation="0.1",
        volatility="0.1", liquidity="0.8",
        data_quality="VALID", broker_position_reconciled=True,
        correlation_id=str(uuid.uuid4()), idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return CapitalGuardSnapshot(**base)


def test_all_metrics_inside_policy_is_normal(svc):
    d = svc.evaluate(_snap())
    assert d.severity == Severity.NORMAL
    assert d.actions == ["normal_operation"]
    assert d.breaches == []


def test_approaching_soft_limit_is_warning_with_notify_and_forbid(svc):
    d = svc.evaluate(_snap(exposure="0.55"))
    assert d.severity == Severity.WARNING
    assert "notify" in d.actions
    assert "forbid_risk_increases" in d.actions
    assert len(d.breaches) == 1
    assert d.breaches[0].dimension == "exposure"


def test_hard_limit_exceeded_is_reduce(svc):
    d = svc.evaluate(_snap(exposure="0.75"))
    assert d.severity == Severity.REDUCE
    assert "cancel_risk_increasing_orders" in d.actions
    assert "reduce_selected_exposure" in d.actions


def test_critical_limit_is_exit(svc):
    d = svc.evaluate(_snap(drawdown="0.25"))
    assert d.severity == Severity.EXIT
    assert d.actions == ["submit_exit_commands"]


def test_liquidity_is_inverted_low_value_is_worse(svc):
    # liquidity soft_limit=0.3: a value AT/BELOW 0.3 is a breach (unlike
    # the other dimensions, where higher is worse).
    d_ok = svc.evaluate(_snap(idempotency_key=str(uuid.uuid4()), liquidity="0.8"))
    d_bad = svc.evaluate(_snap(idempotency_key=str(uuid.uuid4()), liquidity="0.25"))
    assert d_ok.severity == Severity.NORMAL
    assert d_bad.severity == Severity.WARNING
    assert d_bad.breaches[0].dimension == "liquidity"


def test_invalid_data_quality_forces_capital_protection_mode(svc):
    d = svc.evaluate(_snap(data_quality="STALE"))
    assert d.severity == Severity.CAPITAL_PROTECTION_MODE
    assert "no_new_openings" in d.actions
    assert "require_validated_recovery" in d.actions


def test_unreconciled_broker_position_forces_capital_protection_mode(svc):
    d = svc.evaluate(_snap(broker_position_reconciled=False))
    assert d.severity == Severity.CAPITAL_PROTECTION_MODE


def test_worst_dimension_wins_when_multiple_breach(svc):
    d = svc.evaluate(_snap(exposure="0.55", drawdown="0.25"))  # WARNING + EXIT
    assert d.severity == Severity.EXIT
    assert len(d.breaches) == 2


def test_protection_mode_is_durable_across_a_clean_snapshot(svc):
    # AC-482-03: protection mode is durable and requires controlled recovery.
    d1 = svc.evaluate(_snap(idempotency_key=str(uuid.uuid4()), data_quality="STALE"))
    assert d1.severity == Severity.CAPITAL_PROTECTION_MODE

    # A perfectly clean snapshot must NOT self-heal the portfolio out of
    # protection mode.
    d2 = svc.evaluate(_snap(idempotency_key=str(uuid.uuid4())))
    assert d2.severity == Severity.CAPITAL_PROTECTION_MODE
    assert d2.forced_protection is True


def test_clear_protection_requires_privileged_actor_and_checklist(svc):
    svc.evaluate(_snap(idempotency_key=str(uuid.uuid4()), data_quality="STALE"))

    assert svc.clear_protection("PORT-1", privileged_actor=None, validation_checklist_id="chk-1") is False
    assert svc.clear_protection("PORT-1", privileged_actor="ops_lead", validation_checklist_id=None) is False

    d_still_locked = svc.evaluate(_snap(idempotency_key=str(uuid.uuid4())))
    assert d_still_locked.severity == Severity.CAPITAL_PROTECTION_MODE

    assert svc.clear_protection("PORT-1", privileged_actor="ops_lead", validation_checklist_id="chk-1") is True

    d_recovered = svc.evaluate(_snap(idempotency_key=str(uuid.uuid4())))
    assert d_recovered.severity == Severity.NORMAL


def test_duplicate_idempotency_key_returns_original_result(svc):
    key = str(uuid.uuid4())
    d1 = svc.evaluate(_snap(idempotency_key=key, exposure="0.2"))
    # different (fresh) inputs, same key - must return original NORMAL decision
    d2 = svc.evaluate(_snap(idempotency_key=key, exposure="0.99"))
    assert d1.id == d2.id
    assert d2.severity == Severity.NORMAL

    count = svc._conn.execute("SELECT COUNT(*) FROM risk_snapshots").fetchone()[0]
    assert count == 1


def test_no_policy_configured_raises():
    conn = sqlite3.connect(":memory:")
    s = LiveCapitalGuardEngineService(conn)
    with pytest.raises(CapitalGuardError, match="NO_POLICY_CONFIGURED"):
        s.evaluate(_snap(portfolio_id="NO-POLICY"))


def test_get_decision_roundtrip(svc):
    d = svc.evaluate(_snap(exposure="0.55"))
    fetched = svc.get_decision(d.id)
    assert fetched.severity == Severity.WARNING
    assert len(fetched.breaches) == 1


def test_health(svc):
    assert svc.health()["status"] == "OK"
