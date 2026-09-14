"""
Module 481 - Position Sizing Production Engine.

Source: AI Trading Platform Bible V63.0, Section 15 (service contract,
persistence, validation, concurrency, acceptance criteria) and Section 22
("Position Sizing - Exact Production Algorithm", the literal pseudocode
this module transcribes into `size_position()` below - SOURCE, not
derived).

Phase 2 of the DPR implementation. NOT wired into main.py's live
entry/sizing path. Per CLAUDE.md's standing real-money discipline, wiring
this in requires: full pytest green (has it) + full 52-symbol/60-day
replay validation of the actual sizing behavior against the live strategy
+ explicit user go-ahead - none of which has happened yet.

IMPLEMENTATION ASSUMPTIONS (SQLite, no PostgreSQL/message broker - see
docs/dpr_v63_phase1_notes.md for the standing project-wide decision):
  - UUID PKs as TEXT, TIMESTAMPTZ as float unix timestamp.
  - BEGIN IMMEDIATE in place of SELECT ... FOR UPDATE / serializable retry.
  - Outbox is a plain append-only table, not a message broker.
  - `instrument_constraints` (lot size / max qty per instrument) is
    created per the DPR's persistence table list but NOT auto-populated
    in this phase - no module in this codebase yet sources that data.
    Callers pass lot_size/max_qty directly in the request for now (both
    are required Section 22 algorithm inputs regardless).
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Optional

from app.core.decisions import EngineDecision


# --- Section 22: Position Sizing - Exact Production Algorithm --------------
# Transcribed from the DPR verbatim (SOURCE), only renamed Approve/Deny to
# the shared EngineDecision so it composes with the rest of app/core.

def size_position(
    *,
    equity,
    risk_pct,
    stop_loss_per_unit,
    confidence,
    liquidity,
    volatility,
    exposure,
    lot_size,
    max_qty,
) -> EngineDecision:
    D = Decimal
    try:
        equity = D(str(equity))
        risk_pct = D(str(risk_pct))
        stop = D(str(stop_loss_per_unit))
        factors = [D(str(confidence)), D(str(liquidity)), D(str(volatility)), D(str(exposure))]
        lot_size_d = D(str(lot_size))
        max_qty_d = D(str(max_qty))
    except (InvalidOperation, ValueError, TypeError):
        return EngineDecision(False, "INVALID_NUMERIC_INPUT", "a numeric input could not be parsed")

    if equity <= 0:
        return EngineDecision(False, "EQUITY_NON_POSITIVE", "equity must be > 0")
    if not (D("0") < risk_pct <= D("1")):
        return EngineDecision(False, "RISK_PCT_OUT_OF_RANGE", "risk_pct must be in (0, 1]")
    if stop <= 0:
        return EngineDecision(False, "STOP_INVALID", "stop_loss_per_unit must be > 0")
    if any(f < 0 or f > 1 for f in factors):
        return EngineDecision(
            False, "FACTOR_OUT_OF_RANGE",
            "confidence/liquidity/volatility/exposure must each be in [0, 1] - "
            "a factor > 1 is rejected rather than increasing risk (Section 22)",
        )
    if lot_size_d <= 0:
        return EngineDecision(False, "LOT_SIZE_INVALID", "lot_size must be > 0")

    capital_risk_allowed = equity * risk_pct
    raw_units = capital_risk_allowed / stop
    adjusted_units = raw_units
    for f in factors:
        adjusted_units *= f

    # "Never let an adjustment enlarge the source-formula size."
    adjusted_units = min(adjusted_units, raw_units, max_qty_d)
    lots = (adjusted_units / lot_size_d).to_integral_value(rounding=ROUND_DOWN)
    final_qty = lots * lot_size_d

    if final_qty <= 0:
        return EngineDecision(
            False, "SIZE_BELOW_MINIMUM",
            "adjusted size rounds down to zero lots",
            data={
                "capital_risk_allowed": str(capital_risk_allowed),
                "raw_units": str(raw_units),
                "adjusted_units": str(adjusted_units),
            },
        )
    return EngineDecision(
        True, "OK", "approved",
        data={
            "capital_risk_allowed": str(capital_risk_allowed),
            "raw_units": str(raw_units),
            "adjusted_units": str(adjusted_units),
            "final_qty": str(final_qty),
        },
    )


# --- 15.1 Service contract / persistence / idempotency ---------------------

@dataclass
class PositionSizingRequest:
    symbol: str
    equity: str
    risk_pct: str
    stop_loss_per_unit: str
    confidence: str
    liquidity: str
    volatility: str
    exposure: str
    lot_size: str
    max_qty: str
    correlation_id: str
    idempotency_key: str
    config_version: str = "v22-source"


class PositionSizingProductionEngineService:
    """Module 481. See module docstring for implementation assumptions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.isolation_level = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS position_sizing_decisions (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                approved INTEGER NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                config_version TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS instrument_constraints (
                symbol TEXT PRIMARY KEY,
                lot_size TEXT NOT NULL,
                max_qty TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_equity_snapshots (
                id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                equity TEXT NOT NULL,
                ts REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS position_sizing_outbox (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                ts REAL NOT NULL,
                published INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def evaluate(self, request: PositionSizingRequest) -> EngineDecision:
        """15.4: duplicate idempotency_key returns the original result
        rather than re-evaluating (order-of-magnitude important here -
        re-running this with fresh market inputs could size a second,
        unintended position for what the caller believes is one retry)."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT result_json, approved, reason_code, reason FROM position_sizing_decisions "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._conn.execute("ROLLBACK")
                data = json.loads(existing[0])
                return EngineDecision(bool(existing[1]), existing[2], existing[3], data)

            decision = size_position(
                equity=request.equity,
                risk_pct=request.risk_pct,
                stop_loss_per_unit=request.stop_loss_per_unit,
                confidence=request.confidence,
                liquidity=request.liquidity,
                volatility=request.volatility,
                exposure=request.exposure,
                lot_size=request.lot_size,
                max_qty=request.max_qty,
            )

            decision_id = str(uuid.uuid4())
            ts = time.time()
            decision.data["decision_id"] = decision_id
            self._conn.execute(
                """
                INSERT INTO position_sizing_decisions
                    (id, idempotency_key, correlation_id, symbol, approved, reason_code,
                     reason, request_json, result_json, config_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    request.idempotency_key,
                    request.correlation_id,
                    request.symbol,
                    1 if decision.approved else 0,
                    decision.reason_code,
                    decision.reason,
                    json.dumps(request.__dict__),
                    json.dumps(decision.data),
                    request.config_version,
                    ts,
                ),
            )
            self._conn.execute(
                "INSERT INTO account_equity_snapshots (id, decision_id, equity, ts) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), decision_id, str(request.equity), ts),
            )
            self._conn.execute(
                """
                INSERT INTO position_sizing_outbox (id, event_type, payload_json, ts, published)
                VALUES (?, 'position_sizing.decided', ?, ?, 0)
                """,
                (
                    str(uuid.uuid4()),
                    json.dumps(
                        {
                            "decision_id": decision_id,
                            "symbol": request.symbol,
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

    def get_decision(self, decision_id: str) -> Optional[EngineDecision]:
        row = self._conn.execute(
            "SELECT approved, reason_code, reason, result_json FROM position_sizing_decisions "
            "WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        return EngineDecision(bool(row[0]), row[1], row[2], json.loads(row[3]))

    def health(self) -> dict:
        return {"status": "OK", "module": 481}
