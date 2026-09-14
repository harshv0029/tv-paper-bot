"""
Tests for Module 480 - Risk Budget Management Engine
(app/risk/risk_budget.py). See that module's docstring for the DPR source
section (14), the derived allocation formula, and implementation
assumptions.
"""
import sqlite3
import uuid
from decimal import Decimal

import pytest

from app.risk.risk_budget import RiskBudgetManagementEngineService, RiskBudgetRequest


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    s = RiskBudgetManagementEngineService(conn)
    s.set_policy("PORT-1", "0.06", config_version="v1")  # 6% portfolio risk limit
    return s


def _req(**overrides):
    base = dict(
        portfolio_id="PORT-1",
        strategy_id="strat-a",
        requested_risk_pct="0.02",
        confidence="1",
        correlation_factor="0",
        drawdown_factor="0",
        correlation_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return RiskBudgetRequest(**base)


def test_no_policy_configured_is_denied():
    conn = sqlite3.connect(":memory:")
    s = RiskBudgetManagementEngineService(conn)
    d = s.evaluate(_req(portfolio_id="NO-POLICY"))
    assert not d.approved
    assert d.reason_code == "NO_POLICY_CONFIGURED"


def test_full_confidence_no_reduction_allocates_requested_amount(svc):
    d = svc.evaluate(_req(requested_risk_pct="0.02", confidence="1",
                           correlation_factor="0", drawdown_factor="0"))
    assert d.approved
    assert Decimal(d.data["allocated_pct"]) == Decimal("0.02")


def test_correlation_and_drawdown_reduce_nominal_allocation(svc):
    # AC-480-03: correlation and drawdown can reduce a nominal allocation.
    full = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s1",
                              requested_risk_pct="0.02", correlation_factor="0", drawdown_factor="0"))
    reduced = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s2",
                                 requested_risk_pct="0.02", correlation_factor="0.5", drawdown_factor="0.5"))
    assert Decimal(reduced.data["allocated_pct"]) < Decimal(full.data["allocated_pct"])
    # 0.02 * 1 * (1-0.5) * (1-0.5) = 0.005
    assert Decimal(reduced.data["allocated_pct"]) == Decimal("0.005")


def test_no_strategy_can_consume_unlimited_risk(svc):
    # AC-480-01: requesting far more than the portfolio limit is capped,
    # never granted in full.
    d = svc.evaluate(_req(requested_risk_pct="0.9", confidence="1"))
    assert d.approved
    assert Decimal(d.data["allocated_pct"]) <= Decimal("0.06")


def test_total_allocated_active_risk_cannot_exceed_portfolio_policy(svc):
    # AC-480-02: two strategies each asking for 4% against a 6% portfolio
    # limit - second must be capped to the remaining 2%, not granted 4%.
    d1 = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s1", requested_risk_pct="0.04"))
    d2 = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s2", requested_risk_pct="0.04"))
    assert d1.approved
    assert d2.approved
    assert Decimal(d1.data["allocated_pct"]) == Decimal("0.04")
    assert Decimal(d2.data["allocated_pct"]) == Decimal("0.02")  # capped to remaining capacity

    usage = svc._conn.execute(
        "SELECT allocated_pct FROM risk_budget_usage WHERE portfolio_id = 'PORT-1'"
    ).fetchone()
    assert Decimal(usage[0]) == Decimal("0.06")


def test_third_request_denied_once_budget_exhausted(svc):
    svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s1", requested_risk_pct="0.03"))
    svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s2", requested_risk_pct="0.03"))
    d3 = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s3", requested_risk_pct="0.01"))
    assert not d3.approved
    assert d3.reason_code == "NO_RISK_CAPACITY_AVAILABLE"


def test_duplicate_idempotency_key_returns_original_result(svc):
    key = str(uuid.uuid4())
    d1 = svc.evaluate(_req(idempotency_key=key, requested_risk_pct="0.02"))
    d2 = svc.evaluate(_req(idempotency_key=key, requested_risk_pct="0.05"))  # different amount, ignored
    assert d1.data["allocation_id"] == d2.data["allocation_id"]

    usage = svc._conn.execute(
        "SELECT allocated_pct FROM risk_budget_usage WHERE portfolio_id = 'PORT-1'"
    ).fetchone()
    assert Decimal(usage[0]) == Decimal("0.02")  # only counted once


def test_release_frees_capacity_for_reuse(svc):
    d1 = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s1", requested_risk_pct="0.05"))
    assert d1.approved

    release = svc.release(d1.data["allocation_id"], reason_code="order_cancelled")
    assert release.approved

    usage = svc._conn.execute(
        "SELECT allocated_pct FROM risk_budget_usage WHERE portfolio_id = 'PORT-1'"
    ).fetchone()
    assert Decimal(usage[0]) == Decimal("0")

    d2 = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), strategy_id="s2", requested_risk_pct="0.05"))
    assert d2.approved
    assert Decimal(d2.data["allocated_pct"]) == Decimal("0.05")


def test_release_twice_is_rejected(svc):
    d1 = svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), requested_risk_pct="0.02"))
    svc.release(d1.data["allocation_id"], reason_code="cancelled")
    second = svc.release(d1.data["allocation_id"], reason_code="cancelled_again")
    assert not second.approved
    assert second.reason_code == "ALLOCATION_NOT_ACTIVE"


@pytest.mark.parametrize(
    "kwargs,reason_code",
    [
        (dict(requested_risk_pct="0"), "REQUESTED_PCT_NON_POSITIVE"),
        (dict(requested_risk_pct="-0.01"), "REQUESTED_PCT_NON_POSITIVE"),
        (dict(confidence="1.5"), "FACTOR_OUT_OF_RANGE"),
        (dict(correlation_factor="-0.1"), "FACTOR_OUT_OF_RANGE"),
        (dict(drawdown_factor="2"), "FACTOR_OUT_OF_RANGE"),
    ],
)
def test_invalid_inputs_denied_with_stable_reason_codes(svc, kwargs, reason_code):
    d = svc.evaluate(_req(**kwargs))
    assert not d.approved
    assert d.reason_code == reason_code


def test_get_decision_roundtrip(svc):
    d = svc.evaluate(_req())
    fetched = svc.get_decision(d.data["allocation_id"])
    assert fetched.approved
    assert fetched.data["status"] == "ACTIVE"


def test_health(svc):
    assert svc.health()["status"] == "OK"
