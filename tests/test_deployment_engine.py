"""
Tests for Module 487 - Production Deployment Engine
(app/governance/deployment.py). See that module's docstring for the DPR
source section (21) and implementation assumptions.
"""
import sqlite3
import uuid

import pytest

from app.governance.deployment import ProductionDeploymentEngineService, PromotionRequest


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    return ProductionDeploymentEngineService(conn)


def _req(**overrides):
    base = dict(
        release_id="rel-1", code_version="v1.0.0", to_stage="TESTING",
        correlation_id=str(uuid.uuid4()), idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return PromotionRequest(**base)


def test_new_release_starts_at_development(svc):
    assert svc.current_stage("rel-1") is None  # not created until first promote() call


def test_development_to_testing_requires_passed_test_evidence(svc):
    d = svc.promote(_req(to_stage="TESTING"))
    assert not d.approved
    assert d.reason_code == "UNTESTED_CODE_CANNOT_PROMOTE"
    assert svc.current_stage("rel-1") == "DEVELOPMENT"


def test_development_to_testing_succeeds_with_passed_evidence(svc):
    d = svc.promote(_req(to_stage="TESTING", test_evidence={"gate_passed": True}))
    assert d.approved
    assert svc.current_stage("rel-1") == "TESTING"


def _promote_to(svc, release_id, target, **kwargs):
    """Helper: walk a release sequentially up to `target`."""
    order = ["TESTING", "PAPER_TRADING", "SMALL_CAPITAL", "PRODUCTION"]
    for stage in order:
        req_kwargs = dict(release_id=release_id, code_version="v1.0.0", to_stage=stage,
                           idempotency_key=str(uuid.uuid4()))
        if stage == "TESTING":
            req_kwargs["test_evidence"] = {"gate_passed": True}
        if stage == "PAPER_TRADING":
            pass  # TESTING -> PAPER_TRADING has no extra gate
        if stage == "SMALL_CAPITAL":
            req_kwargs["paper_trading_metrics"] = kwargs.get("paper_trading_metrics", {"trades": 50})
        if stage == "PRODUCTION":
            req_kwargs["small_capital_metrics"] = kwargs.get("small_capital_metrics", {"trades": 20})
            req_kwargs["approvals"] = kwargs.get("approvals", ["cio"])
        d = svc.promote(PromotionRequest(**req_kwargs))
        if stage == target:
            return d
        if not d.approved:
            return d  # stop early if blocked before reaching target
    return d


def test_sequential_promotion_cannot_skip_stages(svc):
    svc.promote(_req(to_stage="TESTING", test_evidence={"gate_passed": True}))
    # attempt to skip straight to SMALL_CAPITAL from TESTING
    d = svc.promote(_req(release_id="rel-1", to_stage="SMALL_CAPITAL", idempotency_key=str(uuid.uuid4())))
    assert not d.approved
    assert d.reason_code == "EDGE_NOT_ALLOWED"


def test_paper_trading_to_small_capital_requires_metrics(svc):
    _promote_to(svc, "rel-1", "PAPER_TRADING")
    d = svc.promote(PromotionRequest(release_id="rel-1", code_version="v1.0.0", to_stage="SMALL_CAPITAL",
                                      idempotency_key=str(uuid.uuid4())))
    assert not d.approved
    assert d.reason_code == "PAPER_TRADING_EVIDENCE_INSUFFICIENT"


def test_paper_trading_catastrophic_failure_blocks_promotion(svc):
    _promote_to(svc, "rel-1", "PAPER_TRADING")
    d = svc.promote(PromotionRequest(
        release_id="rel-1", code_version="v1.0.0", to_stage="SMALL_CAPITAL",
        paper_trading_metrics={"trades": 10, "catastrophic_failure": True},
        idempotency_key=str(uuid.uuid4()),
    ))
    assert not d.approved
    assert d.reason_code == "PAPER_TRADING_EVIDENCE_INSUFFICIENT"


def test_small_capital_to_production_requires_approval(svc):
    _promote_to(svc, "rel-1", "SMALL_CAPITAL")
    d = svc.promote(PromotionRequest(
        release_id="rel-1", code_version="v1.0.0", to_stage="PRODUCTION",
        small_capital_metrics={"trades": 20}, approvals=[],
        idempotency_key=str(uuid.uuid4()),
    ))
    assert not d.approved
    assert d.reason_code == "PRODUCTION_PROMOTION_REQUIRES_APPROVAL"


def test_full_sequential_promotion_to_production(svc):
    d = _promote_to(svc, "rel-1", "PRODUCTION")
    assert d.approved
    assert svc.current_stage("rel-1") == "PRODUCTION"

    approvals = svc._conn.execute(
        "SELECT approver FROM deployment_approvals WHERE release_id = 'rel-1'"
    ).fetchall()
    assert len(approvals) == 1


def test_emergency_rollback_requires_authorization(svc):
    _promote_to(svc, "rel-1", "SMALL_CAPITAL")
    d = svc.emergency_rollback("rel-1", "TESTING", reason_code="regression_found", authorized_by=None)
    assert not d.approved
    assert d.reason_code == "ROLLBACK_UNAUTHORIZED"
    assert svc.current_stage("rel-1") == "SMALL_CAPITAL"


def test_emergency_rollback_bypasses_sequential_rule(svc):
    _promote_to(svc, "rel-1", "SMALL_CAPITAL")
    d = svc.emergency_rollback("rel-1", "DEVELOPMENT", reason_code="critical_bug", authorized_by="ops_lead")
    assert d.approved
    assert svc.current_stage("rel-1") == "DEVELOPMENT"

    record = svc._conn.execute(
        "SELECT from_stage, to_stage, authorized_by FROM rollback_records WHERE release_id = 'rel-1'"
    ).fetchone()
    assert record == ("SMALL_CAPITAL", "DEVELOPMENT", "ops_lead")


def test_rollback_cannot_go_upward(svc):
    svc.promote(_req(to_stage="TESTING", test_evidence={"gate_passed": True}))
    d = svc.emergency_rollback("rel-1", "SMALL_CAPITAL", reason_code="x", authorized_by="ops_lead")
    assert not d.approved
    assert d.reason_code == "ROLLBACK_MUST_GO_DOWN"


def test_duplicate_idempotency_key_returns_original(svc):
    key = str(uuid.uuid4())
    d1 = svc.promote(_req(to_stage="TESTING", test_evidence={"gate_passed": True}, idempotency_key=key))
    d2 = svc.promote(_req(to_stage="TESTING", test_evidence={}, idempotency_key=key))
    assert d1.data["promotion_id"] == d2.data["promotion_id"]
    assert d2.approved  # original approved decision, not re-evaluated


def test_health(svc):
    assert svc.health()["status"] == "OK"
