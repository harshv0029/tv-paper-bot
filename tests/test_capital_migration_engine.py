"""
Tests for Module 483 - Capital Migration Policy Engine
(app/portfolio/capital_migration.py). See that module's docstring for the
DPR source section (17) and implementation assumptions.
"""
import sqlite3
import uuid
from decimal import Decimal

import pytest

from app.portfolio.capital_migration import CapitalMigrationPolicyEngineService, MigrationRequest


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    s = CapitalMigrationPolicyEngineService(conn)
    s.set_policy("PORT-1", config_version="v1")  # defaults: EARLY .95 / MEDIUM .60 / HIGH_WEALTH .30
    return s


def _req(**overrides):
    base = dict(
        portfolio_id="PORT-1",
        capital_stage="MEDIUM",
        realized_profit="100000",
        trading_account_equity="500000",
        already_migrated_total="0",
        liquidity_reserve="50000",
        correlation_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
    )
    base.update(overrides)
    return MigrationRequest(**base)


def test_no_policy_configured_is_denied():
    conn = sqlite3.connect(":memory:")
    s = CapitalMigrationPolicyEngineService(conn)
    d = s.recommend(_req(portfolio_id="NO-POLICY"))
    assert not d.approved
    assert d.reason_code == "NO_POLICY_CONFIGURED"


def test_unknown_capital_stage_rejected(svc):
    d = svc.recommend(_req(capital_stage="NONSENSE"))
    assert not d.approved
    assert d.reason_code == "UNKNOWN_CAPITAL_STAGE"


def test_medium_stage_recommends_excess_over_60pct_retention(svc):
    # total_wealth = 500000; target = 500000*0.60 = 300000; excess = 200000
    # capped by realized_profit=100000 -> recommend 100000
    d = svc.recommend(_req(trading_account_equity="500000", realized_profit="100000"))
    assert d.approved
    assert Decimal(d.data["recommended_amount"]) == Decimal("100000")


def test_never_migrate_more_than_realized_profit(svc):
    # AC-483-03: excess is huge (400000) but realized_profit only 10000 -
    # recommendation must be capped at 10000, not 400000.
    d = svc.recommend(_req(trading_account_equity="500000", realized_profit="10000",
                            liquidity_reserve="0"))
    assert d.approved
    assert Decimal(d.data["recommended_amount"]) == Decimal("10000")


def test_early_stage_retains_almost_everything(svc):
    # EARLY retention 0.95: target = 500000*0.95=475000; excess=25000
    d = svc.recommend(_req(capital_stage="EARLY", trading_account_equity="500000",
                            realized_profit="100000", liquidity_reserve="0"))
    assert Decimal(d.data["recommended_amount"]) == Decimal("25000")


def test_high_wealth_stage_recommends_more_migration_than_early(svc):
    early = svc.recommend(_req(idempotency_key=str(uuid.uuid4()), capital_stage="EARLY",
                                trading_account_equity="500000", realized_profit="1000000",
                                liquidity_reserve="0"))
    high = svc.recommend(_req(idempotency_key=str(uuid.uuid4()), capital_stage="HIGH_WEALTH",
                               trading_account_equity="500000", realized_profit="1000000",
                               liquidity_reserve="0"))
    # AC-483-02: high wealth prioritizes preservation - recommends migrating MORE.
    assert Decimal(high.data["recommended_amount"]) > Decimal(early.data["recommended_amount"])


def test_liquidity_reserve_caps_recommendation(svc):
    # trading_account_equity=500000, liquidity_reserve=480000 -> can migrate at most 20000
    # even though stage/profit math would allow much more.
    d = svc.recommend(_req(capital_stage="HIGH_WEALTH", trading_account_equity="500000",
                            realized_profit="1000000", liquidity_reserve="480000"))
    assert Decimal(d.data["recommended_amount"]) == Decimal("20000")


def test_no_migration_needed_when_no_realized_profit(svc):
    # excess exists (retention < 1 always leaves some), but zero realized
    # profit means nothing is eligible to migrate (AC-483-03).
    d = svc.recommend(_req(capital_stage="EARLY", trading_account_equity="100000",
                            realized_profit="0", liquidity_reserve="0"))
    assert not d.approved
    assert d.reason_code == "NO_MIGRATION_NEEDED"


def test_negative_inputs_rejected(svc):
    d = svc.recommend(_req(trading_account_equity="-1"))
    assert not d.approved
    assert d.reason_code == "NEGATIVE_INPUT_REJECTED"


def test_duplicate_idempotency_key_returns_original(svc):
    key = str(uuid.uuid4())
    d1 = svc.recommend(_req(idempotency_key=key, trading_account_equity="500000"))
    d2 = svc.recommend(_req(idempotency_key=key, trading_account_equity="999999"))
    assert d1.data.get("migration_id") == d2.data.get("migration_id")


def test_approve_flow(svc):
    d = svc.recommend(_req())
    assert d.approved
    migration_id = d.data["migration_id"]

    approved = svc.approve(migration_id, approved_by="ops_lead")
    assert approved.approved

    fetched = svc.get_decision(migration_id)
    assert fetched.data["status"] == "APPROVED"

    wealth_row = svc._conn.execute(
        "SELECT amount FROM wealth_allocations WHERE migration_id = ?", (migration_id,)
    ).fetchone()
    assert wealth_row is not None


def test_approve_twice_rejected(svc):
    d = svc.recommend(_req())
    svc.approve(d.data["migration_id"], approved_by="ops_lead")
    second = svc.approve(d.data["migration_id"], approved_by="ops_lead")
    assert not second.approved
    assert second.reason_code == "ALREADY_APPROVED"


def test_approve_a_no_migration_needed_recommendation_rejected(svc):
    d = svc.recommend(_req(capital_stage="EARLY", trading_account_equity="100000",
                            realized_profit="0", liquidity_reserve="0"))
    assert not d.approved
    # NO_MIGRATION_NEEDED recommendations still get an id but cannot be approved
    # (no separate migration_id was created since decision.data only has recommended_amount)
    row = svc._conn.execute("SELECT id FROM capital_migrations ORDER BY created_at DESC LIMIT 1").fetchone()
    result = svc.approve(row[0], approved_by="ops_lead")
    assert not result.approved
    assert result.reason_code == "CANNOT_APPROVE_DENIED_RECOMMENDATION"


def test_approve_unknown_migration(svc):
    d = svc.approve("does-not-exist", approved_by="ops_lead")
    assert not d.approved
    assert d.reason_code == "MIGRATION_NOT_FOUND"


def test_health(svc):
    assert svc.health()["status"] == "OK"
