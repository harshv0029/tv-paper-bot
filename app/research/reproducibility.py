"""
Module 479 - Research Reproducibility Engine.

Source: AI Trading Platform Bible V63.0, Section 13 (service contract,
persistence, validation, concurrency, acceptance criteria). Primary rules
(SOURCE, verbatim): "Old and new strategy code versions are separate
strategies for result comparison. A completed manifest is immutable. All
hashes are captured before execution starts."

Phase 4 of the DPR implementation. NOT wired into main.py's live path -
this module makes backtests reproducible; it doesn't itself touch
entry/exit/sizing, so it carries a lower bar than Modules 480-482, but it
is still new/unwired/unvalidated in the sense that nothing in this
codebase's existing replay-validation workflows calls it yet.

IMPLEMENTATION ASSUMPTIONS (Section 13 does not fix these):
  - manifest_hash algorithm: sha256 over the canonical (sorted-key) JSON
    encoding of {strategy_version_id, dataset_id, parameters,
    execution_assumptions, cost_model, test_period}. The DPR names
    "hashes" as an input/output everywhere but never specifies an
    algorithm or canonicalization scheme.
  - This engine persists and enforces version/hash identity; it does not
    itself compute a strategy's code_hash or a dataset's data_hash from
    source files - those are supplied by the caller (the DPR lists them
    as module INPUTS, not something Section 13 derives internally).
  - AC-479-01 ("old and new strategy code versions are separate
    strategies") is enforced via a uniqueness constraint on
    (strategy_name, code_hash): registering the same name with a
    different hash always creates a new strategy_versions row, never
    overwrites the old one's id.
  - AC-479-02 ("a completed manifest is immutable") is enforced by
    rejecting any second complete_backtest_run() call on an already-
    COMPLETED run, rather than silently overwriting results.
  - SQLite/no-broker assumptions as in Phases 1-3 (see
    docs/dpr_v63_phase1_notes.md).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


class ResearchReproducibilityError(Exception):
    pass


class ImmutableManifestError(ResearchReproducibilityError):
    pass


def _canonical_hash(obj) -> str:
    """IMPLEMENTATION ASSUMPTION: sha256 over sorted-key JSON. See module
    docstring."""
    blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class BacktestRun:
    id: str
    strategy_version_id: str
    dataset_id: str
    parameters: dict
    execution_assumptions: dict
    cost_model: dict
    test_period: dict
    manifest_hash: str
    status: str  # RUNNING | COMPLETED
    correlation_id: str
    idempotency_key: str
    created_at: float
    completed_at: Optional[float] = None
    results: dict = field(default_factory=dict)
    artifact_hashes: list = field(default_factory=list)


class ResearchReproducibilityEngineService:
    """Module 479. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_versions (
                id TEXT PRIMARY KEY,
                strategy_name TEXT NOT NULL,
                code_version TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE (strategy_name, code_hash)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                data_version TEXT NOT NULL,
                data_hash TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                strategy_version_id TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                execution_assumptions_json TEXT NOT NULL,
                cost_model_json TEXT NOT NULL,
                test_period_json TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                results_json TEXT,
                created_at REAL NOT NULL,
                completed_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_parameters (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                param_key TEXT NOT NULL,
                param_value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    # -- strategy/dataset identity --------------------------------------

    def register_strategy_version(self, strategy_name: str, code_version: str, code_hash: str) -> str:
        """AC-479-01: a (strategy_name, code_hash) pair already on file
        returns its existing id unchanged (idempotent registration); a new
        code_hash for a known strategy_name always gets a NEW id - old and
        new code versions are separate strategies, never overwritten."""
        row = self._conn.execute(
            "SELECT id FROM strategy_versions WHERE strategy_name = ? AND code_hash = ?",
            (strategy_name, code_hash),
        ).fetchone()
        if row is not None:
            return row[0]
        version_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO strategy_versions (id, strategy_name, code_version, code_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (version_id, strategy_name, code_version, code_hash, time.time()),
        )
        return version_id

    def register_dataset(self, data_version: str, data_hash: str) -> str:
        row = self._conn.execute(
            "SELECT id FROM datasets WHERE data_hash = ?", (data_hash,)
        ).fetchone()
        if row is not None:
            return row[0]
        dataset_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO datasets (id, data_version, data_hash, created_at) VALUES (?, ?, ?, ?)",
            (dataset_id, data_version, data_hash, time.time()),
        )
        return dataset_id

    # -- 13.1 service contract ------------------------------------------

    def create_backtest_run(
        self,
        *,
        strategy_version_id: str,
        dataset_id: str,
        parameters: dict,
        execution_assumptions: dict,
        cost_model: dict,
        test_period: dict,
        correlation_id: str,
        idempotency_key: str,
    ) -> BacktestRun:
        """AC-479-03: all hashes are captured before execution starts - the
        manifest_hash is computed and persisted right here, at creation
        (status=RUNNING), not after results come back."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id FROM backtest_runs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                return self.get_decision(existing[0])

            sv = self._conn.execute(
                "SELECT id FROM strategy_versions WHERE id = ?", (strategy_version_id,)
            ).fetchone()
            if sv is None:
                self._conn.execute("ROLLBACK")
                raise ResearchReproducibilityError(
                    f"UNKNOWN_STRATEGY_VERSION: {strategy_version_id!r} is not registered"
                )
            ds = self._conn.execute(
                "SELECT id FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
            if ds is None:
                self._conn.execute("ROLLBACK")
                raise ResearchReproducibilityError(
                    f"UNKNOWN_DATASET: {dataset_id!r} is not registered"
                )

            manifest_hash = _canonical_hash(
                {
                    "strategy_version_id": strategy_version_id,
                    "dataset_id": dataset_id,
                    "parameters": parameters,
                    "execution_assumptions": execution_assumptions,
                    "cost_model": cost_model,
                    "test_period": test_period,
                }
            )

            run_id = str(uuid.uuid4())
            ts = time.time()
            self._conn.execute(
                """
                INSERT INTO backtest_runs
                    (id, idempotency_key, correlation_id, strategy_version_id, dataset_id,
                     parameters_json, execution_assumptions_json, cost_model_json,
                     test_period_json, manifest_hash, status, results_json, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', NULL, ?, NULL)
                """,
                (
                    run_id, idempotency_key, correlation_id, strategy_version_id, dataset_id,
                    json.dumps(parameters), json.dumps(execution_assumptions),
                    json.dumps(cost_model), json.dumps(test_period), manifest_hash, ts,
                ),
            )
            for k, v in parameters.items():
                self._conn.execute(
                    "INSERT INTO backtest_parameters (id, run_id, param_key, param_value) "
                    "VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, str(k), json.dumps(v)),
                )
            self._conn.execute(
                """
                INSERT INTO research_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'backtest_run.created', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps({"run_id": run_id, "manifest_hash": manifest_hash, "correlation_id": correlation_id}),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except ResearchReproducibilityError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return self.get_decision(run_id)

    def complete_backtest_run(self, run_id: str, *, results: dict, artifact_hashes: list) -> BacktestRun:
        """AC-479-02: a completed manifest is immutable - calling this
        twice on the same run raises rather than overwriting results."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT status FROM backtest_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                raise ResearchReproducibilityError(f"RUN_NOT_FOUND: {run_id!r}")
            if row[0] == "COMPLETED":
                self._conn.execute("ROLLBACK")
                raise ImmutableManifestError(
                    f"run {run_id!r} is already COMPLETED - a completed manifest is immutable"
                )

            ts = time.time()
            self._conn.execute(
                "UPDATE backtest_runs SET status = 'COMPLETED', results_json = ?, completed_at = ? "
                "WHERE id = ?",
                (json.dumps(results), ts, run_id),
            )
            for i, artifact_hash in enumerate(artifact_hashes):
                self._conn.execute(
                    "INSERT INTO backtest_artifacts (id, run_id, artifact_name, artifact_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, f"artifact-{i}", artifact_hash, ts),
                )
            self._conn.execute(
                """
                INSERT INTO research_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'backtest_run.completed', ?, ?, 0)
                """,
                (str(uuid.uuid4()), json.dumps({"run_id": run_id}), ts),
            )
            self._conn.execute("COMMIT")
        except ResearchReproducibilityError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return self.get_decision(run_id)

    def reproduce(self, run_id: str) -> dict:
        """Returns a 'reproduction command' - a deterministic descriptor of
        everything needed to redo the run, per Section 13's
        POST /research/backtests/{id}/reproduce. Does not itself launch a
        new run - reproducing is the caller's action, this just hands back
        the pinned manifest."""
        run = self.get_decision(run_id)
        if run is None:
            raise ResearchReproducibilityError(f"RUN_NOT_FOUND: {run_id!r}")
        sv = self._conn.execute(
            "SELECT strategy_name, code_version, code_hash FROM strategy_versions WHERE id = ?",
            (run.strategy_version_id,),
        ).fetchone()
        ds = self._conn.execute(
            "SELECT data_version, data_hash FROM datasets WHERE id = ?", (run.dataset_id,)
        ).fetchone()
        return {
            "run_id": run.id,
            "manifest_hash": run.manifest_hash,
            "strategy_name": sv[0] if sv else None,
            "code_version": sv[1] if sv else None,
            "code_hash": sv[2] if sv else None,
            "data_version": ds[0] if ds else None,
            "data_hash": ds[1] if ds else None,
            "parameters": run.parameters,
            "execution_assumptions": run.execution_assumptions,
            "cost_model": run.cost_model,
            "test_period": run.test_period,
        }

    def get_decision(self, run_id: str) -> Optional[BacktestRun]:
        row = self._conn.execute(
            """
            SELECT id, strategy_version_id, dataset_id, parameters_json, execution_assumptions_json,
                   cost_model_json, test_period_json, manifest_hash, status, correlation_id,
                   idempotency_key, created_at, completed_at, results_json
            FROM backtest_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        artifact_rows = self._conn.execute(
            "SELECT artifact_hash FROM backtest_artifacts WHERE run_id = ?", (run_id,)
        ).fetchall()
        return BacktestRun(
            id=row[0],
            strategy_version_id=row[1],
            dataset_id=row[2],
            parameters=json.loads(row[3]),
            execution_assumptions=json.loads(row[4]),
            cost_model=json.loads(row[5]),
            test_period=json.loads(row[6]),
            manifest_hash=row[7],
            status=row[8],
            correlation_id=row[9],
            idempotency_key=row[10],
            created_at=row[11],
            completed_at=row[12],
            results=json.loads(row[13]) if row[13] else {},
            artifact_hashes=[r[0] for r in artifact_rows],
        )

    def health(self) -> dict:
        return {"status": "OK", "module": 479}
