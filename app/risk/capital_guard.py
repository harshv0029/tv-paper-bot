"""
Module 482 - Live Capital Guard Engine.

Source: AI Trading Platform Bible V63.0, Section 16 (service contract,
persistence, acceptance criteria) and Section 23 ("Live Capital Guard -
Severity Evaluation and Actions" - the severity/action table and the
capital_guard() pseudocode, both transcribed below as SOURCE).

Phase 3 of the DPR implementation. NOT wired into main.py's live path -
same bar as Phases 1-2 applies before any wiring: full pytest green (has
it) + full replay validation + explicit user go-ahead.

IMPLEMENTATION ASSUMPTIONS:
  - Section 23's pseudocode calls evaluate_all_dimensions(snapshot, policy)
    without defining it anywhere in the extracted document. This module
    supplies it as a 3-threshold-per-dimension model (soft -> WARNING,
    hard -> REDUCE, critical -> EXIT). Each dimension is flagged
    higher_is_worse=True (exposure/margin/drawdown/correlation/volatility)
    or False (liquidity - Section 15's "poor liquidity reduces size"
    establishes liquidity as a 0..1 quality factor where LOWER is worse,
    the only one of these six dimensions with a stated direction anywhere
    in the source).
  - "Protection mode is durable and requires controlled recovery" (Section
    16 primary rule, AC-482-03) is implemented as a latch: once a
    snapshot evaluates to CAPITAL_PROTECTION_MODE for a portfolio, every
    subsequent evaluate() for that portfolio returns
    CAPITAL_PROTECTION_MODE regardless of the new snapshot's own computed
    severity, until an explicit clear_protection() call.
    clear_protection() requires a privileged actor + a persisted
    validation checklist id - DERIVED, mirroring Module 478's identical
    HUMAN_OVERRIDE_REQUIRED resume gate (12.3), since Section 16 does not
    re-specify recovery mechanics and Module 478 already establishes this
    project's convention for "controlled recovery".
  - SQLite/no-broker assumptions as in Phases 1-2 (see
    docs/dpr_v63_phase1_notes.md): UUID PKs as TEXT, TIMESTAMPTZ as float
    unix timestamp, BEGIN IMMEDIATE in place of SELECT...FOR UPDATE,
    outbox as a plain append-only table.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import Optional


class Severity(IntEnum):
    NORMAL = 0
    WARNING = 1
    REDUCE = 2
    EXIT = 3
    CAPITAL_PROTECTION_MODE = 4


# Section 23's severity/action table (SOURCE), minus the WARNING row's
# policy-conditional "forbid risk increases if policy says so" - that part
# is appended in capital_guard() based on the policy flag.
ACTIONS_FOR_SEVERITY = {
    Severity.NORMAL: ["normal_operation"],
    Severity.WARNING: ["notify"],
    Severity.REDUCE: ["cancel_risk_increasing_orders", "reduce_selected_exposure"],
    Severity.EXIT: ["submit_exit_commands"],
    Severity.CAPITAL_PROTECTION_MODE: [
        "no_new_openings",
        "reconcile",
        "reduce_or_exit",
        "require_validated_recovery",
    ],
}

DIMENSIONS = ("exposure", "margin", "drawdown", "correlation", "volatility", "liquidity")
HIGHER_IS_WORSE = {
    "exposure": True,
    "margin": True,
    "drawdown": True,
    "correlation": True,
    "volatility": True,
    "liquidity": False,
}


@dataclass
class DimensionPolicy:
    soft_limit: Optional[str] = None
    hard_limit: Optional[str] = None
    critical_limit: Optional[str] = None


@dataclass
class CapitalGuardSnapshot:
    portfolio_id: str
    exposure: str
    margin: str
    drawdown: str
    correlation: str
    volatility: str
    liquidity: str
    data_quality: str  # 'VALID' or anything else
    broker_position_reconciled: bool
    correlation_id: str
    idempotency_key: str


@dataclass
class Breach:
    dimension: str
    severity: Severity
    value: str
    limit_breached: Optional[str]


@dataclass
class GuardDecision:
    severity: Severity
    breaches: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    forced_protection: bool = False
    id: Optional[str] = None


class CapitalGuardError(Exception):
    pass


def _dimension_severity(
    value: Decimal, dp: DimensionPolicy, higher_is_worse: bool
) -> tuple[Severity, Optional[str]]:
    for limit_str, sev in (
        (dp.critical_limit, Severity.EXIT),
        (dp.hard_limit, Severity.REDUCE),
        (dp.soft_limit, Severity.WARNING),
    ):
        if limit_str is None:
            continue
        limit = Decimal(str(limit_str))
        breached = (value >= limit) if higher_is_worse else (value <= limit)
        if breached:
            return sev, str(limit_str)
    return Severity.NORMAL, None


def evaluate_all_dimensions(
    snapshot: CapitalGuardSnapshot, dimension_policies: dict
) -> list:
    """IMPLEMENTATION - see module docstring. Returns one Breach per
    dimension currently outside NORMAL."""
    breaches = []
    for dim in DIMENSIONS:
        dp = dimension_policies.get(dim)
        if dp is None:
            continue
        try:
            value = Decimal(str(getattr(snapshot, dim)))
        except (InvalidOperation, ValueError, TypeError):
            continue
        sev, limit_breached = _dimension_severity(value, dp, HIGHER_IS_WORSE[dim])
        if sev != Severity.NORMAL:
            breaches.append(Breach(dim, sev, str(value), limit_breached))
    return breaches


def capital_guard(
    snapshot: CapitalGuardSnapshot,
    dimension_policies: dict,
    *,
    forbid_risk_increase_on_warning: bool = True,
) -> GuardDecision:
    """Section 23's exact pseudocode (SOURCE)."""
    breaches = evaluate_all_dimensions(snapshot, dimension_policies)
    severity = max((b.severity for b in breaches), default=Severity.NORMAL)
    if snapshot.data_quality != "VALID":
        severity = max(severity, Severity.CAPITAL_PROTECTION_MODE)
    if snapshot.broker_position_reconciled is False:
        severity = max(severity, Severity.CAPITAL_PROTECTION_MODE)

    actions = list(ACTIONS_FOR_SEVERITY[severity])
    if severity == Severity.WARNING and forbid_risk_increase_on_warning:
        actions.append("forbid_risk_increases")

    return GuardDecision(severity=severity, breaches=breaches, actions=actions)


# --- 16.1 Service contract / persistence / idempotency ---------------------


class LiveCapitalGuardEngineService:
    """Module 482. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_guard_policies (
                portfolio_id TEXT PRIMARY KEY,
                dimensions_json TEXT NOT NULL,
                forbid_risk_increase_on_warning INTEGER NOT NULL,
                config_version TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_snapshots (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                portfolio_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                severity TEXT NOT NULL,
                forced_protection INTEGER NOT NULL,
                config_version TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_breaches (
                id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                severity TEXT NOT NULL,
                value TEXT NOT NULL,
                limit_breached TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_guard_actions (
                id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                actions_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_guard_state (
                portfolio_id TEXT PRIMARY KEY,
                in_protection INTEGER NOT NULL,
                version INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capital_guard_outbox (
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
        dimension_policies: dict,
        *,
        forbid_risk_increase_on_warning: bool = True,
        config_version: str,
    ) -> None:
        dims_json = json.dumps({k: v.__dict__ for k, v in dimension_policies.items()})
        self._conn.execute(
            """
            INSERT INTO capital_guard_policies
                (portfolio_id, dimensions_json, forbid_risk_increase_on_warning, config_version, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(portfolio_id) DO UPDATE SET
                dimensions_json = excluded.dimensions_json,
                forbid_risk_increase_on_warning = excluded.forbid_risk_increase_on_warning,
                config_version = excluded.config_version,
                updated_at = excluded.updated_at
            """,
            (
                portfolio_id,
                dims_json,
                1 if forbid_risk_increase_on_warning else 0,
                config_version,
                time.time(),
            ),
        )

    def evaluate(self, snapshot: CapitalGuardSnapshot) -> GuardDecision:
        """16: 'Risk is monitored continuously, not only before order
        creation' - callers are expected to call this on every cycle, not
        just pre-trade. Idempotency per 16.4: duplicate idempotency_key
        returns the original decision."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT id FROM risk_snapshots WHERE idempotency_key = ?",
                (snapshot.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                return self.get_decision(existing[0])

            policy_row = self._conn.execute(
                "SELECT dimensions_json, forbid_risk_increase_on_warning, config_version "
                "FROM capital_guard_policies WHERE portfolio_id = ?",
                (snapshot.portfolio_id,),
            ).fetchone()
            if policy_row is None:
                self._conn.execute("ROLLBACK")
                raise CapitalGuardError(
                    f"NO_POLICY_CONFIGURED: no capital_guard_policies row for "
                    f"portfolio {snapshot.portfolio_id!r}; call set_policy() first"
                )
            dims_raw = json.loads(policy_row[0])
            dimension_policies = {k: DimensionPolicy(**v) for k, v in dims_raw.items()}
            forbid_on_warning = bool(policy_row[1])
            config_version = policy_row[2]

            state_row = self._conn.execute(
                "SELECT in_protection, version FROM capital_guard_state WHERE portfolio_id = ?",
                (snapshot.portfolio_id,),
            ).fetchone()
            in_protection = bool(state_row[0]) if state_row else False
            state_version = state_row[1] if state_row else 0

            decision = capital_guard(
                snapshot, dimension_policies, forbid_risk_increase_on_warning=forbid_on_warning
            )

            forced = False
            if in_protection:
                # Durable latch (Section 16 primary rule / AC-482-03): a
                # clean snapshot does not self-heal out of protection mode.
                decision = GuardDecision(
                    severity=Severity.CAPITAL_PROTECTION_MODE,
                    breaches=decision.breaches,
                    actions=list(ACTIONS_FOR_SEVERITY[Severity.CAPITAL_PROTECTION_MODE]),
                    forced_protection=True,
                )
                forced = True

            decision_id = str(uuid.uuid4())
            decision.id = decision_id
            ts = time.time()

            self._conn.execute(
                """
                INSERT INTO risk_snapshots
                    (id, idempotency_key, correlation_id, portfolio_id, snapshot_json,
                     severity, forced_protection, config_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    snapshot.idempotency_key,
                    snapshot.correlation_id,
                    snapshot.portfolio_id,
                    json.dumps(snapshot.__dict__),
                    decision.severity.name,
                    1 if forced else 0,
                    config_version,
                    ts,
                ),
            )
            for b in decision.breaches:
                self._conn.execute(
                    """
                    INSERT INTO risk_breaches
                        (id, decision_id, dimension, severity, value, limit_breached, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), decision_id, b.dimension, b.severity.name, b.value,
                     b.limit_breached, ts),
                )
            self._conn.execute(
                "INSERT INTO capital_guard_actions (id, decision_id, actions_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), decision_id, json.dumps(decision.actions), ts),
            )

            if decision.severity == Severity.CAPITAL_PROTECTION_MODE and not in_protection:
                self._conn.execute(
                    """
                    INSERT INTO capital_guard_state (portfolio_id, in_protection, version, updated_at)
                    VALUES (?, 1, ?, ?)
                    ON CONFLICT(portfolio_id) DO UPDATE SET
                        in_protection = 1, version = excluded.version, updated_at = excluded.updated_at
                    """,
                    (snapshot.portfolio_id, state_version + 1, ts),
                )

            self._conn.execute(
                """
                INSERT INTO capital_guard_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'capital_guard.decided', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps(
                        {
                            "decision_id": decision_id,
                            "portfolio_id": snapshot.portfolio_id,
                            "severity": decision.severity.name,
                            "correlation_id": snapshot.correlation_id,
                        }
                    ),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except CapitalGuardError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        return decision

    def clear_protection(
        self, portfolio_id: str, *, privileged_actor: Optional[str], validation_checklist_id: Optional[str]
    ) -> bool:
        """DERIVED - mirrors Module 478's HUMAN_OVERRIDE_REQUIRED resume
        gate (12.3): leaving a durable CAPITAL_PROTECTION_MODE latch
        requires a privileged actor and a persisted validation checklist
        id. Returns False (no-op, nothing persisted) if either is missing."""
        if not (privileged_actor and validation_checklist_id):
            return False
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT version FROM capital_guard_state WHERE portfolio_id = ?", (portfolio_id,)
            ).fetchone()
            version = row[0] if row else 0
            ts = time.time()
            self._conn.execute(
                """
                INSERT INTO capital_guard_state (portfolio_id, in_protection, version, updated_at)
                VALUES (?, 0, ?, ?)
                ON CONFLICT(portfolio_id) DO UPDATE SET
                    in_protection = 0, version = excluded.version, updated_at = excluded.updated_at
                """,
                (portfolio_id, version + 1, ts),
            )
            self._conn.execute(
                """
                INSERT INTO capital_guard_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'capital_guard.protection_cleared', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps(
                        {
                            "portfolio_id": portfolio_id,
                            "privileged_actor": privileged_actor,
                            "validation_checklist_id": validation_checklist_id,
                        }
                    ),
                    ts,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return True

    def get_decision(self, decision_id: str) -> Optional[GuardDecision]:
        row = self._conn.execute(
            "SELECT severity, forced_protection FROM risk_snapshots WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        severity = Severity[row[0]]
        forced = bool(row[1])
        breach_rows = self._conn.execute(
            "SELECT dimension, severity, value, limit_breached FROM risk_breaches "
            "WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()
        breaches = [Breach(r[0], Severity[r[1]], r[2], r[3]) for r in breach_rows]
        action_row = self._conn.execute(
            "SELECT actions_json FROM capital_guard_actions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        actions = json.loads(action_row[0]) if action_row else []
        return GuardDecision(
            severity=severity, breaches=breaches, actions=actions,
            forced_protection=forced, id=decision_id,
        )

    def health(self) -> dict:
        return {"status": "OK", "module": 482}
