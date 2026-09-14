"""
Module 478 - State Transition Governance Engine.

Source: AI Trading Platform Bible V63.0, Section 12 (states, 12.1 allowed
transition matrix, 12.2 implementation interface, 12.3 state-machine
invariants). This is Phase 1 of the DPR implementation - foundational
only, and NOT wired into main.py's live webhook/order-placement path yet.
See docs/dpr_v63_phase1_notes.md for overall scope/phasing.

IMPLEMENTATION ASSUMPTIONS (source doc did not fix these; DERIVED/
IMPLEMENTATION ASSUMPTION per the DPR's own Section 1.1 classification):

  - Persistence is SQLite, not PostgreSQL. Production (main.py) runs on
    SQLite today; migrating the database engine is its own separate,
    high-risk infra project the user explicitly deferred (2026-09-14) in
    favor of adapting this spec to SQLite. UUID primary keys are stored as
    TEXT; TIMESTAMPTZ becomes a float unix timestamp (matches main.py's
    own convention, e.g. real_trading_control.updated_at).
  - "SELECT ... FOR UPDATE" (12.2 step 1) is realized as a SQLite
    `BEGIN IMMEDIATE` write-lock wrapping the whole
    read-current -> validate -> guards -> append-log -> update-singleton
    -> commit sequence, since SQLite has no row-level FOR UPDATE.
  - The "transactional outbox" (12.2 step 7) is a plain append-only table
    in the same DB/transaction (state_transition_outbox), not a message
    broker - there is no broker/bus anywhere in this codebase to
    integrate with. A future publisher can poll `published = 0` rows.
  - Guard evaluation itself (e.g. "analysis completed", "risk gate
    passed") is caller-supplied via TransitionContext - this engine only
    enforces the 12.1 allowed-edge matrix and the 12.3 hard invariants; it
    does not decide domain questions that belong to modules which do not
    exist in this codebase yet (Modules 480/481/482/etc., not yet built).
  - Methods are synchronous, matching this codebase's existing sqlite3
    idiom (main.py's get_db()), not the DPR's `async def` interface -
    trivial to wrap with asyncio.to_thread when/if this is wired into a
    FastAPI route.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.core.enums import SystemState

# 12.1 Allowed transition matrix: from_state -> {to_state: guard description}.
# Transcribed verbatim from the DPR's transition table (28 edges).
TRANSITION_MATRIX: dict[SystemState, dict[SystemState, str]] = {
    SystemState.INITIALISING: {
        SystemState.DATA_LOADING: "system validation passed",
        SystemState.CAPITAL_PROTECTION_MODE: "validation failed",
    },
    SystemState.DATA_LOADING: {
        SystemState.DATA_VALIDATION: "data load complete",
        SystemState.DATA_FAILURE: "load failure",
    },
    SystemState.DATA_VALIDATION: {
        SystemState.MARKET_ANALYSIS: "quality gates passed",
        SystemState.DATA_FAILURE: "invalid/stale/incomplete data",
    },
    SystemState.MARKET_ANALYSIS: {
        SystemState.RISK_CHECK: "analysis completed",
        SystemState.MODEL_FAILURE: "analysis/model failure",
    },
    SystemState.RISK_CHECK: {
        SystemState.OPPORTUNITY_ANALYSIS: "base risk gate passed",
        SystemState.RISK_BREACH: "risk gate failed",
    },
    SystemState.OPPORTUNITY_ANALYSIS: {
        SystemState.PORTFOLIO_APPROVAL: "eligible opportunity exists",
        SystemState.SYSTEM_READY: "no eligible opportunity",
    },
    SystemState.PORTFOLIO_APPROVAL: {
        SystemState.ORDER_GENERATION: "portfolio approves",
        SystemState.SYSTEM_READY: "portfolio rejects/no-op",
    },
    SystemState.ORDER_GENERATION: {
        SystemState.ORDER_EXECUTION: "valid order intents created",
        SystemState.RISK_BREACH: "pre-trade risk changed",
    },
    SystemState.ORDER_EXECUTION: {
        SystemState.POSITION_MONITORING: "orders acknowledged/known",
        SystemState.BROKER_FAILURE: "broker unavailable/unknown outcome",
    },
    SystemState.POSITION_MONITORING: {
        SystemState.POST_TRADE_ANALYSIS: "monitoring window/cycle completed",
        SystemState.RISK_BREACH: "live guard breach",
    },
    SystemState.POST_TRADE_ANALYSIS: {
        SystemState.LEARNING_UPDATE: "analysis persisted",
    },
    SystemState.LEARNING_UPDATE: {
        SystemState.SYSTEM_READY: "learning update accepted/skipped safely",
    },
    SystemState.SYSTEM_READY: {
        SystemState.DATA_LOADING: "next scheduled cycle",
    },
    SystemState.BROKER_FAILURE: {
        SystemState.RISK_CHECK: "only after reconnect test + reconciliation",
    },
    SystemState.RISK_BREACH: {
        SystemState.CAPITAL_PROTECTION_MODE: "breach severity requires protection",
    },
    SystemState.MODEL_FAILURE: {
        SystemState.HUMAN_OVERRIDE_REQUIRED: "model cannot be validated",
    },
    SystemState.CAPITAL_PROTECTION_MODE: {
        SystemState.HUMAN_OVERRIDE_REQUIRED: "automatic recovery not permitted",
    },
    SystemState.HUMAN_OVERRIDE_REQUIRED: {
        SystemState.INITIALISING: "authorized resume after validation",
    },
}


@dataclass
class TransitionContext:
    """Facts this engine cannot determine on its own - supplied by the
    caller (eventually: the CIO orchestrator / other Module 47x-48x
    engines once they exist)."""

    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    guard_ok: bool = True
    trading_enabled: bool = False
    live_orders_permitted: bool = False
    risk_approval_valid: bool = False
    broker_session_healthy: bool = False
    reconnect_test_passed: bool = False
    reconciliation_passed: bool = False
    privileged_actor: Optional[str] = None
    validation_checklist_id: Optional[str] = None


@dataclass
class TransitionDecision:
    allowed: bool
    reason_code: str
    reason: str


@dataclass
class TransitionRecord:
    id: str
    from_state: SystemState
    to_state: SystemState
    reason_code: str
    version: int
    ts: float


class StateTransitionError(Exception):
    """Raised by transition() when a transition is not allowed."""


class StateTransitionService:
    """Module 478. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        # Explicit transaction control (BEGIN IMMEDIATE / COMMIT / ROLLBACK)
        # requires autocommit mode; the sqlite3 module otherwise opens its
        # own implicit transaction ahead of the first DML statement.
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_state_current (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state_transition_log (
                id TEXT PRIMARY KEY,
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                ts REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state_transition_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        row = self._conn.execute(
            "SELECT 1 FROM system_state_current WHERE id = 1"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO system_state_current (id, state, version, updated_at) "
                "VALUES (1, ?, 1, ?)",
                (SystemState.INITIALISING.value, time.time()),
            )

    # -- 12.2 implementation interface --------------------------------------

    def current(self) -> SystemState:
        """12.3 invariant: any unrecognized persisted state maps to
        HUMAN_OVERRIDE_REQUIRED on read, and live trading stays disabled."""
        row = self._conn.execute(
            "SELECT state FROM system_state_current WHERE id = 1"
        ).fetchone()
        if row is None:
            return SystemState.HUMAN_OVERRIDE_REQUIRED
        try:
            return SystemState(row[0])
        except ValueError:
            return SystemState.HUMAN_OVERRIDE_REQUIRED

    def can_transition(
        self, from_state: SystemState, to_state: SystemState, ctx: TransitionContext
    ) -> TransitionDecision:
        edges = TRANSITION_MATRIX.get(from_state, {})
        if to_state not in edges:
            return TransitionDecision(
                False,
                "EDGE_NOT_ALLOWED",
                f"{from_state.value} -> {to_state.value} is not in the allowed "
                f"transition matrix",
            )
        if not ctx.guard_ok:
            return TransitionDecision(
                False,
                "GUARD_FAILED",
                f"caller-supplied guard for {from_state.value} -> {to_state.value} "
                f"({edges[to_state]}) was not satisfied",
            )
        # 12.3 hard invariants beyond the bare edge matrix.
        if to_state == SystemState.ORDER_EXECUTION:
            if not (
                ctx.trading_enabled
                and ctx.live_orders_permitted
                and ctx.risk_approval_valid
                and ctx.broker_session_healthy
            ):
                return TransitionDecision(
                    False,
                    "ORDER_EXECUTION_GUARD_FAILED",
                    "ORDER_EXECUTION requires trading_enabled, live_orders_permitted, "
                    "an unexpired risk approval and a healthy broker session",
                )
        if from_state == SystemState.BROKER_FAILURE and to_state == SystemState.RISK_CHECK:
            if not (ctx.reconnect_test_passed and ctx.reconciliation_passed):
                return TransitionDecision(
                    False,
                    "BROKER_RECOVERY_INCOMPLETE",
                    "BROKER_FAILURE recovery requires a passed reconnect test AND "
                    "position/cash reconciliation before RISK_CHECK",
                )
        if (
            from_state == SystemState.HUMAN_OVERRIDE_REQUIRED
            and to_state == SystemState.INITIALISING
        ):
            if not (ctx.privileged_actor and ctx.validation_checklist_id):
                return TransitionDecision(
                    False,
                    "OVERRIDE_RESUME_UNAUTHORIZED",
                    "leaving HUMAN_OVERRIDE_REQUIRED requires a privileged actor and a "
                    "persisted validation checklist id",
                )
        return TransitionDecision(True, "OK", "allowed")

    def transition(
        self, to_state: SystemState, *, reason_code: str, ctx: TransitionContext
    ) -> TransitionRecord:
        """12.2: SELECT current FOR UPDATE (-> BEGIN IMMEDIATE) -> validate
        enum/edge -> evaluate guards -> append log -> update singleton
        -> commit atomically -> emit through outbox."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT state, version FROM system_state_current WHERE id = 1"
            ).fetchone()
            if row is None:
                from_state, version = SystemState.HUMAN_OVERRIDE_REQUIRED, 1
            else:
                try:
                    from_state = SystemState(row[0])
                except ValueError:
                    from_state = SystemState.HUMAN_OVERRIDE_REQUIRED
                version = row[1]

            decision = self.can_transition(from_state, to_state, ctx)
            if not decision.allowed:
                self._conn.execute("ROLLBACK")
                raise StateTransitionError(f"{decision.reason_code}: {decision.reason}")

            record_id = str(uuid.uuid4())
            ts = time.time()
            new_version = version + 1

            self._conn.execute(
                """
                INSERT INTO state_transition_log
                    (id, from_state, to_state, reason_code, correlation_id, version, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    from_state.value,
                    to_state.value,
                    reason_code,
                    ctx.correlation_id,
                    new_version,
                    ts,
                ),
            )
            self._conn.execute(
                "UPDATE system_state_current SET state = ?, version = ?, updated_at = ? "
                "WHERE id = 1",
                (to_state.value, new_version, ts),
            )
            self._conn.execute(
                """
                INSERT INTO state_transition_outbox
                    (id, event_type, payload_json, ts, published)
                VALUES (?, 'state.changed', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps(
                        {
                            "from_state": from_state.value,
                            "to_state": to_state.value,
                            "reason_code": reason_code,
                            "correlation_id": ctx.correlation_id,
                            "version": new_version,
                        }
                    ),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except StateTransitionError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return TransitionRecord(record_id, from_state, to_state, reason_code, new_version, ts)

    def force_protection(self, *, reason_code: str, ctx: TransitionContext) -> TransitionRecord:
        """Emergency path: force CAPITAL_PROTECTION_MODE from ANY current
        state, bypassing the normal edge matrix (e.g. an external live
        capital guard breach that can't wait for the next scheduled cycle
        to route through RISK_BREACH). Still goes through the same durable
        log/outbox/version machinery as transition()."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT state, version FROM system_state_current WHERE id = 1"
            ).fetchone()
            if row is None:
                from_state, version = SystemState.HUMAN_OVERRIDE_REQUIRED, 1
            else:
                try:
                    from_state = SystemState(row[0])
                except ValueError:
                    from_state = SystemState.HUMAN_OVERRIDE_REQUIRED
                version = row[1]

            record_id = str(uuid.uuid4())
            ts = time.time()
            new_version = version + 1

            self._conn.execute(
                """
                INSERT INTO state_transition_log
                    (id, from_state, to_state, reason_code, correlation_id, version, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    from_state.value,
                    SystemState.CAPITAL_PROTECTION_MODE.value,
                    reason_code,
                    ctx.correlation_id,
                    new_version,
                    ts,
                ),
            )
            self._conn.execute(
                "UPDATE system_state_current SET state = ?, version = ?, updated_at = ? "
                "WHERE id = 1",
                (SystemState.CAPITAL_PROTECTION_MODE.value, new_version, ts),
            )
            self._conn.execute(
                """
                INSERT INTO state_transition_outbox
                    (id, event_type, payload_json, ts, published)
                VALUES (?, 'state.changed', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps(
                        {
                            "from_state": from_state.value,
                            "to_state": SystemState.CAPITAL_PROTECTION_MODE.value,
                            "reason_code": reason_code,
                            "correlation_id": ctx.correlation_id,
                            "version": new_version,
                            "forced": True,
                        }
                    ),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return TransitionRecord(
            record_id,
            from_state,
            SystemState.CAPITAL_PROTECTION_MODE,
            reason_code,
            new_version,
            ts,
        )
