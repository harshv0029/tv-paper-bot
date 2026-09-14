"""
Module 483 - Capital Migration Policy Engine.

Source: AI Trading Platform Bible V63.0, Section 17. Primary rules
(SOURCE, verbatim): "Trading account cannot hold all accumulated wealth
permanently. Early stage prioritizes skill and survival; medium stage
balances; high wealth prioritizes preservation. Never migrate unrealized
P&L as if it were cash."

Phase 5 of the DPR implementation. NOT wired into main.py. Wiring this in
requires the same bar as Modules 480-482: full replay validation +
explicit user go-ahead - this module's recommendations would eventually
move real capital between "trading" and "preserved" buckets, so it's
real-money-adjacent even though it doesn't touch entry/exit/sizing
directly.

IMPLEMENTATION ASSUMPTIONS (Section 17 names capital_stage as an INPUT,
not something this module computes - some other, not-yet-built module
classifies EARLY/MEDIUM/HIGH_WEALTH; this engine only consumes that
classification):
  - Retention-by-stage is a policy-configurable percentage of total wealth
    (trading account equity + everything already migrated out) that stays
    in the trading account: EARLY retains the most (skill/survival),
    HIGH_WEALTH the least (preservation) - the DPR states the ordering but
    not exact numbers, so these are config, not hardcoded, with documented
    defaults (0.95 / 0.60 / 0.30) reflecting that ordering.
  - Migration amount is derived as:
        target_trading_equity = total_wealth * stage_retention_pct
        excess = max(0, trading_account_equity - target_trading_equity)
        recommended = min(excess, realized_profit)   # AC-483-03
        recommended = min(recommended, trading_account_equity - liquidity_reserve)
    The `min(excess, realized_profit)` step is the direct enforcement of
    AC-483-03 ("never migrate unrealized P&L as if it were cash") -
    however large the stage-driven "excess" is, the recommendation can
    never exceed what's actually realized.
  - SQLite/no-broker assumptions as in Phases 1-4 (see
    docs/dpr_v63_phase1_notes.md).
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

CAPITAL_STAGES = ("EARLY", "MEDIUM", "HIGH_WEALTH")

DEFAULT_STAGE_RETENTION_PCT = {
    "EARLY": "0.95",
    "MEDIUM": "0.60",
    "HIGH_WEALTH": "0.30",
}


@dataclass
class MigrationRequest:
    portfolio_id: str
    capital_stage: str
    realized_profit: str
    trading_account_equity: str
    already_migrated_total: str
    liquidity_reserve: str
    correlation_id: str
    idempotency_key: str


class CapitalMigrationPolicyEngineService:
    """Module 483. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_migration_policies (
                portfolio_id TEXT PRIMARY KEY,
                stage_retention_json TEXT NOT NULL,
                config_version TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_stage_history (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                capital_stage TEXT NOT NULL,
                ts REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_migrations (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                portfolio_id TEXT NOT NULL,
                capital_stage TEXT NOT NULL,
                approved INTEGER NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                recommended_amount TEXT NOT NULL,
                status TEXT NOT NULL,  -- RECOMMENDED | APPROVED
                config_version TEXT NOT NULL,
                request_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                approved_at REAL,
                approved_by TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wealth_allocations (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                migration_id TEXT NOT NULL,
                amount TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_migration_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def set_policy(
        self,
        portfolio_id: str,
        *,
        stage_retention_pct: Optional[dict] = None,
        config_version: str,
    ) -> None:
        retention = dict(DEFAULT_STAGE_RETENTION_PCT)
        if stage_retention_pct:
            retention.update({k: str(v) for k, v in stage_retention_pct.items()})
        self._conn.execute(
            """
            INSERT INTO capital_migration_policies (portfolio_id, stage_retention_json, config_version, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(portfolio_id) DO UPDATE SET
                stage_retention_json = excluded.stage_retention_json,
                config_version = excluded.config_version,
                updated_at = excluded.updated_at
            """,
            (portfolio_id, json.dumps(retention), config_version, time.time()),
        )

    def recommend(self, request: MigrationRequest) -> EngineDecision:
        """GET /portfolio/migration/recommendation equivalent. Produces a
        RECOMMENDED (not yet approved/transferred) migration amount."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id, approved, reason_code, reason, recommended_amount, status "
                "FROM capital_migrations WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    bool(existing[1]), existing[2], existing[3],
                    {"migration_id": existing[0], "recommended_amount": existing[4], "status": existing[5]},
                )

            if request.capital_stage not in CAPITAL_STAGES:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    False, "UNKNOWN_CAPITAL_STAGE",
                    f"capital_stage must be one of {CAPITAL_STAGES}, got {request.capital_stage!r}",
                )

            policy_row = self._conn.execute(
                "SELECT stage_retention_json, config_version FROM capital_migration_policies "
                "WHERE portfolio_id = ?",
                (request.portfolio_id,),
            ).fetchone()
            if policy_row is None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    False, "NO_POLICY_CONFIGURED",
                    f"no capital_migration_policies row for portfolio {request.portfolio_id!r}",
                )
            retention = json.loads(policy_row[0])
            config_version = policy_row[1]

            try:
                realized_profit = Decimal(str(request.realized_profit))
                trading_equity = Decimal(str(request.trading_account_equity))
                already_migrated = Decimal(str(request.already_migrated_total))
                liquidity_reserve = Decimal(str(request.liquidity_reserve))
            except (InvalidOperation, ValueError, TypeError):
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "INVALID_NUMERIC_INPUT", "a numeric input could not be parsed")

            if trading_equity < 0 or realized_profit < 0 or liquidity_reserve < 0:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    False, "NEGATIVE_INPUT_REJECTED",
                    "trading_account_equity, realized_profit and liquidity_reserve must be >= 0",
                )

            stage_retention_pct = Decimal(retention[request.capital_stage])
            total_wealth = trading_equity + already_migrated
            target_trading_equity = total_wealth * stage_retention_pct

            # AC-483-01: trading account cannot hold all wealth permanently
            # - structurally enforced since stage_retention_pct < 1.
            excess = max(Decimal("0"), trading_equity - target_trading_equity)

            # AC-483-03: never migrate unrealized P&L as if it were cash -
            # capped by what's actually realized, however large `excess` is.
            recommended = min(excess, realized_profit)

            # Never recommend migrating below the required liquidity reserve.
            headroom_above_reserve = max(Decimal("0"), trading_equity - liquidity_reserve)
            recommended = min(recommended, headroom_above_reserve)

            migration_id = str(uuid.uuid4())
            ts = time.time()

            if recommended <= 0:
                decision = EngineDecision(
                    False, "NO_MIGRATION_NEEDED",
                    f"trading_account_equity ({trading_equity}) is within stage {request.capital_stage!r}'s "
                    f"retention target and/or no realized profit or liquidity headroom to migrate",
                    {"recommended_amount": "0"},
                )
            else:
                decision = EngineDecision(
                    True, "OK", "migration recommended",
                    {"migration_id": migration_id, "recommended_amount": str(recommended),
                     "target_trading_equity": str(target_trading_equity)},
                )

            self._conn.execute(
                """
                INSERT INTO capital_migrations
                    (id, idempotency_key, correlation_id, portfolio_id, capital_stage, approved,
                     reason_code, reason, recommended_amount, status, config_version, request_json,
                     created_at, approved_at, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'RECOMMENDED', ?, ?, ?, NULL, NULL)
                """,
                (
                    migration_id, request.idempotency_key, request.correlation_id, request.portfolio_id,
                    request.capital_stage, 1 if decision.approved else 0, decision.reason_code,
                    decision.reason, decision.data.get("recommended_amount", "0"), config_version,
                    json.dumps(request.__dict__), ts,
                ),
            )
            self._conn.execute(
                "INSERT INTO capital_stage_history (id, portfolio_id, capital_stage, ts) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), request.portfolio_id, request.capital_stage, ts),
            )
            self._conn.execute(
                """
                INSERT INTO capital_migration_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'capital_migration.recommended', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps({"migration_id": migration_id, "portfolio_id": request.portfolio_id,
                                "approved": decision.approved, "correlation_id": request.correlation_id}),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return decision

    def approve(self, migration_id: str, *, approved_by: str) -> EngineDecision:
        """POST /portfolio/migration/approve equivalent - converts a
        RECOMMENDED migration into an APPROVED transfer instruction."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT approved, status, recommended_amount, portfolio_id FROM capital_migrations "
                "WHERE id = ?",
                (migration_id,),
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "MIGRATION_NOT_FOUND", f"no migration {migration_id!r}")
            was_approved_recommendation, status, amount, portfolio_id = row
            if not was_approved_recommendation:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    False, "CANNOT_APPROVE_DENIED_RECOMMENDATION",
                    f"migration {migration_id!r} was never recommended (NO_MIGRATION_NEEDED)",
                )
            if status == "APPROVED":
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "ALREADY_APPROVED", f"migration {migration_id!r} is already APPROVED")

            ts = time.time()
            self._conn.execute(
                "UPDATE capital_migrations SET status = 'APPROVED', approved_at = ?, approved_by = ? "
                "WHERE id = ?",
                (ts, approved_by, migration_id),
            )
            self._conn.execute(
                "INSERT INTO wealth_allocations (id, portfolio_id, migration_id, amount, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), portfolio_id, migration_id, amount, ts),
            )
            self._conn.execute(
                """
                INSERT INTO capital_migration_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'capital_migration.approved', ?, ?, 0)
                """,
                (str(uuid.uuid4()), json.dumps({"migration_id": migration_id, "approved_by": approved_by}), ts),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return EngineDecision(True, "OK", "approved", {"migration_id": migration_id, "amount": amount})

    def get_decision(self, migration_id: str) -> Optional[EngineDecision]:
        row = self._conn.execute(
            "SELECT approved, reason_code, reason, recommended_amount, status FROM capital_migrations "
            "WHERE id = ?",
            (migration_id,),
        ).fetchone()
        if row is None:
            return None
        return EngineDecision(
            bool(row[0]), row[1], row[2], {"recommended_amount": row[3], "status": row[4]}
        )

    def health(self) -> dict:
        return {"status": "OK", "module": 483}
