"""
Module 486 - Production Testing Engine.

Source: AI Trading Platform Bible V63.0, Section 20. Primary rules
(SOURCE, verbatim): "Risk + portfolio + execution integration must be
tested. Crash and recovery scenarios must be tested."

Phase 5 of the DPR implementation. NOT wired into main.py or into this
repo's actual pytest run - this module is a governance LOG/GATE over test
results reported to it; it does not execute test suites itself (Section
20 gives no mechanism for that - "test_suite" and "results" are module
INPUTS, i.e. something else runs the tests and reports in).

IMPLEMENTATION ASSUMPTIONS (Section 20 states the two required test
categories in prose but names no category strings):
  - REQUIRED_CATEGORIES = {"risk_portfolio_execution_integration",
    "crash_recovery"} - a direct, literal transcription of the two
    primary rules into category labels a caller's reported results must
    include, each with at least one PASSING result, for the release gate
    to pass.
  - Gate result is PASS only if: no reported result failed, AND both
    required categories have >=1 passing result. Any failing result in
    ANY category fails the gate (a strict reading of "must be tested" -
    tested-and-failing is not the same as satisfied).
  - fault_scenarios inputs are recorded as their own table (matching the
    persistence list) but a fault scenario only counts toward the
    "crash_recovery" gate requirement if it also appears as a passing
    result in that category - a fault scenario that's merely listed but
    never actually exercised doesn't satisfy AC-486-02.
  - SQLite/no-broker assumptions as in Phases 1-4.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.decisions import EngineDecision

REQUIRED_CATEGORIES = frozenset({"risk_portfolio_execution_integration", "crash_recovery"})


@dataclass
class ProductionTestRunRequest:
    code_version: str
    test_suite: str
    results: list  # [{"test_name": str, "category": str, "passed": bool}, ...]
    fault_scenarios: list  # [str, ...]
    correlation_id: str
    idempotency_key: str


class ProductionTestingEngineService:
    """Module 486. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS test_runs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                code_version TEXT NOT NULL,
                test_suite TEXT NOT NULL,
                gate_result TEXT NOT NULL,  -- PASS | FAIL
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS test_results (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                category TEXT NOT NULL,
                passed INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fault_scenarios (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                scenario_name TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS release_quality_gates (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                code_version TEXT NOT NULL,
                gate_result TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS testing_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def evaluate(self, request: ProductionTestRunRequest) -> EngineDecision:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id, gate_result, reason_code, reason FROM test_runs WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                return EngineDecision(
                    existing[1] == "PASS", existing[2], existing[3],
                    {"run_id": existing[0], "gate_result": existing[1]},
                )

            categories_with_pass = set()
            any_failure = False
            for r in request.results:
                if not r.get("passed"):
                    any_failure = True
                else:
                    categories_with_pass.add(r.get("category"))

            missing_categories = REQUIRED_CATEGORIES - categories_with_pass
            if any_failure:
                gate_result = "FAIL"
                reason_code = "TEST_FAILURES_PRESENT"
                reason = "one or more reported test results failed"
            elif missing_categories:
                gate_result = "FAIL"
                reason_code = "REQUIRED_CATEGORY_NOT_COVERED"
                reason = f"missing a passing test in required categories: {sorted(missing_categories)}"
            else:
                gate_result = "PASS"
                reason_code, reason = "OK", "all required categories covered, no failures"

            run_id = str(uuid.uuid4())
            ts = time.time()
            self._conn.execute(
                """
                INSERT INTO test_runs
                    (id, idempotency_key, correlation_id, code_version, test_suite, gate_result,
                     reason_code, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, request.idempotency_key, request.correlation_id, request.code_version,
                 request.test_suite, gate_result, reason_code, reason, ts),
            )
            for r in request.results:
                self._conn.execute(
                    "INSERT INTO test_results (id, run_id, test_name, category, passed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, r.get("test_name", ""), r.get("category", ""),
                     1 if r.get("passed") else 0, ts),
                )
            for scenario in request.fault_scenarios:
                self._conn.execute(
                    "INSERT INTO fault_scenarios (id, run_id, scenario_name, created_at) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, scenario, ts),
                )
            self._conn.execute(
                "INSERT INTO release_quality_gates (id, run_id, code_version, gate_result, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), run_id, request.code_version, gate_result, ts),
            )
            self._conn.execute(
                """
                INSERT INTO testing_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'test_run.gated', ?, ?, 0)
                """,
                (str(uuid.uuid4()), json.dumps({
                    "run_id": run_id, "code_version": request.code_version, "gate_result": gate_result,
                    "correlation_id": request.correlation_id,
                }), ts),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return EngineDecision(
            gate_result == "PASS", reason_code, reason, {"run_id": run_id, "gate_result": gate_result}
        )

    def get_decision(self, run_id: str) -> Optional[EngineDecision]:
        row = self._conn.execute(
            "SELECT gate_result, reason_code, reason FROM test_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return EngineDecision(row[0] == "PASS", row[1], row[2], {"gate_result": row[0]})

    def health(self) -> dict:
        return {"status": "OK", "module": 486}
