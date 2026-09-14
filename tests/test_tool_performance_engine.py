"""
Tests for Module 484 - Tool Performance Memory Engine
(app/governance/tool_performance.py). See that module's docstring for the
DPR source section (18) and implementation assumptions.
"""
import sqlite3
import uuid

import pytest

from app.governance.tool_performance import ToolEvaluationRequest, ToolPerformanceMemoryEngineService


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    return ToolPerformanceMemoryEngineService(conn, review_period_days=30)


def _req(**overrides):
    base = dict(
        tool_id="tool-1", tool_name="Backtest SaaS", cost="100",
        expected_benefit="150", actual_benefit=None,
        correlation_id=str(uuid.uuid4()), idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return ToolEvaluationRequest(**base)


def test_pre_commitment_approved_when_expected_benefit_exceeds_cost(svc):
    d = svc.evaluate(_req(expected_benefit="150", cost="100"))
    assert d.approved
    assert d.data["decision"] == "APPROVED_TRIAL"
    assert d.data["renewal_review_date"] is not None


def test_pre_commitment_denied_when_expected_benefit_does_not_exceed_cost(svc):
    d = svc.evaluate(_req(expected_benefit="80", cost="100"))
    assert not d.approved
    assert d.data["decision"] == "DENIED_TRIAL"
    assert d.reason_code == "NEW_COST_LACKS_MEASURABLE_IMPROVEMENT"


def test_post_measurement_keep_when_actual_benefit_exceeds_cost(svc):
    d = svc.evaluate(_req(cost="100", actual_benefit="200"))
    assert d.approved
    assert d.data["decision"] == "KEEP"
    assert d.data["roi"] == "1"


def test_post_measurement_remove_when_actual_benefit_does_not_justify_cost(svc):
    d = svc.evaluate(_req(cost="100", actual_benefit="50"))
    assert not d.approved
    assert d.data["decision"] == "REMOVE"
    assert d.reason_code == "REALIZED_BENEFIT_DOES_NOT_JUSTIFY_COST"


def test_cost_non_positive_rejected(svc):
    d = svc.evaluate(_req(cost="0"))
    assert not d.approved
    assert d.reason_code == "COST_NON_POSITIVE"


def test_record_replace_decision_persists_for_audit(svc):
    d = svc.record_replace_decision("tool-1", reason="cheaper alternative found", correlation_id=str(uuid.uuid4()))
    assert not d.approved
    assert d.data["decision"] == "REPLACE"
    row = svc._conn.execute(
        "SELECT decision, reason FROM tool_decisions WHERE id = ?", (d.data["decision_id"],)
    ).fetchone()
    assert row[0] == "REPLACE"
    assert "cheaper alternative" in row[1]


def test_duplicate_idempotency_key_returns_original(svc):
    key = str(uuid.uuid4())
    d1 = svc.evaluate(_req(idempotency_key=key, cost="100", expected_benefit="150"))
    d2 = svc.evaluate(_req(idempotency_key=key, cost="999999", expected_benefit="1"))
    assert d1.data["decision_id"] == d2.data["decision_id"]
    assert d2.data["decision"] == "APPROVED_TRIAL"  # not re-evaluated against the "bad" second request


def test_decision_evidence_retained_across_multiple_evaluations(svc):
    # AC-484-02: decision evidence is retained for future procurement comparisons.
    svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), tool_id="tool-1", actual_benefit=None))
    svc.evaluate(_req(idempotency_key=str(uuid.uuid4()), tool_id="tool-1", actual_benefit="200", cost="100"))
    count = svc._conn.execute("SELECT COUNT(*) FROM tool_decisions WHERE tool_id = 'tool-1'").fetchone()[0]
    assert count == 2


def test_get_decision_roundtrip(svc):
    d = svc.evaluate(_req())
    fetched = svc.get_decision(d.data["decision_id"])
    assert fetched.approved
    assert fetched.data["decision"] == "APPROVED_TRIAL"


def test_health(svc):
    assert svc.health()["status"] == "OK"
