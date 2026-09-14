"""
Module 480 - Risk Budget Management Engine.

Source: AI Trading Platform Bible V63.0, Section 14. Primary rules (SOURCE,
verbatim): "No strategy can consume unlimited risk. Total allocated active
risk cannot exceed portfolio policy. Correlation and drawdown can reduce a
nominal allocation." Inputs/outputs/tables are SOURCE; the exact allocation
FORMULA below is an IMPLEMENTATION ASSUMPTION - Section 14 does not give one
(unlike Module 481, which gets an exact algorithm in Section 22). Derived
directly from the three primary rules and the module's acceptance criteria
(AC-480-01/02/03):

    nominal_pct    = requested_risk_pct * confidence
    adjusted_pct   = nominal_pct * (1 - correlation_factor) * (1 - drawdown_factor)
    available_pct  = portfolio_risk_limit_pct - currently_allocated_pct
    final_pct      = min(adjusted_pct, available_pct)

confidence, correlation_factor and drawdown_factor are each in [0, 1] - a
correlation/drawdown factor of 0 means "no reduction", 1 means "fully
zero out this allocation", matching Section 22's "adjustment factors are
0..1 reducers, never enlargers" convention for the sibling sizing module.

Phase 2 of the DPR implementation. NOT wired into main.py's live path.
Wiring this into entry/sizing decisions requires the same bar as Module
481: full pytest green (has it) + full replay validation + explicit user
go-ahead - not done here.

IMPLEMENTATION ASSUMPTIONS (SQLite, no PostgreSQL/message broker - see
docs/dpr_v63_phase1_notes.md): UUID PKs as TEXT, TIMESTAMPTZ as float unix
timestamp, BEGIN IMMEDIATE in place of SELECT...FOR UPDATE/serializable
retry, outbox is a plain append-only table. `risk_budget_usage` is modeled
as one mutable current-usage row per portfolio (allocated_pct, version)
plus the append-only `risk_budget_allocations` log - the same
singleton-plus-log pattern Module 478 already uses, rather than summing
the log on every read.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.core.decisions import EngineDecision


@dataclass
class RiskBudgetRequest:
    portfolio_id: str
    strategy_id: str
    requested_risk_pct: str
    confidence: str
    correlation_factor: str
    drawdown_factor: str
    correlation_id: str
    idempotency_key: str


class RiskBudgetManagementEngineService:
    """Module 480. See module docstring for the derived formula and
    implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_budget_policies (
                portfolio_id TEXT PRIMARY KEY,
                portfolio_risk_limit_pct TEXT NOT NULL,
                config_version TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_budget_usage (
                portfolio_id TEXT PRIMARY KEY,
                allocated_pct TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_budget_allocations (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                portfolio_id TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                status TEXT NOT NULL,  -- ACTIVE | RELEASED
                approved INTEGER NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                allocated_pct TEXT NOT NULL,
                config_version TEXT NOT NULL,
                request_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                released_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS correlation_snapshots (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                correlation_factor TEXT NOT NULL,
                ts REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_budget_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def set_policy(
        self, portfolio_id: str, portfolio_risk_limit_pct: str, config_version: str
    ) -> None:
        """Config is versioned and must be persisted with every decision
        (15.3/'Persist the exact configuration version used for each
        decision' - identical wording repeated for every module in the
        DPR, including this one)."""
        self._conn.execute(
            """
            INSERT INTO risk_budget_policies (portfolio_id, portfolio_risk_limit_pct, config_version, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(portfolio_id) DO UPDATE SET
                portfolio_risk_limit_pct = excluded.portfolio_risk_limit_pct,
                config_version = excluded.config_version,
                updated_at = excluded.updated_at
            """,
            (portfolio_id, str(portfolio_risk_limit_pct), config_version, time.time()),
        )

    def evaluate(self, request: RiskBudgetRequest) -> EngineDecision:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id, approved, reason_code, reason, allocated_pct FROM risk_budget_allocations "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    bool(existing[1]), existing[2], existing[3],
                    {"allocation_id": existing[0], "allocated_pct": existing[4]},
                )

            policy_row = self._conn.execute(
                "SELECT portfolio_risk_limit_pct, config_version FROM risk_budget_policies "
                "WHERE portfolio_id = ?",
                (request.portfolio_id,),
            ).fetchone()
            if policy_row is None:
                decision = EngineDecision(
                    False, "NO_POLICY_CONFIGURED",
                    f"no risk_budget_policies row for portfolio {request.portfolio_id!r}; "
                    f"call set_policy() first",
                )
                self._conn.execute("ROLLBACK")
                return decision

            limit_pct = Decimal(policy_row[0])
            config_version = policy_row[1]

            try:
                requested_pct = Decimal(str(request.requested_risk_pct))
                confidence = Decimal(str(request.confidence))
                correlation_factor = Decimal(str(request.correlation_factor))
                drawdown_factor = Decimal(str(request.drawdown_factor))
            except (InvalidOperation, ValueError, TypeError):
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "INVALID_NUMERIC_INPUT", "a numeric input could not be parsed")

            if requested_pct <= 0:
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "REQUESTED_PCT_NON_POSITIVE", "requested_risk_pct must be > 0")
            for name, val in (
                ("confidence", confidence),
                ("correlation_factor", correlation_factor),
                ("drawdown_factor", drawdown_factor),
            ):
                if val < 0 or val > 1:
                    self._conn.execute("ROLLBACK")
                    return EngineDecision(
                        False, "FACTOR_OUT_OF_RANGE", f"{name} must be in [0, 1], got {val}"
                    )

            usage_row = self._conn.execute(
                "SELECT allocated_pct, version FROM risk_budget_usage WHERE portfolio_id = ?",
                (request.portfolio_id,),
            ).fetchone()
            currently_allocated = Decimal(usage_row[0]) if usage_row else Decimal("0")
            usage_version = usage_row[1] if usage_row else 0

            # No strategy can consume unlimited risk (AC-480-01): bounded by
            # the requested amount and by confidence/correlation/drawdown
            # reducers, never enlarged.
            nominal_pct = requested_pct * confidence
            adjusted_pct = nominal_pct * (1 - correlation_factor) * (1 - drawdown_factor)

            # Total allocated active risk cannot exceed portfolio policy
            # (AC-480-02): capped by remaining capacity under the limit.
            available_pct = limit_pct - currently_allocated
            final_pct = min(adjusted_pct, available_pct)

            allocation_id = str(uuid.uuid4())
            ts = time.time()

            if final_pct <= 0:
                decision = EngineDecision(
                    False, "NO_RISK_CAPACITY_AVAILABLE",
                    f"portfolio {request.portfolio_id!r} has no remaining risk capacity "
                    f"(limit={limit_pct}, allocated={currently_allocated}, "
                    f"requested-after-adjustment={adjusted_pct})",
                    {"available_pct": str(available_pct), "adjusted_pct": str(adjusted_pct)},
                )
            else:
                decision = EngineDecision(
                    True, "OK", "approved",
                    {
                        "allocation_id": allocation_id,
                        "nominal_pct": str(nominal_pct),
                        "adjusted_pct": str(adjusted_pct),
                        "allocated_pct": str(final_pct),
                        "available_pct_before": str(available_pct),
                    },
                )

            self._conn.execute(
                """
                INSERT INTO risk_budget_allocations
                    (id, idempotency_key, portfolio_id, strategy_id, correlation_id, status,
                     approved, reason_code, reason, allocated_pct, config_version,
                     request_json, created_at, released_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    allocation_id,
                    request.idempotency_key,
                    request.portfolio_id,
                    request.strategy_id,
                    request.correlation_id,
                    "ACTIVE" if decision.approved else "DENIED",
                    1 if decision.approved else 0,
                    decision.reason_code,
                    decision.reason,
                    str(final_pct) if decision.approved else "0",
                    config_version,
                    json.dumps(request.__dict__),
                    ts,
                ),
            )
            self._conn.execute(
                "INSERT INTO correlation_snapshots (id, portfolio_id, strategy_id, correlation_factor, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), request.portfolio_id, request.strategy_id,
                 str(correlation_factor), ts),
            )
            if decision.approved:
                new_allocated = currently_allocated + final_pct
                self._conn.execute(
                    """
                    INSERT INTO risk_budget_usage (portfolio_id, allocated_pct, version, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(portfolio_id) DO UPDATE SET
                        allocated_pct = excluded.allocated_pct,
                        version = excluded.version,
                        updated_at = excluded.updated_at
                    """,
                    (request.portfolio_id, str(new_allocated), usage_version + 1, ts),
                )
            self._conn.execute(
                """
                INSERT INTO risk_budget_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'risk_budget.decided', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps(
                        {
                            "allocation_id": allocation_id,
                            "portfolio_id": request.portfolio_id,
                            "strategy_id": request.strategy_id,
                            "approved": decision.approved,
                            "reason_code": decision.reason_code,
                            "correlation_id": request.correlation_id,
                        }
                    ),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return decision

    def release(self, allocation_id: str, *, reason_code: str) -> EngineDecision:
        """DERIVED: an ACTIVE allocation must be releasable (cancel/reject/
        expiry, mirroring Section 22's 'release unused reservation' rule
        for the sibling sizing module) or usage only ever grows and every
        portfolio permanently loses capacity."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT portfolio_id, status, allocated_pct FROM risk_budget_allocations WHERE id = ?",
                (allocation_id,),
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "ALLOCATION_NOT_FOUND", f"no allocation {allocation_id!r}")
            portfolio_id, status, allocated_pct = row
            if status != "ACTIVE":
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    False, "ALLOCATION_NOT_ACTIVE", f"allocation {allocation_id!r} is {status}, not ACTIVE"
                )

            ts = time.time()
            self._conn.execute(
                "UPDATE risk_budget_allocations SET status = 'RELEASED', released_at = ? WHERE id = ?",
                (ts, allocation_id),
            )
            usage_row = self._conn.execute(
                "SELECT allocated_pct, version FROM risk_budget_usage WHERE portfolio_id = ?",
                (portfolio_id,),
            ).fetchone()
            currently_allocated = Decimal(usage_row[0]) if usage_row else Decimal("0")
            usage_version = usage_row[1] if usage_row else 0
            new_allocated = max(Decimal("0"), currently_allocated - Decimal(allocated_pct))
            self._conn.execute(
                """
                INSERT INTO risk_budget_usage (portfolio_id, allocated_pct, version, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(portfolio_id) DO UPDATE SET
                    allocated_pct = excluded.allocated_pct,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (portfolio_id, str(new_allocated), usage_version + 1, ts),
            )
            self._conn.execute(
                """
                INSERT INTO risk_budget_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'risk_budget.released', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps({"allocation_id": allocation_id, "portfolio_id": portfolio_id, "reason_code": reason_code}),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return EngineDecision(True, "OK", "released", {"allocation_id": allocation_id})

    def get_decision(self, allocation_id: str) -> Optional[EngineDecision]:
        row = self._conn.execute(
            "SELECT approved, reason_code, reason, allocated_pct, status FROM risk_budget_allocations "
            "WHERE id = ?",
            (allocation_id,),
        ).fetchone()
        if row is None:
            return None
        return EngineDecision(bool(row[0]), row[1], row[2], {"allocated_pct": row[3], "status": row[4]})

    def health(self) -> dict:
        return {"status": "OK", "module": 480}
