"""
Module 487 - Production Deployment Engine.

Source: AI Trading Platform Bible V63.0, Section 21. Primary rules
(SOURCE, verbatim): "No untested code reaches live capital. Promotion is
sequential unless emergency rollback." Stage sequence (SOURCE, Section 21
header + Section 33 "Deployment Architecture for Cloud VPS"):
Development -> Testing -> Paper Trading -> Small Capital -> Production.

Phase 5 of the DPR implementation. NOT wired into main.py - this module
governs *promotion decisions*; it does not itself deploy code or flip
REAL_TRADING_ENABLED (that stays the user's own manual Render env var
switch per this session's standing decision - see
docs/dpr_v63_phase1_notes.md). A future wiring of this module would, at
most, gate a recommendation - never make live-trading state changes on
its own.

IMPLEMENTATION ASSUMPTIONS (Section 21 names the four evidence inputs and
the two primary rules, but not the exact gate per promotion edge):
  - Promotion is normally one step at a time along DEVELOPMENT(0) ->
    TESTING(1) -> PAPER_TRADING(2) -> SMALL_CAPITAL(3) -> PRODUCTION(4);
    any non-adjacent jump is rejected (EDGE_NOT_ALLOWED) unless done via
    emergency_rollback(), which is explicitly the DPR's own stated
    exception to "promotion is sequential".
  - Per-edge evidence gate, derived directly from the module's named
    inputs and "no untested code reaches live capital":
      DEVELOPMENT -> TESTING requires `test_evidence.gate_passed = True`
        (a Module 486 PASS, or equivalent) - code cannot even reach the
        Testing stage untested.
      PAPER_TRADING -> SMALL_CAPITAL requires non-empty
        `paper_trading_metrics` with no `catastrophic_failure` flag.
      SMALL_CAPITAL -> PRODUCTION requires non-empty
        `small_capital_metrics` AND at least one entry in `approvals` -
        Section 33's "Operator/CIO policy may enable production trading"
        establishes that reaching live capital needs an explicit
        approval, not an automatic metrics threshold nobody set.
  - emergency_rollback() may move to ANY lower stage (or re-disable an
    already-promoted release) bypassing the sequential check, but
    requires `authorized_by` - DERIVED, mirroring the project's now-
    established convention (Modules 478/482) that any override/recovery
    path needs an accountable actor.
  - SQLite/no-broker assumptions as in Phases 1-4.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.core.decisions import EngineDecision

STAGES = ["DEVELOPMENT", "TESTING", "PAPER_TRADING", "SMALL_CAPITAL", "PRODUCTION"]
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}


@dataclass
class PromotionRequest:
    release_id: str
    code_version: str
    to_stage: str
    test_evidence: dict = field(default_factory=dict)
    paper_trading_metrics: dict = field(default_factory=dict)
    small_capital_metrics: dict = field(default_factory=dict)
    approvals: list = field(default_factory=list)
    correlation_id: str = ""
    idempotency_key: str = ""


class ProductionDeploymentEngineService:
    """Module 487. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS releases (
                release_id TEXT PRIMARY KEY,
                code_version TEXT NOT NULL,
                current_stage TEXT NOT NULL DEFAULT 'DEVELOPMENT',
                version INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deployment_environments (
                stage TEXT PRIMARY KEY,
                stage_index INTEGER NOT NULL
            )
            """
        )
        for stage in STAGES:
            self._conn.execute(
                "INSERT OR IGNORE INTO deployment_environments (stage, stage_index) VALUES (?, ?)",
                (stage, STAGE_INDEX[stage]),
            )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deployment_promotions (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                release_id TEXT NOT NULL,
                from_stage TEXT NOT NULL,
                to_stage TEXT NOT NULL,
                approved INTEGER NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                request_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deployment_approvals (
                id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                promotion_id TEXT NOT NULL,
                approver TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rollback_records (
                id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                from_stage TEXT NOT NULL,
                to_stage TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                authorized_by TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deployment_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def _get_or_create_release(self, release_id: str, code_version: str, ts: float) -> str:
        row = self._conn.execute(
            "SELECT current_stage FROM releases WHERE release_id = ?", (release_id,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO releases (release_id, code_version, current_stage, version, created_at, updated_at) "
                "VALUES (?, ?, 'DEVELOPMENT', 1, ?, ?)",
                (release_id, code_version, ts, ts),
            )
            return "DEVELOPMENT"
        return row[0]

    def promote(self, request: PromotionRequest) -> EngineDecision:
        """AC-487-02: promotion is sequential. AC-487-01: no untested code
        reaches live capital - enforced via the per-edge evidence gate."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id, approved, reason_code, reason, to_stage FROM deployment_promotions "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    bool(existing[1]), existing[2], existing[3],
                    {"promotion_id": existing[0], "to_stage": existing[4]},
                )

            if request.to_stage not in STAGE_INDEX:
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "UNKNOWN_STAGE", f"{request.to_stage!r} is not a valid stage")

            ts = time.time()
            current_stage = self._get_or_create_release(request.release_id, request.code_version, ts)
            from_idx = STAGE_INDEX[current_stage]
            to_idx = STAGE_INDEX[request.to_stage]

            if to_idx != from_idx + 1:
                decision = EngineDecision(
                    False, "EDGE_NOT_ALLOWED",
                    f"promotion is sequential: {current_stage} -> {request.to_stage} skips stages "
                    f"(use emergency_rollback for a non-sequential move)",
                )
            elif current_stage == "DEVELOPMENT" and not request.test_evidence.get("gate_passed"):
                decision = EngineDecision(
                    False, "UNTESTED_CODE_CANNOT_PROMOTE",
                    "DEVELOPMENT -> TESTING requires test_evidence.gate_passed = True "
                    "(AC-487-01: no untested code reaches live capital)",
                )
            elif current_stage == "PAPER_TRADING" and (
                not request.paper_trading_metrics
                or request.paper_trading_metrics.get("catastrophic_failure")
            ):
                decision = EngineDecision(
                    False, "PAPER_TRADING_EVIDENCE_INSUFFICIENT",
                    "PAPER_TRADING -> SMALL_CAPITAL requires non-empty paper_trading_metrics "
                    "with no catastrophic_failure flag",
                )
            elif current_stage == "SMALL_CAPITAL" and (
                not request.small_capital_metrics or not request.approvals
            ):
                decision = EngineDecision(
                    False, "PRODUCTION_PROMOTION_REQUIRES_APPROVAL",
                    "SMALL_CAPITAL -> PRODUCTION requires small_capital_metrics AND at least one "
                    "recorded approval (Operator/CIO policy may enable production trading)",
                )
            else:
                decision = EngineDecision(True, "OK", "promoted", {"to_stage": request.to_stage})

            promotion_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO deployment_promotions
                    (id, idempotency_key, correlation_id, release_id, from_stage, to_stage, approved,
                     reason_code, reason, request_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    promotion_id, request.idempotency_key, request.correlation_id, request.release_id,
                    current_stage, request.to_stage, 1 if decision.approved else 0,
                    decision.reason_code, decision.reason,
                    json.dumps({k: v for k, v in request.__dict__.items()}), ts,
                ),
            )
            if decision.approved:
                for approver in request.approvals:
                    self._conn.execute(
                        "INSERT INTO deployment_approvals (id, release_id, promotion_id, approver, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), request.release_id, promotion_id, approver, ts),
                    )
                self._conn.execute(
                    "UPDATE releases SET current_stage = ?, version = version + 1, updated_at = ? "
                    "WHERE release_id = ?",
                    (request.to_stage, ts, request.release_id),
                )
            self._conn.execute(
                """
                INSERT INTO deployment_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'deployment.promotion_decided', ?, ?, 0)
                """,
                (str(uuid.uuid4()), json.dumps({
                    "promotion_id": promotion_id, "release_id": request.release_id,
                    "to_stage": request.to_stage, "approved": decision.approved,
                    "correlation_id": request.correlation_id,
                }), ts),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        decision.data["promotion_id"] = promotion_id
        return decision

    def emergency_rollback(
        self, release_id: str, to_stage: str, *, reason_code: str, authorized_by: Optional[str]
    ) -> EngineDecision:
        """The DPR's own stated exception to 'promotion is sequential'.
        DERIVED to require an authorized_by actor."""
        if not authorized_by:
            return EngineDecision(False, "ROLLBACK_UNAUTHORIZED", "emergency_rollback requires authorized_by")
        if to_stage not in STAGE_INDEX:
            return EngineDecision(False, "UNKNOWN_STAGE", f"{to_stage!r} is not a valid stage")

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT current_stage FROM releases WHERE release_id = ?", (release_id,)
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "RELEASE_NOT_FOUND", f"no release {release_id!r}")
            current_stage = row[0]
            if STAGE_INDEX[to_stage] >= STAGE_INDEX[current_stage]:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    False, "ROLLBACK_MUST_GO_DOWN",
                    f"rollback target {to_stage!r} is not below current stage {current_stage!r}",
                )

            ts = time.time()
            self._conn.execute(
                "UPDATE releases SET current_stage = ?, version = version + 1, updated_at = ? "
                "WHERE release_id = ?",
                (to_stage, ts, release_id),
            )
            record_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO rollback_records
                    (id, release_id, from_stage, to_stage, reason_code, authorized_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, release_id, current_stage, to_stage, reason_code, authorized_by, ts),
            )
            self._conn.execute(
                """
                INSERT INTO deployment_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'deployment.rolled_back', ?, ?, 0)
                """,
                (str(uuid.uuid4()), json.dumps({
                    "release_id": release_id, "from_stage": current_stage, "to_stage": to_stage,
                    "authorized_by": authorized_by,
                }), ts),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return EngineDecision(True, "OK", "rolled back", {"rollback_id": record_id, "to_stage": to_stage})

    def get_decision(self, promotion_id: str) -> Optional[EngineDecision]:
        row = self._conn.execute(
            "SELECT approved, reason_code, reason, to_stage FROM deployment_promotions WHERE id = ?",
            (promotion_id,),
        ).fetchone()
        if row is None:
            return None
        return EngineDecision(bool(row[0]), row[1], row[2], {"to_stage": row[3]})

    def current_stage(self, release_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT current_stage FROM releases WHERE release_id = ?", (release_id,)
        ).fetchone()
        return row[0] if row else None

    def health(self) -> dict:
        return {"status": "OK", "module": 487}
