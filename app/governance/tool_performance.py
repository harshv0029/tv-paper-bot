"""
Module 484 - Tool Performance Memory Engine.

Source: AI Trading Platform Bible V63.0, Section 18. Primary rules
(SOURCE, verbatim): "New cost requires measurable improvement. Decision
evidence is retained for future procurement comparisons."

Phase 5 of the DPR implementation. NOT wired into main.py - this module
doesn't touch entry/exit/sizing at all (it's a tooling-spend governance
log), so it carries a lower bar than Modules 480-483, but still nothing
in this codebase calls it yet.

IMPLEMENTATION ASSUMPTIONS (Section 18 gives inputs/outputs/rules but no
exact decision procedure):
  - "New cost requires measurable improvement" (AC-484-01) is split into
    two evaluation modes based on whether actual_benefit has been
    measured yet:
      * PRE-COMMITMENT (actual_benefit is None - a brand new tool/cost
        being proposed): approved only if expected_benefit > cost, i.e. a
        positive PROJECTED improvement - the only number available before
        the tool has actually been used.
      * POST-MEASUREMENT (actual_benefit is provided - a renewal/periodic
        review of a tool already in use): decision is KEEP if
        actual_benefit > cost (realized ROI positive), else REMOVE - "new
        cost requires measurable improvement" applies continuously, not
        just at initial purchase.
  - REPLACE is not something this engine can derive from the four named
    inputs alone (no "alternative cost/benefit" input exists anywhere in
    Section 18) - it's exposed as an explicit human/procurement decision
    via record_replace_decision(), still persisted to tool_decisions for
    AC-484-02's audit trail, rather than invented from data that isn't
    there.
  - renewal_review_date is `evaluated_at + review_period_days` (policy-
    configurable, default 90) whenever the decision keeps the tool in
    play (APPROVED_TRIAL or KEEP).
  - SQLite/no-broker assumptions as in Phases 1-4.
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

DEFAULT_REVIEW_PERIOD_DAYS = 90
SECONDS_PER_DAY = 86400


@dataclass
class ToolEvaluationRequest:
    tool_id: str
    tool_name: str
    cost: str
    expected_benefit: str
    actual_benefit: Optional[str]
    correlation_id: str
    idempotency_key: str


class ToolPerformanceMemoryEngineService:
    """Module 484. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection, *, review_period_days: int = DEFAULT_REVIEW_PERIOD_DAYS):
        self._conn = conn
        self._conn.isolation_level = None
        self._review_period_days = review_period_days
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_registry (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_costs (
                id TEXT PRIMARY KEY,
                tool_id TEXT NOT NULL,
                cost TEXT NOT NULL,
                recorded_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_benefit_measurements (
                id TEXT PRIMARY KEY,
                tool_id TEXT NOT NULL,
                actual_benefit TEXT NOT NULL,
                measured_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_decisions (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                tool_id TEXT NOT NULL,
                decision TEXT NOT NULL,  -- APPROVED_TRIAL | DENIED_TRIAL | KEEP | REMOVE | REPLACE
                roi TEXT,
                renewal_review_date REAL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                request_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_governance_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def evaluate(self, request: ToolEvaluationRequest) -> EngineDecision:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id, decision, roi, renewal_review_date, reason_code, reason FROM tool_decisions "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                approved = existing[1] in ("APPROVED_TRIAL", "KEEP")
                return EngineDecision(
                    approved, existing[4], existing[5],
                    {"decision": existing[1], "roi": existing[2], "renewal_review_date": existing[3],
                     "decision_id": existing[0]},
                )

            try:
                cost = Decimal(str(request.cost))
                expected_benefit = Decimal(str(request.expected_benefit))
                actual_benefit = (
                    Decimal(str(request.actual_benefit)) if request.actual_benefit is not None else None
                )
            except (InvalidOperation, ValueError, TypeError):
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "INVALID_NUMERIC_INPUT", "a numeric input could not be parsed")

            if cost <= 0:
                self._conn.execute("ROLLBACK")
                return EngineDecision(False, "COST_NON_POSITIVE", "cost must be > 0")

            ts = time.time()
            self._conn.execute(
                "INSERT OR IGNORE INTO tool_registry (tool_id, tool_name, created_at) VALUES (?, ?, ?)",
                (request.tool_id, request.tool_name, ts),
            )
            self._conn.execute(
                "INSERT INTO tool_costs (id, tool_id, cost, recorded_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), request.tool_id, str(cost), ts),
            )

            if actual_benefit is None:
                # PRE-COMMITMENT: only a projection exists.
                roi = None
                if expected_benefit > cost:
                    decision_label = "APPROVED_TRIAL"
                    reason_code, reason = "OK", "projected benefit exceeds cost"
                else:
                    decision_label = "DENIED_TRIAL"
                    reason_code = "NEW_COST_LACKS_MEASURABLE_IMPROVEMENT"
                    reason = (
                        f"expected_benefit ({expected_benefit}) does not exceed cost ({cost}) - "
                        f"AC-484-01: new cost requires measurable improvement"
                    )
            else:
                self._conn.execute(
                    "INSERT INTO tool_benefit_measurements (id, tool_id, actual_benefit, measured_at) "
                    "VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), request.tool_id, str(actual_benefit), ts),
                )
                roi = (actual_benefit - cost) / cost
                if actual_benefit > cost:
                    decision_label = "KEEP"
                    reason_code, reason = "OK", "realized benefit exceeds cost"
                else:
                    decision_label = "REMOVE"
                    reason_code = "REALIZED_BENEFIT_DOES_NOT_JUSTIFY_COST"
                    reason = f"actual_benefit ({actual_benefit}) does not exceed cost ({cost})"

            renewal_review_date = None
            if decision_label in ("APPROVED_TRIAL", "KEEP"):
                renewal_review_date = ts + self._review_period_days * SECONDS_PER_DAY

            decision_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO tool_decisions
                    (id, idempotency_key, correlation_id, tool_id, decision, roi, renewal_review_date,
                     reason_code, reason, request_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id, request.idempotency_key, request.correlation_id, request.tool_id,
                    decision_label, str(roi) if roi is not None else None, renewal_review_date,
                    reason_code, reason, json.dumps(request.__dict__), ts,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO tool_governance_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'tool_decision.made', ?, ?, 0)
                """,
                (str(uuid.uuid4()), json.dumps({
                    "decision_id": decision_id, "tool_id": request.tool_id, "decision": decision_label,
                    "correlation_id": request.correlation_id,
                }), ts),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        approved = decision_label in ("APPROVED_TRIAL", "KEEP")
        return EngineDecision(
            approved, reason_code, reason,
            {"decision": decision_label, "roi": str(roi) if roi is not None else None,
             "renewal_review_date": renewal_review_date, "decision_id": decision_id},
        )

    def record_replace_decision(
        self, tool_id: str, *, reason: str, correlation_id: str
    ) -> EngineDecision:
        """DERIVED - REPLACE is a procurement judgment call this engine
        cannot derive from cost/expected_benefit/actual_benefit alone (no
        'alternative' input exists in Section 18). Exposed as an explicit
        action so the decision still lands in tool_decisions for
        AC-484-02's audit trail, rather than being silently un-recordable."""
        decision_id = str(uuid.uuid4())
        ts = time.time()
        self._conn.execute(
            """
            INSERT INTO tool_decisions
                (id, idempotency_key, correlation_id, tool_id, decision, roi, renewal_review_date,
                 reason_code, reason, request_json, created_at)
            VALUES (?, ?, ?, ?, 'REPLACE', NULL, NULL, 'MANUAL_REPLACE_DECISION', ?, ?, ?)
            """,
            (decision_id, str(uuid.uuid4()), correlation_id, tool_id, reason,
             json.dumps({"tool_id": tool_id, "reason": reason}), ts),
        )
        return EngineDecision(False, "MANUAL_REPLACE_DECISION", reason, {"decision": "REPLACE", "decision_id": decision_id})

    def get_decision(self, decision_id: str) -> Optional[EngineDecision]:
        row = self._conn.execute(
            "SELECT decision, roi, renewal_review_date, reason_code, reason FROM tool_decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        approved = row[0] in ("APPROVED_TRIAL", "KEEP")
        return EngineDecision(
            approved, row[3], row[4], {"decision": row[0], "roi": row[1], "renewal_review_date": row[2]}
        )

    def health(self) -> dict:
        return {"status": "OK", "module": 484}
