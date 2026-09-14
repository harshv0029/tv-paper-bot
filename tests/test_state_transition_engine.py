"""
Tests for Module 478 - State Transition Governance Engine
(app/orchestrator/state_machine.py). See that module's docstring for the
DPR source section and implementation assumptions.
"""
import sqlite3

import pytest

from app.core.enums import SystemState
from app.orchestrator.state_machine import (
    StateTransitionError,
    StateTransitionService,
    TransitionContext,
)


@pytest.fixture
def svc():
    conn = sqlite3.connect(":memory:")
    return StateTransitionService(conn)


def test_fresh_engine_starts_initialising(svc):
    assert svc.current() == SystemState.INITIALISING


def test_valid_transition_succeeds_and_bumps_version(svc):
    rec = svc.transition(
        SystemState.DATA_LOADING, reason_code="validation_passed", ctx=TransitionContext()
    )
    assert rec.from_state == SystemState.INITIALISING
    assert rec.to_state == SystemState.DATA_LOADING
    assert rec.version == 2
    assert svc.current() == SystemState.DATA_LOADING

    row = svc._conn.execute("SELECT COUNT(*) FROM state_transition_log").fetchone()
    assert row[0] == 1
    row = svc._conn.execute("SELECT COUNT(*) FROM state_transition_outbox").fetchone()
    assert row[0] == 1


def test_disallowed_edge_is_rejected(svc):
    with pytest.raises(StateTransitionError, match="EDGE_NOT_ALLOWED"):
        svc.transition(
            SystemState.ORDER_EXECUTION, reason_code="skip_ahead", ctx=TransitionContext()
        )
    # state must not have moved
    assert svc.current() == SystemState.INITIALISING


def test_guard_ok_false_blocks_an_otherwise_valid_edge(svc):
    with pytest.raises(StateTransitionError, match="GUARD_FAILED"):
        svc.transition(
            SystemState.DATA_LOADING,
            reason_code="attempt",
            ctx=TransitionContext(guard_ok=False),
        )
    assert svc.current() == SystemState.INITIALISING


def _walk_to_order_generation(svc):
    ctx = TransitionContext()
    svc.transition(SystemState.DATA_LOADING, reason_code="r", ctx=ctx)
    svc.transition(SystemState.DATA_VALIDATION, reason_code="r", ctx=ctx)
    svc.transition(SystemState.MARKET_ANALYSIS, reason_code="r", ctx=ctx)
    svc.transition(SystemState.RISK_CHECK, reason_code="r", ctx=ctx)
    svc.transition(SystemState.OPPORTUNITY_ANALYSIS, reason_code="r", ctx=ctx)
    svc.transition(SystemState.PORTFOLIO_APPROVAL, reason_code="r", ctx=ctx)
    svc.transition(SystemState.ORDER_GENERATION, reason_code="r", ctx=ctx)


def test_order_execution_requires_all_four_flags(svc):
    _walk_to_order_generation(svc)
    with pytest.raises(StateTransitionError, match="ORDER_EXECUTION_GUARD_FAILED"):
        svc.transition(
            SystemState.ORDER_EXECUTION,
            reason_code="orders_created",
            ctx=TransitionContext(
                trading_enabled=True,
                live_orders_permitted=True,
                risk_approval_valid=True,
                broker_session_healthy=False,  # missing
            ),
        )
    assert svc.current() == SystemState.ORDER_GENERATION


def test_order_execution_succeeds_with_all_flags(svc):
    _walk_to_order_generation(svc)
    rec = svc.transition(
        SystemState.ORDER_EXECUTION,
        reason_code="orders_created",
        ctx=TransitionContext(
            trading_enabled=True,
            live_orders_permitted=True,
            risk_approval_valid=True,
            broker_session_healthy=True,
        ),
    )
    assert rec.to_state == SystemState.ORDER_EXECUTION


def _force_into_broker_failure(svc):
    ctx = TransitionContext()
    _walk_to_order_generation(svc)
    svc.transition(
        SystemState.ORDER_EXECUTION,
        reason_code="orders_created",
        ctx=TransitionContext(
            trading_enabled=True,
            live_orders_permitted=True,
            risk_approval_valid=True,
            broker_session_healthy=True,
        ),
    )
    svc.transition(SystemState.BROKER_FAILURE, reason_code="broker_down", ctx=ctx)


def test_broker_failure_recovery_requires_reconnect_and_reconciliation(svc):
    _force_into_broker_failure(svc)
    with pytest.raises(StateTransitionError, match="BROKER_RECOVERY_INCOMPLETE"):
        svc.transition(
            SystemState.RISK_CHECK,
            reason_code="attempt_resume",
            ctx=TransitionContext(reconnect_test_passed=True, reconciliation_passed=False),
        )
    assert svc.current() == SystemState.BROKER_FAILURE


def test_broker_failure_recovery_succeeds_with_both_checks(svc):
    _force_into_broker_failure(svc)
    rec = svc.transition(
        SystemState.RISK_CHECK,
        reason_code="resumed",
        ctx=TransitionContext(reconnect_test_passed=True, reconciliation_passed=True),
    )
    assert rec.to_state == SystemState.RISK_CHECK


def test_broker_failure_cannot_jump_directly_to_order_execution_or_system_ready(svc):
    _force_into_broker_failure(svc)
    for target in (SystemState.ORDER_EXECUTION, SystemState.SYSTEM_READY):
        with pytest.raises(StateTransitionError, match="EDGE_NOT_ALLOWED"):
            svc.transition(
                target,
                reason_code="attempt_skip",
                ctx=TransitionContext(
                    reconnect_test_passed=True,
                    reconciliation_passed=True,
                    trading_enabled=True,
                    live_orders_permitted=True,
                    risk_approval_valid=True,
                    broker_session_healthy=True,
                ),
            )


def test_human_override_resume_requires_privileged_actor_and_checklist(svc):
    ctx = TransitionContext()
    svc.transition(
        SystemState.CAPITAL_PROTECTION_MODE, reason_code="validation_failed", ctx=ctx
    )
    svc.transition(SystemState.HUMAN_OVERRIDE_REQUIRED, reason_code="no_auto_recovery", ctx=ctx)

    with pytest.raises(StateTransitionError, match="OVERRIDE_RESUME_UNAUTHORIZED"):
        svc.transition(SystemState.INITIALISING, reason_code="resume", ctx=ctx)

    rec = svc.transition(
        SystemState.INITIALISING,
        reason_code="resume",
        ctx=TransitionContext(privileged_actor="ops_lead", validation_checklist_id="chk-1"),
    )
    assert rec.to_state == SystemState.INITIALISING


def test_current_maps_unrecognized_persisted_state_to_human_override_required(svc):
    svc._conn.execute(
        "UPDATE system_state_current SET state = 'SOME_GARBAGE_STATE' WHERE id = 1"
    )
    assert svc.current() == SystemState.HUMAN_OVERRIDE_REQUIRED


def test_force_protection_bypasses_matrix_from_any_state(svc):
    # DATA_LOADING has no direct edge to CAPITAL_PROTECTION_MODE in the
    # normal matrix - force_protection must still work.
    svc.transition(SystemState.DATA_LOADING, reason_code="r", ctx=TransitionContext())
    rec = svc.force_protection(reason_code="live_guard_breach", ctx=TransitionContext())
    assert rec.to_state == SystemState.CAPITAL_PROTECTION_MODE
    assert rec.from_state == SystemState.DATA_LOADING
    assert svc.current() == SystemState.CAPITAL_PROTECTION_MODE


def test_full_happy_path_cycle(svc):
    ctx = TransitionContext()
    sequence = [
        SystemState.DATA_LOADING,
        SystemState.DATA_VALIDATION,
        SystemState.MARKET_ANALYSIS,
        SystemState.RISK_CHECK,
        SystemState.OPPORTUNITY_ANALYSIS,
        SystemState.PORTFOLIO_APPROVAL,
        SystemState.ORDER_GENERATION,
    ]
    for state in sequence:
        svc.transition(state, reason_code="cycle", ctx=ctx)

    svc.transition(
        SystemState.ORDER_EXECUTION,
        reason_code="cycle",
        ctx=TransitionContext(
            trading_enabled=True,
            live_orders_permitted=True,
            risk_approval_valid=True,
            broker_session_healthy=True,
        ),
    )
    svc.transition(SystemState.POSITION_MONITORING, reason_code="cycle", ctx=ctx)
    svc.transition(SystemState.POST_TRADE_ANALYSIS, reason_code="cycle", ctx=ctx)
    svc.transition(SystemState.LEARNING_UPDATE, reason_code="cycle", ctx=ctx)
    rec = svc.transition(SystemState.SYSTEM_READY, reason_code="cycle", ctx=ctx)
    assert rec.to_state == SystemState.SYSTEM_READY
    assert rec.version == 13  # 1 initial + 12 transitions

    log_count = svc._conn.execute(
        "SELECT COUNT(*) FROM state_transition_log"
    ).fetchone()[0]
    assert log_count == 12
