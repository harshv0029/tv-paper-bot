"""
Tests for Module 486 - Production Testing Engine
(app/governance/production_testing.py). See that module's docstring for
the DPR source section (20) and implementation assumptions.
"""
import sqlite3
import uuid

import pytest

from app.governance.production_testing import ProductionTestingEngineService, ProductionTestRunRequest


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    return ProductionTestingEngineService(conn)


def _passing_results():
    return [
        {"test_name": "risk_x_portfolio_x_execution", "category": "risk_portfolio_execution_integration", "passed": True},
        {"test_name": "broker_crash_recovery", "category": "crash_recovery", "passed": True},
    ]


def _req(**overrides):
    base = dict(
        code_version="v1.2.3", test_suite="full",
        results=_passing_results(), fault_scenarios=["broker_timeout"],
        correlation_id=str(uuid.uuid4()), idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return ProductionTestRunRequest(**base)


def test_gate_passes_when_both_required_categories_covered_and_no_failures(svc):
    d = svc.evaluate(_req())
    assert d.approved
    assert d.data["gate_result"] == "PASS"


def test_gate_fails_on_any_failing_result(svc):
    results = _passing_results()
    results.append({"test_name": "flaky", "category": "misc", "passed": False})
    d = svc.evaluate(_req(results=results))
    assert not d.approved
    assert d.reason_code == "TEST_FAILURES_PRESENT"


def test_gate_fails_when_risk_portfolio_execution_integration_not_covered(svc):
    results = [{"test_name": "broker_crash_recovery", "category": "crash_recovery", "passed": True}]
    d = svc.evaluate(_req(results=results))
    assert not d.approved
    assert d.reason_code == "REQUIRED_CATEGORY_NOT_COVERED"


def test_gate_fails_when_crash_recovery_not_covered(svc):
    results = [{"test_name": "r_p_e", "category": "risk_portfolio_execution_integration", "passed": True}]
    d = svc.evaluate(_req(results=results))
    assert not d.approved
    assert d.reason_code == "REQUIRED_CATEGORY_NOT_COVERED"


def test_a_listed_but_never_passing_fault_scenario_does_not_satisfy_crash_recovery(svc):
    # crash_recovery category present but its result FAILED - listing the
    # fault_scenario name alone must not count as "tested".
    results = [
        {"test_name": "r_p_e", "category": "risk_portfolio_execution_integration", "passed": True},
        {"test_name": "broker_crash_recovery", "category": "crash_recovery", "passed": False},
    ]
    d = svc.evaluate(_req(results=results, fault_scenarios=["broker_timeout"]))
    assert not d.approved


def test_persists_results_and_fault_scenarios(svc):
    d = svc.evaluate(_req())
    run_id = d.data["run_id"]
    result_count = svc._conn.execute("SELECT COUNT(*) FROM test_results WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert result_count == 2
    scenario_count = svc._conn.execute(
        "SELECT COUNT(*) FROM fault_scenarios WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    assert scenario_count == 1
    gate_row = svc._conn.execute(
        "SELECT gate_result FROM release_quality_gates WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert gate_row[0] == "PASS"


def test_duplicate_idempotency_key_returns_original(svc):
    key = str(uuid.uuid4())
    d1 = svc.evaluate(_req(idempotency_key=key))
    d2 = svc.evaluate(_req(idempotency_key=key, results=[]))  # would otherwise fail
    assert d1.data["run_id"] == d2.data["run_id"]
    assert d2.approved  # returns original PASS, not re-evaluated against empty results


def test_get_decision_roundtrip(svc):
    d = svc.evaluate(_req())
    fetched = svc.get_decision(d.data["run_id"])
    assert fetched.approved


def test_health(svc):
    assert svc.health()["status"] == "OK"
