"""
Tests for Module 481 - Position Sizing Production Engine
(app/risk/position_sizing.py). See that module's docstring for the DPR
source section (15 + the exact Section 22 algorithm) and implementation
assumptions.
"""
import sqlite3
import uuid
from decimal import Decimal

import pytest

from app.risk.position_sizing import (
    PositionSizingProductionEngineService,
    PositionSizingRequest,
    size_position,
)


# --- direct tests of the Section 22 algorithm (size_position) --------------

def test_capital_risk_allowed_formula():
    # AC-481-01: Capital Risk Allowed = Account Equity x Risk Percentage.
    d = size_position(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    assert d.approved
    assert d.data["capital_risk_allowed"] == "4000.00"


def test_raw_units_formula():
    # AC-481-02: Position Size = Capital Risk Allowed / Stop Loss Amount.
    d = size_position(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    assert Decimal(d.data["raw_units"]) == Decimal("400")
    assert Decimal(d.data["final_qty"]) == Decimal("400")


def test_poor_liquidity_reduces_size_even_with_high_confidence():
    # AC-481-03.
    high_liquidity = size_position(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    poor_liquidity = size_position(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="0.2", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    assert float(poor_liquidity.data["final_qty"]) < float(high_liquidity.data["final_qty"])


def test_factor_above_one_is_rejected_not_treated_as_enlarger():
    d = size_position(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1.5", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    assert not d.approved
    assert d.reason_code == "FACTOR_OUT_OF_RANGE"


def test_adjustment_never_enlarges_raw_size():
    # all factors at 1.0 (max, no reduction) - adjusted must equal raw, not exceed it
    d = size_position(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    assert Decimal(d.data["adjusted_units"]) == Decimal(d.data["raw_units"])


def test_lot_size_rounds_down():
    d = size_position(
        equity="10000", risk_pct="0.01", stop_loss_per_unit="1",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="75", max_qty="1000000",
    )
    # raw_units = 100/1 = 100; 100 // 75 = 1 lot -> 75
    assert d.approved
    assert d.data["final_qty"] == "75"


def test_max_qty_caps_size():
    d = size_position(
        equity="4000000", risk_pct="0.5", stop_loss_per_unit="1",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="500",
    )
    assert d.approved
    assert d.data["final_qty"] == "500"


def test_size_below_minimum_denied():
    d = size_position(
        equity="1000", risk_pct="0.001", stop_loss_per_unit="100",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="50", max_qty="1000000",
    )
    assert not d.approved
    assert d.reason_code == "SIZE_BELOW_MINIMUM"


@pytest.mark.parametrize(
    "kwargs,reason_code",
    [
        (dict(equity="0"), "EQUITY_NON_POSITIVE"),
        (dict(equity="-1"), "EQUITY_NON_POSITIVE"),
        (dict(risk_pct="0"), "RISK_PCT_OUT_OF_RANGE"),
        (dict(risk_pct="1.1"), "RISK_PCT_OUT_OF_RANGE"),
        (dict(stop_loss_per_unit="0"), "STOP_INVALID"),
        (dict(lot_size="0"), "LOT_SIZE_INVALID"),
    ],
)
def test_invalid_inputs_are_denied_with_stable_reason_codes(kwargs, reason_code):
    base = dict(
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
    )
    base.update(kwargs)
    d = size_position(**base)
    assert not d.approved
    assert d.reason_code == reason_code


# --- service-layer tests: persistence, idempotency --------------------------

@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    return PositionSizingProductionEngineService(conn)


def _req(**overrides):
    base = dict(
        symbol="RELIANCE.NS",
        equity="400000", risk_pct="0.01", stop_loss_per_unit="10",
        confidence="1", liquidity="1", volatility="1", exposure="1",
        lot_size="1", max_qty="1000000",
        correlation_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return PositionSizingRequest(**base)


def test_evaluate_persists_decision_and_equity_snapshot(svc):
    req = _req()
    d = svc.evaluate(req)
    assert d.approved
    decision_id = d.data["decision_id"]

    fetched = svc.get_decision(decision_id)
    assert fetched.approved
    assert fetched.reason_code == "OK"

    snap = svc._conn.execute(
        "SELECT equity FROM account_equity_snapshots WHERE decision_id = ?", (decision_id,)
    ).fetchone()
    assert snap is not None
    assert snap[0] == "400000"


def test_duplicate_idempotency_key_returns_original_result(svc):
    key = str(uuid.uuid4())
    req1 = _req(idempotency_key=key, symbol="TCS.NS")
    d1 = svc.evaluate(req1)

    # Even with different (fresh) market inputs, the same idempotency_key
    # must return the ORIGINAL decision, not re-evaluate.
    req2 = _req(idempotency_key=key, symbol="TCS.NS", equity="999999999")
    d2 = svc.evaluate(req2)

    assert d1.data["decision_id"] == d2.data["decision_id"]
    assert d1.data["final_qty"] == d2.data["final_qty"]

    count = svc._conn.execute("SELECT COUNT(*) FROM position_sizing_decisions").fetchone()[0]
    assert count == 1


def test_health(svc):
    assert svc.health()["status"] == "OK"
