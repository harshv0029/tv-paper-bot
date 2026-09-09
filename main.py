"""
TradingView Paper Trading Webhook Receiver
-------------------------------------------
Receives TradingView alert webhooks and logs SIMULATED (paper) trades.
No real orders are ever sent to any broker from this app.

Endpoints:
  POST /webhook      -> TradingView posts alerts here
  GET  /positions     -> current simulated open positions
  GET  /trades        -> full trade log
  GET  /pnl           -> realized + unrealized P&L summary
  GET  /health        -> uptime check
  GET  /history       -> historical OHLC data for strategy research/backtesting
                         (this server has real internet access; Claude's own
                         workspace does not, so this is the automatic data path)
"""

import asyncio
import datetime as dt
import json
import math
import os
import sqlite3
import time
from contextlib import closing
from itertools import product

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 2026-09-04 structure split (docs/PROJECT_STRUCTURE_PLAN.md Phase 1) - pure
# code motion, re-exported here under their original names so every existing
# main.py call site (and main.<name> from tests/) keeps working unchanged.
from constants import (
    ORB_STRATEGY_PREFIX, OPTIONS_ELIGIBLE_SYMBOLS, OPTIONS_TARGET_DELTA,
    OPTIONS_MIN_DTE, OPTIONS_MAX_DTE, OPTIONS_MAX_IV_VS_ATM,
    OPTIONS_MAX_SPREAD_PCT, OPTIONS_STOP_PCT, OPTIONS_STRATEGY_TAG,
)
from data_fetch import fetch_ohlc, get_fx_to_inr, _DATA_CACHE, _CACHE_TTL_SECONDS
import sentiment_signals
from options_pricing import (
    _norm_cdf, bs_price, parse_legs, run_options_backtest, _bs_delta,
    select_option_contract, _requote_contract,
)
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "paper_trades.db")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
STARTING_CASH = float(os.environ.get("STARTING_CASH", "100000"))  # paper capital

# No single new trade may claim more than capital/CAPITAL_TRANCHES of the
# shared pool, even when more sits free - reserves room for other real
# opportunities to be taken in parallel rather than one position locking
# out the rest of the day. 2 = the account's current split (a trade can use
# at most half the pool at once); raise for finer-grained parallelism.
CAPITAL_TRANCHES = 2

app = FastAPI(title="TradingView Paper Trading Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Allows the dashboard (a page hosted on a different domain) to call /history,
# /backtest, /sweep directly from the browser. Fine for these read-only,
# unauthenticated GET endpoints - /webhook is POST-only and still requires the
# secret, so this does not weaken that.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --- Real-money external persistence (Upstash Redis) ------------------------
# Render's free tier has no persistent disk - every restart wipes real_positions
# along with every other table (see data_fetch.py's own comment for the same
# fact). A git-committed JSON journal already exists for this (see
# STATE_REAL_POSITIONS_PATH / reconcile_real_positions_from_journal below),
# but it's only as fresh as the last journal-sync run (up to ~15 min, or
# worse mid-day) AND its own commit+push is itself another restart-triggering
# event - provably too slow: the 2026-09-08 AARTIIND incident was exactly a
# restart landing inside that gap, wiping a just-adopted real position's
# governance before either the journal or the next scheduler tick caught up.
#
# Explicit user instruction 2026-09-08 ("free/minimal-cost path, real-money
# tables only"): mirror real_positions - and ONLY real_positions, the table
# that actually costs real money if silently lost - to Upstash Redis's free
# tier (REST API, no persistent connection needed, comfortably within this
# app's real write volume) on every single mutation, synchronously, in the
# same request that made the change. No git commit, no push, no periodic-
# sync wait in either direction - closes the exact race that bit AARTIIND.
# The rest of the DB (paper trading, backtests, scan cursors) stays on
# ephemeral SQLite exactly as before; those don't cost real money if wiped.
#
# Degrades to a silent no-op if the two env vars aren't set (same graceful-
# degradation pattern as KOTAK_NEO_API_TOKEN elsewhere in this file) - the
# git-JSON journal keeps working as a second-layer fallback regardless.
UPSTASH_REDIS_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
_REAL_POSITIONS_REDIS_KEY = "tv_paper_bot:real_positions:v1"


def _sync_real_positions_external(conn) -> None:
    """Pushes a full snapshot of real_positions to Upstash - call this right
    after every commit that touches real_positions (INSERT on entry, UPDATE
    on sl/target order id, DELETE on exit/ghost-cleanup). Best-effort and
    silent: a failure here must never break real trading - the write has
    already committed to SQLite; this is only the durability mirror, not
    this process's own source of truth for its own lifetime."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM real_positions").fetchall()]
        payload = json.dumps({"synced_at": time.time(), "rows": rows})
        requests.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{_REAL_POSITIONS_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            data=payload.encode("utf-8"),
            timeout=5,
        )
    except Exception as e:
        print(f"[real_positions_external] sync failed (non-fatal): {e}")


def hydrate_real_positions_from_external() -> bool:
    """Startup-time restore, sourced from Upstash instead of (in addition
    to) the slower git-JSON journal - see reconcile_real_positions_from_journal
    below, which the startup call site now only runs as a second-layer
    fallback when this returns False (Upstash unset or unreachable). Never
    places any order - only restores this app's own tracking of a position
    that already exists at the broker, same as the journal-based reconcile.

    Returns True iff Upstash was actually reached, regardless of whether
    any rows came back - an EMPTY-but-successful read is still
    authoritative and must suppress the git-journal fallback below, not
    just a non-empty one.

    BUG found live 2026-09-08: this used to return None unconditionally,
    so the startup call site always ALSO ran
    reconcile_real_positions_from_journal regardless of whether Upstash
    hydration succeeded - a symbol Upstash correctly held as CLOSED
    (ghost-removed by an earlier reconcile) still got resurrected by the
    git journal's own stale, up-to-~15-min-old snapshot, which has no way
    to know about a cleanup that happened after its last sync. Confirmed
    live: AGL.NS/BHANDARI.NS, already ghost-removed from real_positions
    multiple times earlier the same day, came back again after this exact
    restart."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return False
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{_REAL_POSITIONS_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("result")
    except Exception as e:
        print(f"[real_positions_external] hydrate failed (non-fatal): {e}")
        return False
    rows = json.loads(raw).get("rows", []) if raw else []
    if rows:
        with closing(get_db()) as conn:
            restored = 0
            for pos in rows:
                if conn.execute("SELECT 1 FROM real_positions WHERE symbol = ?", (pos["symbol"],)).fetchone():
                    continue
                conn.execute(
                    "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
                    "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, "
                    "target_order_id, target_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pos["symbol"], pos["kotak_trading_symbol"], pos["qty"], pos["entry_price"],
                     pos.get("entry_order_id"), pos["opened_at"], pos["day"],
                     pos.get("sl_order_id"), pos.get("sl_trigger_price"),
                     pos.get("target_order_id"), pos.get("target_price")),
                )
                restored += 1
            if restored:
                conn.commit()
                print(f"[real_positions_external] restored {restored} real position(s) from Upstash")
    return True


# --- Scan-coverage external persistence (Upstash Redis) ----------------------
# Same restart-race family as real_positions above, different symptom: the
# round-robin scan cursor (_scheduler_rr_cursor, defined far below) is a
# plain in-memory int, only ever persisted to the slower git-JSON journal
# (state/scheduler_check_counts.json, synced ~every 15 min or on push - see
# reconcile_scheduler_check_counts_from_journal's own docstring for the
# original 2026-09-08 finding: "still stuck 358 distinct... how to ensure
# it can scan all 2661 every 15 minutes"). That fix helped, but on a day
# with MANY restarts close together (confirmed live 2026-09-08: rr_cursor
# read back as 0 mid-afternoon, hours into the trading session, after a
# string of deploys each restarting Render faster than journal-sync's own
# cadence could keep up) the cursor keeps losing forward progress before a
# single full rotation (2661/35 ~= 76 ticks ~= ~38 min) can complete -
# every restart sends it back toward the START of WATCHLIST's ordering,
# so the "distinct symbols scanned" count stalls even though the total
# check count keeps climbing (re-scanning the same early symbols, not
# covering new ones). Mirrors real_positions' fix exactly: a small,
# synchronous, real-time mirror closes the gap the periodic journal can't.
_RR_CURSOR_REDIS_KEY = "tv_paper_bot:rr_cursor:v1"


def _sync_rr_cursor_external(cursor: int) -> None:
    """Call this right after _scheduler_rr_cursor advances (every tick that
    actually scans a round-robin batch). Best-effort and silent, same
    pattern as _sync_real_positions_external - a failure here must never
    break the scheduler tick that's calling it."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return
    try:
        requests.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{_RR_CURSOR_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            data=str(int(cursor)).encode("utf-8"),
            timeout=5,
        )
    except Exception as e:
        print(f"[rr_cursor_external] sync failed (non-fatal): {e}")


def hydrate_rr_cursor_from_external() -> int | None:
    """Startup-time restore, sourced from Upstash - real-time, so it wins
    over the slower git journal (reconcile_scheduler_check_counts_from_journal
    still runs too and restores everything else that file carries; its own
    rr_cursor restore is now only reached when this returns None). Returns
    the cursor value, or None if Upstash is unset/unreachable/empty - the
    cursor is re-modded against the current flat-symbol count on every
    tick regardless (see _scheduler_loop), so restoring a raw int here
    needs no bounds-checking against today's specific watchlist/market-hours
    state."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{_RR_CURSOR_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("result")
        return int(raw) if raw is not None else None
    except Exception as e:
        print(f"[rr_cursor_external] hydrate failed (non-fatal): {e}")
        return None


# check_counts (the "distinct symbols scanned today" state) - 2026-09-09,
# explicit user finding: "751 total checks run today (751 / 2661
# distinct)... these two numbers are getting reset again. why so? have u
# not fixed?" They were right to push back - the rr_cursor fix above only
# covered the round-robin CURSOR (an int), not the check_counts dict
# itself (per-symbol counts, the thing "distinct scanned" is actually
# computed from - see check_counts_today_rows below). That dict was STILL
# only persisted to the slower git journal (journal-sync.yml, every 15
# min - see reconcile_scheduler_check_counts_from_journal), with no
# Upstash mirror of its own, so a restart happening more often than every
# 15 min (this Render service's own restart cadence, independent of any
# push) wipes it back to empty before the next journal sync could have
# captured it, even though rr_cursor itself now survives fine. Same fix
# family as rr_cursor, applied to the actual dict this time: synced once
# per TICK (not per symbol - up to ~2661 keys, so a per-symbol sync would
# be dozens of Upstash writes per tick), hydrated first on startup.
_CHECK_COUNTS_REDIS_KEY = "tv_paper_bot:scheduler_check_counts:v1"


def _sync_check_counts_external(day: str, counts: dict) -> None:
    """Call once per scheduler tick, after that tick's checks have all
    run. Best-effort and silent, same pattern as _sync_rr_cursor_external -
    a failure here must never break the scheduler tick that's calling it."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return
    try:
        requests.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{_CHECK_COUNTS_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            data=json.dumps({"day": day, "counts": counts}).encode("utf-8"),
            timeout=5,
        )
    except Exception as e:
        print(f"[check_counts_external] sync failed (non-fatal): {e}")


def hydrate_check_counts_from_external() -> tuple[str, dict] | None:
    """Startup-time restore, sourced from Upstash - real-time (synced once
    per ~30s tick), so it wins over the slower git journal
    (reconcile_scheduler_check_counts_from_journal's own counts restore is
    only reached when this returns None). Returns (day, counts), or None
    if Upstash is unset/unreachable/empty/malformed."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{_CHECK_COUNTS_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("result")
        if not raw:
            return None
        saved = json.loads(raw)
        day, counts = saved.get("day"), saved.get("counts")
        if not day or not isinstance(counts, dict):
            return None
        return day, counts
    except Exception as e:
        print(f"[check_counts_external] hydrate failed (non-fatal): {e}")
        return None


def init_db():
    with closing(get_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,      -- buy | sell
                qty REAL NOT NULL,
                price REAL NOT NULL,
                fx_to_inr REAL NOT NULL DEFAULT 1.0,  -- price*fx_to_inr = INR value/unit
                strategy TEXT,
                raw_payload TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_state (
                symbol TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                status TEXT NOT NULL,   -- 'long'
                entry_price REAL,       -- native currency (e.g. USD for SPY)
                stop_loss REAL,         -- native currency - LIVE value, ratchets up as the trailing
                                        -- stop engages (see _trailing_stop_target); this is what the
                                        -- stop_hit check actually compares against
                initial_stop_loss REAL, -- native currency - the stop AT ENTRY, frozen forever; R
                                        -- (entry_price - initial_stop_loss) is the trailing stop's
                                        -- own activation/breakeven yardstick, independent of how far
                                        -- stop_loss has already trailed
                target REAL,            -- native currency
                qty REAL,
                entry_ts REAL,
                orb_high REAL,
                orb_low REAL,
                fx_to_inr REAL NOT NULL DEFAULT 1.0,  -- captured at entry; entry_price*fx_to_inr = INR/unit
                interval TEXT NOT NULL DEFAULT '5m'   -- candle size this trade was taken on
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS option_state (
                opt_symbol TEXT PRIMARY KEY,  -- "{underlying}:OPT-CALL" / "{underlying}:OPT-PUT"
                underlying TEXT NOT NULL,
                day TEXT NOT NULL,
                right TEXT NOT NULL,          -- call | put
                expiry TEXT NOT NULL,         -- YYYY-MM-DD
                strike REAL NOT NULL,
                contracts REAL NOT NULL,      -- 1 contract = 100 shares, the real multiplier
                entry_premium REAL NOT NULL,  -- native currency, per share
                stop_premium REAL NOT NULL,
                target_premium REAL NOT NULL,
                entry_iv REAL,
                entry_delta REAL,
                entry_ts REAL NOT NULL,
                fx_to_inr REAL NOT NULL DEFAULT 1.0
            )
            """
        )
        # Long Straddle - NEW strategy added 2026-09-07, explicit user
        # instruction ("there are strategies where put and call are
        # together less than half of total cost too" - docs/
        # STRATEGY_LOG.md row #3, "Expect big move, direction unknown
        # (vol expansion)"). Genuinely separate from option_state above:
        # that table (and the whole US-underlier options engine it
        # belonged to) has been dormant since OPTIONS_ELIGIBLE_SYMBOLS
        # was emptied 2026-09-03. This is a fresh, NSE-real-chain-backed
        # (nse_fo_chain.py), NOT YET BACKTESTED strategy - paper-tracked
        # here always; real order mirroring is a SEPARATE opt-in (see
        # is_real_fo_trading_enabled + the real_straddle_enabled runtime
        # setting, both default OFF) so real capital is never put behind
        # an unproven signal without the user's own deliberate switch.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nse_straddle_state (
                underlying TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                expiry TEXT NOT NULL,
                strike REAL NOT NULL,
                lot_size INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                call_entry_premium REAL NOT NULL,
                put_entry_premium REAL NOT NULL,
                call_kotak_symbol TEXT,
                put_kotak_symbol TEXT,
                call_instrument_token TEXT,
                put_instrument_token TEXT,
                entry_ts REAL NOT NULL,
                fx_to_inr REAL NOT NULL DEFAULT 1.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_control (
                id INTEGER PRIMARY KEY CHECK (id = 1),  -- single row - one master switch, not per-symbol
                enabled INTEGER NOT NULL DEFAULT 1,     -- 1 = new entries allowed, 0 = paused
                updated_at REAL,
                updated_by TEXT,
                reason TEXT
            )
            """
        )
        # Live-editable risk/scheduling thresholds (2026-09-07, explicit user
        # instruction: "i want all of your constraints on the render web
        # page so that i directly make changes for thresholds ... to make
        # it go live immediately"). Before this, values like the daily loss
        # cap % or the scheduler's entry-scan batch size were plain Python
        # constants - changing them meant a code edit -> staging ->
        # deploy-gate -> Render redeploy, same multi-minute ceremony as
        # every other code change. This table is checked LIVE (see
        # get_runtime_setting, RUNTIME_SETTINGS_DEFAULTS below) so a value
        # written here takes effect on the VERY NEXT scheduler tick, no
        # redeploy at all. Key-value, one row per setting, so adding a new
        # tunable later never needs a schema migration.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL,
                updated_at REAL,
                updated_by TEXT
            )
            """
        )
        # --- Stage 3: real order placement (2026-09-04) --------------------
        # Explicit user instruction. Deliberately its OWN kill switch, NOT
        # a reuse of trading_control above - pausing/resuming PAPER trading
        # must never accidentally arm or disarm REAL trading, and vice
        # versa. Default enabled=0 (OFF) - the opposite default of
        # trading_control's enabled=1 - so a fresh DB (a redeploy with no
        # journal yet, or the very first deploy of this table) never
        # accidentally starts real trading.
        #
        # VESTIGIAL as of 2026-09-04 (later same day): explicit user
        # instruction removed this switch's UI (the token-gated unlock
        # popup on trade-view) in favor of controlling real trading via
        # just the paper kill switch + the Render env var. is_real_trading_
        # enabled() below no longer reads this table - found live, the
        # hard way: this row was sitting at enabled=1 with no UI control
        # left to see or change it, which would have silently kept real
        # orders armed. Table/endpoints kept (not deleted) as an inert
        # audit trail rather than ripping out a live-money code path
        # without more room to verify nothing else depends on it.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_trading_control (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL DEFAULT 0,     -- 1 = real entries allowed, 0 = off (default)
                updated_at REAL,
                updated_by TEXT,
                reason TEXT
            )
            """
        )
        # Currently-open REAL positions - mirrors signal_state's shape but
        # kept fully separate (paper and real must never share a row/table,
        # so a bug in one can't corrupt the other's state). One row per
        # symbol with an open real position; deleted on real exit.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_positions (
                symbol TEXT PRIMARY KEY,
                kotak_trading_symbol TEXT NOT NULL,
                qty INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_order_id TEXT,
                opened_at REAL NOT NULL,
                day TEXT NOT NULL,
                sl_order_id TEXT,
                sl_trigger_price REAL,
                target_order_id TEXT,
                target_price REAL
            )
            """
        )
        # T1-holdings restriction blacklist (2026-09-08, explicit user
        # instruction: "if ever such asset is classified as T1 holding then
        # dont trade in that as they are risk"). Kotak's own RMS rule
        # ("RMS:Rule: Check T1 holdings...No Holdings Present...") rejects
        # an algo-tagged SELL (SL placement or exit) against a same-day CNC
        # buy until T1 settlement - seen live, repeatedly, across many
        # symbols this session (AGL, BHANDARI, AARTIIND, ADANIPOWER,
        # ABSLNN50ET, ADVENTHTL). A symbol that's already hit this once
        # today is a real execution risk (can't reliably protect a fresh
        # position with a resting stop for potentially the rest of the
        # day) - flagged here the first time it's seen, checked before any
        # NEW real entry. day-scoped, not permanent: T1 settlement clears
        # overnight, so a symbol flagged today may trade fine tomorrow.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_t1_restricted (
                symbol TEXT NOT NULL,
                day TEXT NOT NULL,
                flagged_at REAL NOT NULL,
                detail TEXT,
                PRIMARY KEY (symbol, day)
            )
            """
        )
        # sl_order_id/sl_trigger_price added 2026-09-07 for real resting
        # stop-loss orders (see kotak_real_orders.place_real_stop_loss) -
        # no ALTER TABLE needed, this app's SQLite DB has no persistent
        # disk on Render's free tier (see data_fetch.py's memory-leak
        # comment for the same fact) - every process start CREATEs fresh.
        # target_order_id/target_price added 2026-09-08 for real resting
        # profit-booking orders, same no-ALTER-TABLE reasoning - see
        # kotak_real_orders.place_real_target and main.py's
        # _maybe_place_real_entry (placement) / _maybe_place_real_exit
        # (cancellation) for the full flow.
        # Full audit log of every real-order ATTEMPT (confirmed, failed, or
        # skipped-and-why) - the permanent record real money needs, kept
        # uncapped like docs/attempt_log.json's paper equivalent. notional_inr
        # is only set for a CONFIRMED buy - that's the only thing that counts
        # against the Rs 500/day cap (see _real_today_spent_inr).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                day TEXT NOT NULL,
                symbol TEXT NOT NULL,
                kotak_trading_symbol TEXT,
                side TEXT NOT NULL,               -- 'B' or 'S'
                qty INTEGER,
                price_est REAL,
                notional_inr REAL,
                status TEXT NOT NULL,             -- 'confirmed' | 'failed' | 'skipped_...'
                order_id TEXT,
                detail TEXT,
                raw_response TEXT
            )
            """
        )
        # Order STATE-TRANSITION log (2026-09-08) - explicit user
        # instruction: "I want to see the log of what order you have
        # placed and from what prev state to what current new order
        # state." real_trades above is the spend-cap ledger (entry/exit
        # only, side B/S, used by _real_today_spent_inr) - this table is
        # a separate, purely-additive, human-readable history of EVERY
        # real order-state change this app makes: entry, exit, AND the
        # two resting legs (sl/target) that real_trades never covered at
        # all (their placed/moved/cancelled/rejected events previously
        # only ever went to a print() line in Render's own logs, gone the
        # moment that log scrolled). Every call site that already changes
        # a real order's state also calls _log_real_order_event - see that
        # function's own docstring. Kept forever, uncapped, same durable-
        # audit-trail policy as real_trades/attempt_log.json; surfaced via
        # GET /real-order-log and static/order-log.html (GET /order-log).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                symbol TEXT NOT NULL,
                kotak_trading_symbol TEXT,
                leg TEXT NOT NULL,      -- 'entry' | 'exit' | 'sl' | 'target'
                event TEXT NOT NULL,    -- 'placed' | 'moved' | 'cancelled' | 'cancel_failed' |
                                        -- 'failed' | 'confirmed' | 'skipped_duplicate'
                order_id TEXT,
                prev_state TEXT,        -- human-readable, e.g. "resting SELL trigger Rs15.36" or "none"
                new_state TEXT,         -- human-readable, e.g. "resting SELL trigger Rs15.66"
                detail TEXT
            )
            """
        )
        # Real F&O positions/audit log - added 2026-09-07, explicit user
        # instruction ("i can update the capital any time. so build it
        # right now" + "there are strategies where put and call are
        # together less than half of total cost too") - SEPARATE from
        # real_positions/real_trades (equity, CNC, qty=1-share) on
        # purpose: F&O is lot-sized, margin/premium-based, and gated by
        # its OWN switch (see is_real_fo_trading_enabled) - enabling
        # equity real trading never silently enables this too. leg_key
        # is e.g. "NIFTY:CALL" (single-leg directional mirror) or
        # "NIFTY:STRADDLE-CE"/"NIFTY:STRADDLE-PE" (long straddle, two
        # rows, opened/closed together - see _straddle_signal_core).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_fo_positions (
                leg_key TEXT PRIMARY KEY,
                underlying TEXT NOT NULL,
                strategy_tag TEXT NOT NULL,
                kotak_trading_symbol TEXT NOT NULL,
                instrument_token TEXT NOT NULL,
                exchange_segment TEXT NOT NULL,
                expiry TEXT,
                strike REAL,
                lot_size INTEGER,
                qty INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_order_id TEXT,
                opened_at REAL NOT NULL,
                day TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS real_fo_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                day TEXT NOT NULL,
                leg_key TEXT NOT NULL,
                kotak_trading_symbol TEXT,
                side TEXT NOT NULL,               -- 'B' or 'S'
                qty INTEGER,
                price_est REAL,
                notional_inr REAL,                -- premium * qty (long options) - the real capital at risk
                status TEXT NOT NULL,              -- 'confirmed' | 'failed' | 'skipped_...'
                order_id TEXT,
                detail TEXT,
                raw_response TEXT
            )
            """
        )
        conn.commit()


init_db()


class AlertPayload(BaseModel):
    secret: str
    symbol: str
    action: str  # "buy" or "sell"
    qty: float
    price: float
    strategy: str | None = None


def apply_paper_trade(conn, symbol: str, action: str, qty: float, price: float):
    """Update the simulated position book. Simple average-price accounting,
    long-only close-out on sell (extend this if you need shorting)."""
    row = conn.execute(
        "SELECT * FROM positions WHERE symbol = ?", (symbol,)
    ).fetchone()
    cur_qty = row["qty"] if row else 0.0
    cur_avg = row["avg_price"] if row else 0.0

    if action == "buy":
        new_qty = cur_qty + qty
        new_avg = ((cur_qty * cur_avg) + (qty * price)) / new_qty if new_qty else 0.0
    elif action == "sell":
        new_qty = cur_qty - qty
        new_avg = cur_avg if new_qty > 0 else 0.0
    else:
        raise HTTPException(status_code=400, detail="action must be 'buy' or 'sell'")

    conn.execute(
        """
        INSERT INTO positions (symbol, qty, avg_price) VALUES (?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price
        """,
        (symbol, new_qty, new_avg),
    )


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload must be JSON")

    payload = AlertPayload(**data)

    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Bad secret")

    action = payload.action.lower().strip()
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, strategy, raw_payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                payload.symbol,
                action,
                payload.qty,
                payload.price,
                payload.strategy,
                body.decode("utf-8"),
            ),
        )
        apply_paper_trade(conn, payload.symbol, action, payload.qty, payload.price)
        conn.commit()

    return {"status": "ok", "logged": payload.dict(exclude={"secret"})}


@app.get("/positions")
def positions():
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT symbol, qty, avg_price FROM positions WHERE qty != 0"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/trades")
def trades(limit: int = 100):
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, ts, symbol, action, qty, price, strategy FROM trades "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/pnl")
def pnl():
    """Realized P&L from closed portions of trades, using FIFO-ish average-cost logic
    already applied in positions. This is a simple summary, not tax/accounting grade."""
    with closing(get_db()) as conn:
        trades_rows = conn.execute(
            "SELECT symbol, action, qty, price FROM trades ORDER BY id"
        ).fetchall()

    book: dict[str, dict] = {}
    realized = 0.0
    for t in trades_rows:
        sym = t["symbol"]
        b = book.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * t["price"])) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        elif t["action"] == "sell":
            realized += (t["price"] - b["avg"]) * min(t["qty"], b["qty"])
            b["qty"] -= t["qty"]

    return {
        "starting_cash": STARTING_CASH,
        "realized_pnl": round(realized, 2),
        "open_positions": {k: v for k, v in book.items() if abs(v["qty"]) > 1e-9},
        "note": "Unrealized P&L needs a live price feed — pull latest price per symbol "
                "and compare to avg_price from /positions to compute it.",
    }


@app.get("/history")
def history(symbol: str, period: str = "6mo", interval: str = "1d"):
    """
    Historical OHLC data for strategy research/backtesting.

    symbol   - Yahoo Finance style ticker. Examples:
                 "^NSEI"        -> NIFTY 50 index
                 "^NSEBANK"     -> BANK NIFTY index
                 "RELIANCE.NS"  -> Reliance Industries (NSE)
                 "TCS.NS"       -> TCS (NSE)
    period   - "1mo","3mo","6mo","1y","2y","5y","max"
    interval - "1d","1h","30m","15m","5m" (intraday intervals only return
                recent history - Yahoo limits how far back intraday data goes)
    """
    df = yf.download(symbol, period=period, interval=interval, progress=False)

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No data for symbol={symbol!r} period={period!r} interval={interval!r}. "
                   f"Check the symbol is a valid Yahoo Finance ticker.",
        )

    # yfinance sometimes returns MultiIndex columns like ('Close', '^NSEI')
    # even for a single symbol - flatten them.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"

    records = [
        {
            "date": row[date_col].isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        }
        for _, row in df.iterrows()
    ]

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "count": len(records),
        "data": records,
    }


# fetch_ohlc, get_fx_to_inr, _DATA_CACHE, _CACHE_TTL_SECONDS moved to
# data_fetch.py (2026-09-04 structure split, see
# docs/PROJECT_STRUCTURE_PLAN.md Phase 1) - imported at the top of this file.


def add_strategy_signal(df: pd.DataFrame, strategy: str, params: dict) -> pd.DataFrame:
    """Adds a boolean 'long' column: True = want to be long, False = want to be flat.
    Long-only, single-position. Extend here to add more strategies."""
    df = df.copy()

    if strategy == "sma_crossover":
        fast, slow = params["fast"], params["slow"]
        df["fast_ma"] = df["Close"].rolling(fast).mean()
        df["slow_ma"] = df["Close"].rolling(slow).mean()
        df["long"] = df["fast_ma"] > df["slow_ma"]

    elif strategy == "rsi_reversal":
        period = params["rsi_period"]
        oversold, overbought = params["oversold"], params["overbought"]
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))

        holding, flags = False, []
        for r in df["rsi"]:
            if pd.notna(r):
                if not holding and r < oversold:
                    holding = True
                elif holding and r > overbought:
                    holding = False
            flags.append(holding)
        df["long"] = flags

    elif strategy in ("orb_breakout", "orb_volume"):
        orb_minutes = int(params.get("orb_minutes", 15))
        sma_fast = int(params.get("sma_fast", 9))
        sma_slow = int(params.get("sma_slow", 21))
        open_min = int(params.get("open_min", 9 * 60 + 15))
        volume_mult = float(params.get("volume_mult", 1.5))
        # ma_type - added 2026-09-08, explicit user instruction: "have you
        # replaced sma with ema? ema are more reliable. do your research
        # and do the needful." This is the piece of that research that
        # was still missing: _moving_average (this file) already added
        # EMA as an opt-in for the LIVE trend-confidence/leading-target
        # gate, but orb_breakout's own entry-trigger trend filter (the
        # fast_ma > slow_ma check right below) was still hardcoded to SMA
        # regardless - meaning /backtest could never actually compare the
        # two for what matters most, the entry decision itself. Default
        # flipped SMA -> EMA everywhere (2026-09-09, explicit user
        # instruction: "stop using SMA and replace it with EMA with
        # immediate effect everywhere") - the real backtest comparison
        # (docs/STRATEGY_LOG.md) found no evidence either way on the
        # sampled symbols/window, and the user chose to switch anyway.
        # ma_type is still fully overridable per-call/per-symbol.
        ma_type = str(params.get("ma_type", "ema")).lower()

        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")
        mins = ts_ist.dt.hour * 60 + ts_ist.dt.minute

        if ma_type == "ema":
            df["fast_ma"] = df["Close"].ewm(span=sma_fast, adjust=False).mean()
            df["slow_ma"] = df["Close"].ewm(span=sma_slow, adjust=False).mean()
        else:
            df["fast_ma"] = df["Close"].rolling(sma_fast).mean()
            df["slow_ma"] = df["Close"].rolling(sma_slow).mean()
        trend_up = df["fast_ma"] > df["slow_ma"]

        in_orb_window = (mins >= open_min) & (mins < open_min + orb_minutes)
        orb_high = df["High"].where(in_orb_window).groupby(day).transform("max")
        orb_high = orb_high.groupby(day).ffill()  # holds the ORB high for the rest of that day

        after_orb = mins >= open_min + orb_minutes
        raw = (df["Close"] > orb_high) & after_orb & trend_up.fillna(False)

        if strategy == "orb_volume":
            vol_avg = df["Volume"].rolling(20).mean()
            raw = raw & (df["Volume"] > vol_avg * volume_mult)

        # docs/STRATEGY_LOG.md row #38 (VSA No Demand / No Supply Bar
        # Filter) - explicit user instruction 2026-09-08: "do the needful"
        # on the remaining catalog rows. Opt-in (vsa_filter=False by
        # default - zero change to current live behavior until a real
        # backtest earns turning it on): a "No Demand" bar is an UP bar
        # (the only kind a breakout trigger bar can be, by construction)
        # with a narrow spread AND low volume relative to recent bars -
        # the classic VSA tell that an up-move lacks real buying interest,
        # a red flag on the specific bar a breakout is triggering off of.
        # (The row's own catalog note named the OPPOSITE bar type, "No
        # Supply" - corrected here per standard VSA convention, where "No
        # Supply" reads bullish, absence of selling, and would make no
        # sense to filter OUT of a long entry.)
        vsa_filter = bool(params.get("vsa_filter", False))
        if vsa_filter:
            no_demand_spread_mult = float(params.get("no_demand_spread_mult", 0.7))
            no_demand_vol_mult = float(params.get("no_demand_vol_mult", 0.7))
            spread = df["High"] - df["Low"]
            spread_avg = spread.rolling(20).mean().shift(1)
            vol_avg_vsa = df["Volume"].rolling(20).mean().shift(1)
            no_demand = (
                (df["Close"] > df["Open"])
                & (spread < spread_avg * no_demand_spread_mult)
                & (df["Volume"] < vol_avg_vsa * no_demand_vol_mult)
            )
            raw = raw & ~no_demand.fillna(False)

        # Once triggered, stay long for the rest of that trading day (flat overnight).
        df["long"] = raw.groupby(day).cummax()

    elif strategy == "vwap_reclaim":
        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")

        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        pv = typical * df["Volume"]
        cum_pv = pv.groupby(day).cumsum()
        cum_vol = df["Volume"].groupby(day).cumsum().replace(0, float("nan"))
        vwap = cum_pv / cum_vol

        raw = df["Close"] > vwap
        df["long"] = raw.groupby(day).cummax()
        df["vwap"] = vwap

    elif strategy == "vwap_mean_reversion":
        # STRATEGY_LOG.md row #13. Session VWAP + rolling-std bands (the
        # bands are an intrabar approximation of the usual SD-of-price
        # bands, computed on the same per-day cumulative VWAP series
        # vwap_reclaim already uses). Enter long when price closes below
        # the LOWER band (oversold vs. VWAP), exit on reversion back
        # ABOVE VWAP itself (not the far band) - same "target the middle,
        # not the extreme" read the bollinger_mean_reversion research
        # above already established as the realistic-win-rate version.
        bb_std_v = float(params.get("bb_std", 2.0))
        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_pv = (typical * df["Volume"]).groupby(day).cumsum()
        cum_vol = df["Volume"].groupby(day).cumsum().replace(0, float("nan"))
        vwap = cum_pv / cum_vol
        dev = (df["Close"] - vwap).groupby(day).expanding().std().reset_index(level=0, drop=True)
        lower = vwap - bb_std_v * dev

        holding, flags = False, []
        for close, lo, vw in zip(df["Close"], lower, vwap):
            if pd.notna(lo) and pd.notna(vw):
                if not holding and close < lo:
                    holding = True
                elif holding and close > vw:
                    holding = False
            flags.append(holding)
        df["long"] = flags
        df["vwap"] = vwap

    elif strategy == "vwap_breakout_retest":
        # STRATEGY_LOG.md row #15. Break ABOVE the upper VWAP band on
        # above-average volume (the momentum signal), then wait for a
        # pullback to VWAP itself that HOLDS (low touches within
        # retest_pct% of VWAP but closes above it) before entering -
        # filters the fakeout breaks that never get a real retest hold.
        # Exit on a close back below VWAP (the level just defended).
        bb_std_v = float(params.get("bb_std", 2.0))
        retest_pct = float(params.get("retest_pct", 0.3)) / 100
        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_pv = (typical * df["Volume"]).groupby(day).cumsum()
        cum_vol = df["Volume"].groupby(day).cumsum().replace(0, float("nan"))
        vwap = cum_pv / cum_vol
        dev = (df["Close"] - vwap).groupby(day).expanding().std().reset_index(level=0, drop=True)
        upper = vwap + bb_std_v * dev
        vol_avg = df["Volume"].rolling(20).mean()
        broke_out = ((df["Close"] > upper) & (df["Volume"] > vol_avg)).groupby(day).cummax()

        holding, flags = False, []
        for close, low, vw, up_ok in zip(df["Close"], df["Low"], vwap, broke_out):
            if pd.notna(vw):
                if not holding and up_ok and close > vw and low <= vw * (1 + retest_pct):
                    holding = True
                elif holding and close < vw:
                    holding = False
            flags.append(holding)
        df["long"] = flags
        df["vwap"] = vwap

    elif strategy in ("anchored_vwap_continuation", "anchored_vwap_reversal"):
        # STRATEGY_LOG.md rows #16/#17. A REAL anchored VWAP is anchored at
        # a specific structural event (a swing low/high, a breakout
        # candle) rather than session start - approximated here as a
        # rolling anchor: the VWAP accumulated since each bar's own
        # trailing N-bar swing low (continuation) or swing high
        # (reversal), recomputed bar-by-bar (not per calendar day like
        # the session-VWAP strategies above). Documented as an
        # approximation, not a guess at the underlying math - a fixed
        # rolling lookback is the standard simplification when there's no
        # single hand-picked anchor event to backtest against.
        anchor_lookback = int(params.get("anchor_lookback", 20))
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        pv = typical * df["Volume"]
        cum_pv_all = pv.cumsum().to_numpy()
        cum_vol_all = df["Volume"].cumsum().to_numpy()
        n = len(df)
        avwap = np.full(n, np.nan)
        if strategy == "anchored_vwap_continuation":
            anchor_idx = df["Low"].rolling(anchor_lookback).apply(lambda x: x.argmin(), raw=True)
        else:
            anchor_idx = df["High"].rolling(anchor_lookback).apply(lambda x: x.argmax(), raw=True)
        for i in range(n):
            if pd.isna(anchor_idx.iloc[i]):
                continue
            a = i - (anchor_lookback - 1) + int(anchor_idx.iloc[i])
            pv_since = cum_pv_all[i] - (cum_pv_all[a - 1] if a > 0 else 0)
            vol_since = cum_vol_all[i] - (cum_vol_all[a - 1] if a > 0 else 0)
            if vol_since > 0:
                avwap[i] = pv_since / vol_since
        df["avwap"] = avwap

        if strategy == "anchored_vwap_continuation":
            # Price holds above AVWAP with higher highs/lows - approximated
            # as: closes above AVWAP AND today's high > N-bar-ago high
            # (structure still rising). Dips back to AVWAP that hold are
            # implicitly the entries (any bar satisfying the condition).
            structure_rising = df["High"] > df["High"].shift(anchor_lookback)
            df["long"] = (df["Close"] > df["avwap"]) & structure_rising.fillna(False)
        else:
            # Reversal read: repeated rejection FROM BELOW the AVWAP
            # (closes stayed under it across the lookback window), THEN a
            # reclaim (close crosses back above) is the long entry - a
            # long-only book can't short the rejection itself, only trade
            # the eventual reclaim it sets up.
            rejected_recently = (df["Close"] < df["avwap"]).rolling(anchor_lookback).sum() >= (anchor_lookback * 0.7)
            reclaim = (df["Close"] > df["avwap"]) & rejected_recently.shift(1).fillna(False)
            holding, flags = False, []
            for is_entry, close, avw in zip(reclaim, df["Close"], df["avwap"]):
                if pd.notna(avw):
                    if not holding and is_entry:
                        holding = True
                    elif holding and close < avw:
                        holding = False
                flags.append(holding)
            df["long"] = flags

    elif strategy == "vwap_multi_period_reversal":
        # STRATEGY_LOG.md row #18. Price sits on one side of session VWAP
        # for >= min_periods consecutive bars, THEN crosses to the other
        # side - the cross event itself is the trigger (not distance from
        # VWAP, which is #13's read). Long entry: was below VWAP for the
        # required run length, now closes above it.
        min_periods = int(params.get("min_periods", 5))
        ts = pd.to_datetime(df["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        day = ts_ist.dt.strftime("%Y-%m-%d")
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_pv = (typical * df["Volume"]).groupby(day).cumsum()
        cum_vol = df["Volume"].groupby(day).cumsum().replace(0, float("nan"))
        vwap = cum_pv / cum_vol
        below = df["Close"] < vwap
        was_below_run = below.shift(1).rolling(min_periods).sum() >= min_periods
        cross_up = (df["Close"] > vwap) & was_below_run.fillna(False)

        holding, flags = False, []
        for is_entry, close, vw in zip(cross_up, df["Close"], vwap):
            if pd.notna(vw):
                if not holding and is_entry:
                    holding = True
                elif holding and close < vw:
                    holding = False
            flags.append(holding)
        df["long"] = flags
        df["vwap"] = vwap

    elif strategy == "bullish_engulfing":
        # Price-action candlestick strategy. Sources (2026-09-03 research):
        # standalone bullish engulfing ~53-55% win rate; rises to ~55-65% when
        # combined with a trend/support-context filter and volume confirmation
        # (liberatedstocktrader.com, tradingrush.net backtest write-ups).
        # Enter long on a bullish engulfing candle (optionally only in an
        # uptrend per trend_sma), exit on the next bearish engulfing candle -
        # same enter/exit-loop shape as rsi_reversal above.
        trend_sma = int(params.get("trend_sma", 0))  # 0 = no trend filter
        volume_confirm = bool(params.get("volume_confirm", False))

        prev_open = df["Open"].shift(1)
        prev_close = df["Close"].shift(1)
        prev_bearish = prev_close < prev_open
        prev_bullish = prev_close > prev_open
        cur_bullish = df["Close"] > df["Open"]
        cur_bearish = df["Close"] < df["Open"]

        engulf_long = (
            cur_bullish & prev_bearish
            & (df["Open"] <= prev_close) & (df["Close"] >= prev_open)
        )
        engulf_exit = (
            cur_bearish & prev_bullish
            & (df["Open"] >= prev_close) & (df["Close"] <= prev_open)
        )

        if trend_sma > 0:
            sma = df["Close"].rolling(trend_sma).mean()
            engulf_long = engulf_long & (df["Close"] > sma)

        if volume_confirm:
            vol_avg = df["Volume"].rolling(20).mean()
            engulf_long = engulf_long & (df["Volume"] > vol_avg)

        holding, flags = False, []
        for is_entry, is_exit in zip(engulf_long, engulf_exit):
            if not holding and is_entry:
                holding = True
            elif holding and is_exit:
                holding = False
            flags.append(holding)
        df["long"] = flags

    elif strategy == "bollinger_mean_reversion":
        # Classic mean-reversion indicator strategy. Sources (2026-09-04
        # research): realistic win rates ~58-65% in non-trending regimes when
        # targeting the middle band (not the far band) as the exit, dropping
        # toward ~45% without a regime filter (crosstrade.io, quant-signals.com);
        # explicitly called out as workable on NIFTY 50 and other liquid
        # NSE large-caps on the momentumiq.in "Bollinger Walk" write-up -
        # directly relevant now that scope is NSE-only.
        # Enter long when price closes below the lower band (oversold vs.
        # its own recent range), exit when it reverts back above the middle
        # band (the rolling mean) - same enter/exit-loop shape as
        # rsi_reversal above.
        bb_period = int(params.get("bb_period", 20))
        bb_std = float(params.get("bb_std", 2.0))
        mid = df["Close"].rolling(bb_period).mean()
        std = df["Close"].rolling(bb_period).std()
        lower = mid - bb_std * std
        upper = mid + bb_std * std

        holding, flags = False, []
        for close, lo, mi in zip(df["Close"], lower, mid):
            if pd.notna(lo) and pd.notna(mi):
                if not holding and close < lo:
                    holding = True
                elif holding and close > mi:
                    holding = False
            flags.append(holding)
        df["long"] = flags
        df["bb_mid"], df["bb_upper"], df["bb_lower"] = mid, upper, lower

    elif strategy == "supertrend":
        # Trend-following indicator, extremely widely used by Indian retail/
        # algo traders on NSE specifically. Sources (2026-09-05 research):
        # ~40-55% hit ratio on 5-min NIFTY with standard params, but winners
        # run 2-3x larger than losers since you ride the trend until it
        # flips (thehonestquant.com, quantifiedstrategies.com); standard
        # settings (10, 3.0) are noted as too slow for BANKNIFTY specifically,
        # which moves 3-5x more intraday points than a typical NSE large-cap
        # (marketcalls.in) - hence sweeping atr_period/multiplier per symbol
        # rather than assuming one setting fits all NSE instruments.
        atr_period = int(params.get("atr_period", 10))
        multiplier = float(params.get("multiplier", 3.0))

        prev_close = df["Close"].shift(1)
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(atr_period).mean()

        hl2 = (df["High"] + df["Low"]) / 2
        basic_upper = (hl2 + multiplier * atr).to_numpy()
        basic_lower = (hl2 - multiplier * atr).to_numpy()
        close = df["Close"].to_numpy()
        n = len(df)

        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        in_uptrend = np.full(n, False)  # True = supertrend line is the lower band (price above it)

        first_valid = int(np.argmax(~np.isnan(basic_upper))) if np.any(~np.isnan(basic_upper)) else n
        for i in range(first_valid, n):
            if i == first_valid:
                final_upper[i] = basic_upper[i]
                final_lower[i] = basic_lower[i]
                in_uptrend[i] = True
                continue
            final_upper[i] = (
                basic_upper[i] if (basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1])
                else final_upper[i - 1]
            )
            final_lower[i] = (
                basic_lower[i] if (basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1])
                else final_lower[i - 1]
            )
            if in_uptrend[i - 1]:
                in_uptrend[i] = close[i] >= final_lower[i]
            else:
                in_uptrend[i] = close[i] > final_upper[i]

        df["long"] = in_uptrend
        df["supertrend"] = np.where(in_uptrend, final_lower, final_upper)

    elif strategy == "pin_bar_reversal":
        # Price-action candlestick strategy, combining a reversal candle
        # (hammer/pin bar) with support-zone context - both explicitly named
        # in the original research brief. Sources (2026-09-08 research): a
        # 10-year backtest on NSE Nifty 50 ranked the hammer #1 among
        # reversal patterns at ~63% win rate (dailypriceaction.com); pin bars
        # at key support/resistance levels showed a 15-20% higher success
        # rate than the pattern alone (FXOpen backtest, 2015-2020, cited via
        # colibritrader.com/innercircletrader.net) - hence requiring the low
        # to sit at/near a rolling N-bar low, not just any long lower wick.
        # Enter long on a bullish pin bar (hammer: long lower wick, small
        # body, small upper wick) whose low is near the rolling sr_lookback-bar
        # low; exit on the mirror bearish pin bar (shooting star) - same
        # enter/exit-loop shape as bullish_engulfing above.
        pin_ratio = float(params.get("pin_ratio", 2.0))
        sr_lookback = int(params.get("sr_lookback", 20))
        sr_tolerance_pct = float(params.get("sr_tolerance_pct", 0.5))

        body = (df["Close"] - df["Open"]).abs().replace(0, 1e-9)
        lower_wick = df[["Open", "Close"]].min(axis=1) - df["Low"]
        upper_wick = df["High"] - df[["Open", "Close"]].max(axis=1)
        rolling_low = df["Low"].rolling(sr_lookback).min()
        near_support = df["Low"] <= rolling_low * (1 + sr_tolerance_pct / 100)

        bullish_pin = (lower_wick >= pin_ratio * body) & (lower_wick > upper_wick) & near_support
        bearish_pin = (upper_wick >= pin_ratio * body) & (upper_wick > lower_wick)

        holding, flags = False, []
        for is_entry, is_exit in zip(bullish_pin, bearish_pin):
            if not holding and is_entry:
                holding = True
            elif holding and is_exit:
                holding = False
            flags.append(holding)
        df["long"] = flags

    elif strategy == "macd_cross":
        fast_span = int(params.get("macd_fast", 12))
        slow_span = int(params.get("macd_slow", 26))
        signal_span = int(params.get("macd_signal", 9))
        ema_fast = df["Close"].ewm(span=fast_span, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=slow_span, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal_span, adjust=False).mean()
        df["long"] = macd > signal_line

    elif strategy in ("wyckoff_spring", "wyckoff_sos"):
        # docs/STRATEGY_LOG.md rows #35 (Spring) and #37 (Sign of
        # Strength breakout) - explicit user instruction 2026-09-08: "do
        # the needful and complete this" (the Wyckoff AMD + Volume batch
        # cataloged the same day). Shared range-context precondition for
        # both: a rolling range_lookback-bar window (shifted by 1 bar to
        # avoid lookahead - only bars STRICTLY before the current one
        # define "the range") must be "flat enough" (width <=
        # range_flatness_pct of its own midpoint) - approximating the
        # schematic's PS/SC/AR/ST structure as "has genuinely been going
        # nowhere," since those individual named sub-events don't have a
        # clean OHLCV-only definition but the range itself is what
        # actually matters for a tradeable Phase-C entry.
        range_lookback = int(params.get("range_lookback", 60))
        range_flatness_pct = float(params.get("range_flatness_pct", 3.0))
        spring_pierce_pct = float(params.get("spring_pierce_pct", 0.3))
        volume_mult = float(params.get("volume_mult", 1.5))

        range_high = df["High"].rolling(range_lookback).max().shift(1)
        range_low = df["Low"].rolling(range_lookback).min().shift(1)
        range_mid = (range_high + range_low) / 2
        is_range = ((range_high - range_low) / range_mid) <= (range_flatness_pct / 100)
        vol_avg = df["Volume"].rolling(20).mean().shift(1)

        # The Spring itself (Manipulation phase): a wick pierces below the
        # range low on above-average volume, then closes back inside -
        # same wick+volume-spike+snap-back fingerprint #19 (Liquidity
        # Sweep Reversal) already uses, gated here to only fire inside a
        # genuine prior range (what makes this specifically Wyckoff's
        # Phase-C entry rather than a bare sweep).
        spring = (
            is_range
            & (df["Low"] < range_low * (1 - spring_pierce_pct / 100))
            & (df["Close"] > range_low)
            & (df["Volume"] > vol_avg * volume_mult)
        )

        if strategy == "wyckoff_spring":
            # Hold from a confirmed spring until price closes back below
            # the range low (invalidated - it was a real breakdown, not a
            # spring) - a stateful hold, same pattern rsi_reversal above
            # already uses for its own until-invalidated exit.
            long_flags, holding = [], False
            for i in range(len(df)):
                if not holding and bool(spring.iloc[i]):
                    holding = True
                elif holding and pd.notna(range_low.iloc[i]) and df["Close"].iloc[i] < range_low.iloc[i]:
                    holding = False
                long_flags.append(holding)
            df["long"] = long_flags

        else:  # wyckoff_sos
            # Track "a still-valid spring has happened in the current
            # range" the same way - valid from the spring bar until price
            # closes back below range_low (the same invalidation the
            # spring-holding loop above uses).
            valid_spring_flags, valid_spring_active = [], False
            for i in range(len(df)):
                if bool(spring.iloc[i]):
                    valid_spring_active = True
                elif valid_spring_active and pd.notna(range_low.iloc[i]) and df["Close"].iloc[i] < range_low.iloc[i]:
                    valid_spring_active = False
                valid_spring_flags.append(valid_spring_active)
            spring_seen = pd.Series(valid_spring_flags, index=df.index).shift(1).fillna(False)

            # Sign of Strength: a genuine breakout above range resistance
            # on expanding volume, ONLY after a still-valid spring earlier
            # in the same range - structurally orb_volume (see that
            # branch above) with this one precondition added, so the
            # breakout is read as "accumulation finished, markup starting"
            # rather than a bare volume-confirmed breakout with no context
            # on what came before it.
            breakout = (df["Close"] > range_high) & (df["Volume"] > vol_avg * volume_mult) & spring_seen

            ts = pd.to_datetime(df["Date"])
            ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
                "UTC"
            ).dt.tz_convert("Asia/Kolkata")
            day = ts_ist.dt.strftime("%Y-%m-%d")
            # Once triggered, stay long for the rest of that trading day -
            # same bounded-exit convention orb_breakout/orb_volume use.
            df["long"] = breakout.groupby(day).cummax()

    elif strategy == "vsa_climax_reversal":
        # docs/STRATEGY_LOG.md row #39 (VSA Stopping Volume / Climax
        # Reversal) - explicit user instruction 2026-09-08: "do the
        # needful" on the remaining catalog rows. Standalone entry (unlike
        # #38 below, which is a filter): an extended decline ends on an
        # extreme-volume, wide-spread bar whose CLOSE lands well off that
        # bar's own low - professional absorption of the crowd's
        # capitulation (Wyckoff's Selling Climax, tradeable on its own
        # without waiting for the rest of a Phase A-E range to confirm,
        # per this row's own "Notes" column).
        avg_lookback = int(params.get("avg_lookback", 20))
        decline_lookback = int(params.get("decline_lookback", 10))
        climax_volume_mult = float(params.get("climax_volume_mult", 2.0))
        climax_spread_mult = float(params.get("climax_spread_mult", 1.5))
        climax_close_pct = float(params.get("climax_close_pct", 0.5))

        spread = df["High"] - df["Low"]
        vol_avg = df["Volume"].rolling(avg_lookback).mean().shift(1)
        spread_avg = spread.rolling(avg_lookback).mean().shift(1)
        # Where the close landed within THIS bar's own range - 1.0 = closed
        # at the high, 0.0 = closed at the low. A climax bar closing in the
        # upper half (>= climax_close_pct) is the "struggle, not a clean
        # continuation down" tell that separates absorption from a genuine
        # breakdown (same distinction #22's own docstring in the log
        # draws against this row).
        close_position = (df["Close"] - df["Low"]) / spread.replace(0, float("nan"))
        prior_decline = df["Close"] < df["Close"].shift(decline_lookback)

        climax = (
            prior_decline
            & (df["Volume"] > vol_avg * climax_volume_mult)
            & (spread > spread_avg * climax_spread_mult)
            & (close_position >= climax_close_pct)
        )

        # Hold from a confirmed climax bar until price closes back below
        # that bar's own low (invalidated - the absorption failed, it was
        # a genuine breakdown after all) - same stateful-hold pattern
        # wyckoff_spring above already uses.
        long_flags, holding, climax_low = [], False, None
        for i in range(len(df)):
            if not holding and bool(climax.iloc[i]):
                holding = True
                climax_low = df["Low"].iloc[i]
            elif holding and df["Close"].iloc[i] < climax_low:
                holding = False
            long_flags.append(holding)
        df["long"] = long_flags

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy {strategy!r}. Supported: sma_crossover, rsi_reversal, "
                   f"orb_breakout, orb_volume, vwap_reclaim, vwap_mean_reversion, "
                   f"vwap_breakout_retest, anchored_vwap_continuation, anchored_vwap_reversal, "
                   f"vwap_multi_period_reversal, bullish_engulfing, pin_bar_reversal, "
                   f"bollinger_mean_reversion, supertrend, macd_cross, wyckoff_spring, wyckoff_sos, "
                   f"vsa_climax_reversal",
        )

    return df.dropna(subset=["long"]).reset_index(drop=True)


def extract_trades_fast(
    long_arr: np.ndarray, close_arr: np.ndarray, dates: np.ndarray, qty: float
) -> tuple[list[dict], dict | None]:
    """Vectorized (numpy, no Python row loop) version of trade extraction -
    entries/exits found via array shifts instead of iterating. This is the
    version used by the sweep endpoint, since it runs once per parameter
    combination and needs to stay fast even for thousands of combinations."""
    shifted = np.roll(long_arr, 1)
    shifted[0] = False
    entries = np.where(long_arr & ~shifted)[0]
    exits = np.where(~long_arr & shifted)[0]

    n_closed = min(len(entries), len(exits))
    closed_entries = entries[:n_closed]
    closed_exits = exits[:n_closed]

    entry_prices = close_arr[closed_entries]
    exit_prices = close_arr[closed_exits]
    pnls = (exit_prices - entry_prices) * qty

    trades = [
        {
            "entry_date": str(dates[e]),
            "entry_price": round(float(entry_prices[i]), 4),
            "exit_date": str(dates[x]),
            "exit_price": round(float(exit_prices[i]), 4),
            "pnl": round(float(pnls[i]), 2),
        }
        for i, (e, x) in enumerate(zip(closed_entries, closed_exits))
    ]

    open_position = None
    if len(entries) > n_closed:
        last_entry_idx = entries[n_closed]
        last_price = float(close_arr[-1])
        entry_price = float(close_arr[last_entry_idx])
        open_position = {
            "entry_date": str(dates[last_entry_idx]),
            "entry_price": entry_price,
            "current_price": last_price,
            "unrealized_pnl": round((last_price - entry_price) * qty, 2),
        }

    return trades, open_position


def extract_trades(df: pd.DataFrame, qty: float) -> tuple[list[dict], dict | None]:
    """Convenience wrapper for a single ad-hoc backtest (/backtest)."""
    long_arr = df["long"].to_numpy()
    close_arr = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].apply(lambda d: d.isoformat()).to_numpy()
    return extract_trades_fast(long_arr, close_arr, dates, qty)


@app.get("/backtest")
def backtest(
    symbol: str,
    period: str = "7d",
    interval: str = "1m",
    strategy: str = "sma_crossover",
    fast: int = 5,
    slow: int = 20,
    rsi_period: int = 14,
    oversold: float = 30,
    overbought: float = 70,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    open_min: int = 9 * 60 + 15,
    volume_mult: float = 1.5,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    trend_sma: int = 0,
    volume_confirm: bool = False,
    bb_period: int = 20,
    bb_std: float = 2.0,
    retest_pct: float = 0.3,
    anchor_lookback: int = 20,
    min_periods: int = 5,
    atr_period: int = 10,
    multiplier: float = 3.0,
    pin_ratio: float = 2.0,
    sr_lookback: int = 20,
    sr_tolerance_pct: float = 0.5,
    ma_type: str = "ema",  # 2026-09-09: SMA -> EMA everywhere, explicit user instruction
    range_lookback: int = 60,
    range_flatness_pct: float = 3.0,
    spring_pierce_pct: float = 0.3,
    vsa_filter: bool = False,
    no_demand_spread_mult: float = 0.7,
    no_demand_vol_mult: float = 0.7,
    avg_lookback: int = 20,
    decline_lookback: int = 10,
    climax_volume_mult: float = 2.0,
    climax_spread_mult: float = 1.5,
    climax_close_pct: float = 0.5,
    qty: float = 1,
):
    """
    Runs a long-only backtest server-side (real internet + pandas live here)
    and returns just the results - keeps responses small regardless of how
    many bars were analyzed.

    strategy=sma_crossover        -> params: fast, slow
    strategy=rsi_reversal         -> params: rsi_period, oversold, overbought
    strategy=orb_breakout/orb_volume -> params: orb_minutes, sma_fast, sma_slow,
                                        open_min, ma_type ("sma"/"ema" - see
                                        that branch's own comment in
                                        add_strategy_signal) (orb_volume also: volume_mult),
                                        vsa_filter (opt-in "No Demand" bar
                                        filter on the trigger bar - see
                                        STRATEGY_LOG.md #38), no_demand_spread_mult,
                                        no_demand_vol_mult
    strategy=wyckoff_spring/wyckoff_sos -> params: range_lookback, range_flatness_pct,
                                        spring_pierce_pct, volume_mult
    strategy=vsa_climax_reversal  -> params: avg_lookback, decline_lookback,
                                        climax_volume_mult, climax_spread_mult,
                                        climax_close_pct (STRATEGY_LOG.md #39)
    strategy=vwap_reclaim         -> no extra params
    strategy=vwap_mean_reversion  -> params: bb_std
    strategy=vwap_breakout_retest -> params: bb_std, retest_pct
    strategy=anchored_vwap_continuation/anchored_vwap_reversal -> params: anchor_lookback
    strategy=vwap_multi_period_reversal -> params: min_periods
    strategy=bullish_engulfing    -> params: trend_sma (0=off), volume_confirm
    strategy=bollinger_mean_reversion -> params: bb_period, bb_std
    strategy=supertrend           -> params: atr_period, multiplier
    strategy=pin_bar_reversal     -> params: pin_ratio, sr_lookback, sr_tolerance_pct
    strategy=macd_cross           -> params: macd_fast, macd_slow, macd_signal
    """
    df = fetch_ohlc(symbol, period, interval)

    if strategy == "sma_crossover":
        params = {"fast": fast, "slow": slow}
    elif strategy == "rsi_reversal":
        params = {"rsi_period": rsi_period, "oversold": oversold, "overbought": overbought}
    elif strategy in ("orb_breakout", "orb_volume"):
        params = {
            "orb_minutes": orb_minutes, "sma_fast": sma_fast, "sma_slow": sma_slow,
            "open_min": open_min, "volume_mult": volume_mult, "ma_type": ma_type,
            "vsa_filter": vsa_filter, "no_demand_spread_mult": no_demand_spread_mult,
            "no_demand_vol_mult": no_demand_vol_mult,
        }
    elif strategy in ("wyckoff_spring", "wyckoff_sos"):
        params = {
            "range_lookback": range_lookback, "range_flatness_pct": range_flatness_pct,
            "spring_pierce_pct": spring_pierce_pct, "volume_mult": volume_mult,
        }
    elif strategy == "vsa_climax_reversal":
        params = {
            "avg_lookback": avg_lookback, "decline_lookback": decline_lookback,
            "climax_volume_mult": climax_volume_mult, "climax_spread_mult": climax_spread_mult,
            "climax_close_pct": climax_close_pct,
        }
    elif strategy == "vwap_reclaim":
        params = {}
    elif strategy == "vwap_mean_reversion":
        params = {"bb_std": bb_std}
    elif strategy == "vwap_breakout_retest":
        params = {"bb_std": bb_std, "retest_pct": retest_pct}
    elif strategy in ("anchored_vwap_continuation", "anchored_vwap_reversal"):
        params = {"anchor_lookback": anchor_lookback}
    elif strategy == "vwap_multi_period_reversal":
        params = {"min_periods": min_periods}
    elif strategy == "bullish_engulfing":
        params = {"trend_sma": trend_sma, "volume_confirm": volume_confirm}
    elif strategy == "bollinger_mean_reversion":
        params = {"bb_period": bb_period, "bb_std": bb_std}
    elif strategy == "supertrend":
        params = {"atr_period": atr_period, "multiplier": multiplier}
    elif strategy == "pin_bar_reversal":
        params = {"pin_ratio": pin_ratio, "sr_lookback": sr_lookback, "sr_tolerance_pct": sr_tolerance_pct}
    elif strategy == "macd_cross":
        params = {"macd_fast": macd_fast, "macd_slow": macd_slow, "macd_signal": macd_signal}
    else:
        params = {}

    df = add_strategy_signal(df, strategy, params)
    trades, open_position = extract_trades(df, qty)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = round(sum(t["pnl"] for t in trades), 2)

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "strategy": strategy,
        "params": params,
        "bars_used": len(df),
        "num_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "total_pnl": total_pnl,
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "open_position": open_position,
        "last_10_trades": trades[-10:],
    }


MAX_SWEEP_COMBINATIONS = 3000


def _parse_num_list(raw: str, cast) -> list:
    try:
        return [cast(x.strip()) for x in raw.split(",") if x.strip() != ""]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Could not parse number list: {raw!r}")


@app.get("/sweep")
def sweep(
    symbol: str,
    period: str = "7d",
    interval: str = "1m",
    strategy: str = "sma_crossover",
    qty: float = 1,
    rank_by: str = "total_pnl",  # total_pnl | win_rate_pct | num_trades
    top_n: int = 15,
    # sma_crossover params - comma-separated lists, e.g. fast=3,5,8,10
    fast: str = "5,10,15,20",
    slow: str = "20,50,100,150",
    # rsi_reversal params - comma-separated lists
    rsi_period: str = "7,14,21",
    oversold: str = "20,25,30",
    overbought: str = "70,75,80",
    # orb_breakout / orb_volume params - comma-separated lists
    orb_minutes: str = "5,15,30",
    sma_fast: str = "5,9,20",
    sma_slow: str = "20,21,50",
    volume_mult: str = "1.2,1.5,2.0",
    # bullish_engulfing params - comma-separated lists
    trend_sma: str = "0,20,50",
    volume_confirm: str = "false,true",
    # bollinger_mean_reversion params - comma-separated lists
    bb_period: str = "10,20,30",
    bb_std: str = "1.5,2.0,2.5",
    # supertrend params - comma-separated lists
    atr_period: str = "7,10,14",
    multiplier: str = "2.0,3.0,4.0",
    # pin_bar_reversal params - comma-separated lists
    pin_ratio: str = "1.5,2.0,3.0",
    sr_lookback: str = "10,20,30",
    sr_tolerance_pct: str = "0.25,0.5,1.0",
):
    """
    Tests every combination of the given parameter lists against ONE fetch of
    the data (cached), and returns only the ranked summary - not every trade
    from every combination - so this stays fast and the response stays small
    even for thousands of combinations.

    Example (sma_crossover): fetch OHLC once, then test every (fast, slow)
    pair where fast in {5,10,15,20} and slow in {20,50,100,150} = 16 runs.
    """
    df = fetch_ohlc(symbol, period, interval)
    close_arr = df["Close"].to_numpy(dtype=float)
    dates = df["Date"].apply(lambda d: d.isoformat()).to_numpy()

    if strategy == "sma_crossover":
        fast_list = _parse_num_list(fast, int)
        slow_list = _parse_num_list(slow, int)
        combos = [
            {"fast": f, "slow": s} for f, s in product(fast_list, slow_list) if f < s
        ]
    elif strategy == "rsi_reversal":
        rp_list = _parse_num_list(rsi_period, int)
        os_list = _parse_num_list(oversold, float)
        ob_list = _parse_num_list(overbought, float)
        combos = [
            {"rsi_period": rp, "oversold": o, "overbought": b}
            for rp, o, b in product(rp_list, os_list, ob_list)
            if o < b
        ]
    elif strategy in ("orb_breakout", "orb_volume"):
        om_list = _parse_num_list(orb_minutes, int)
        sf_list = _parse_num_list(sma_fast, int)
        ss_list = _parse_num_list(sma_slow, int)
        if strategy == "orb_volume":
            vm_list = _parse_num_list(volume_mult, float)
            combos = [
                {"orb_minutes": om, "sma_fast": sf, "sma_slow": ss, "volume_mult": vm}
                for om, sf, ss, vm in product(om_list, sf_list, ss_list, vm_list)
                if sf < ss
            ]
        else:
            combos = [
                {"orb_minutes": om, "sma_fast": sf, "sma_slow": ss}
                for om, sf, ss in product(om_list, sf_list, ss_list)
                if sf < ss
            ]
    elif strategy == "bullish_engulfing":
        ts_list = _parse_num_list(trend_sma, int)
        vc_list = [v.strip().lower() == "true" for v in volume_confirm.split(",") if v.strip() != ""]
        combos = [
            {"trend_sma": ts, "volume_confirm": vc}
            for ts, vc in product(ts_list, vc_list)
        ]
    elif strategy == "bollinger_mean_reversion":
        bp_list = _parse_num_list(bb_period, int)
        bs_list = _parse_num_list(bb_std, float)
        combos = [
            {"bb_period": bp, "bb_std": bs} for bp, bs in product(bp_list, bs_list)
        ]
    elif strategy == "supertrend":
        ap_list = _parse_num_list(atr_period, int)
        mult_list = _parse_num_list(multiplier, float)
        combos = [
            {"atr_period": ap, "multiplier": m} for ap, m in product(ap_list, mult_list)
        ]
    elif strategy == "pin_bar_reversal":
        pr_list = _parse_num_list(pin_ratio, float)
        sl_list = _parse_num_list(sr_lookback, int)
        st_list = _parse_num_list(sr_tolerance_pct, float)
        combos = [
            {"pin_ratio": pr, "sr_lookback": sl, "sr_tolerance_pct": st}
            for pr, sl, st in product(pr_list, sl_list, st_list)
        ]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy {strategy!r}. Supported: sma_crossover, rsi_reversal, "
                   f"orb_breakout, orb_volume, bullish_engulfing, pin_bar_reversal, "
                   f"bollinger_mean_reversion, supertrend",
        )

    if not combos:
        raise HTTPException(status_code=400, detail="No valid parameter combinations (check your ranges).")
    if len(combos) > MAX_SWEEP_COMBINATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"{len(combos)} combinations requested, max is {MAX_SWEEP_COMBINATIONS}. "
                    f"Narrow your ranges or split into multiple sweep calls.",
        )

    results = []
    for params in combos:
        sig_df = add_strategy_signal(df, strategy, params)
        long_arr = sig_df["long"].to_numpy()
        aligned_close = sig_df["Close"].to_numpy(dtype=float)
        aligned_dates = sig_df["Date"].apply(lambda d: d.isoformat()).to_numpy()

        trades, _ = extract_trades_fast(long_arr, aligned_close, aligned_dates, qty)
        if not trades:
            continue

        wins = [t for t in trades if t["pnl"] > 0]
        total_pnl = round(sum(t["pnl"] for t in trades), 2)
        results.append({
            "params": params,
            "num_trades": len(trades),
            "win_rate_pct": round(100 * len(wins) / len(trades), 1),
            "total_pnl": total_pnl,
        })

    if rank_by not in ("total_pnl", "win_rate_pct", "num_trades"):
        raise HTTPException(status_code=400, detail="rank_by must be total_pnl, win_rate_pct, or num_trades")

    results.sort(key=lambda r: r[rank_by], reverse=True)

    all_pnls = [r["total_pnl"] for r in results]
    summary = {
        "combinations_tested": len(combos),
        "combinations_with_trades": len(results),
        "median_total_pnl": round(float(np.median(all_pnls)), 2) if all_pnls else None,
        "pct_profitable_combos": round(100 * sum(1 for p in all_pnls if p > 0) / len(all_pnls), 1) if all_pnls else None,
    }

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "strategy": strategy,
        "bars_used": len(df),
        "rank_by": rank_by,
        "summary": summary,
        "top_results": results[:top_n],
        "note": (
            "Testing many parameter combinations on ONE historical window risks "
            "overfitting - the single best combo here may just be curve-fit noise. "
            "Look at 'median_total_pnl' and 'pct_profitable_combos' too: a strategy "
            "where most nearby parameter combos are also profitable is more trustworthy "
            "than one lone spike at the top. Validate top candidates on a different "
            "date range before trusting them."
        ),
    }


# _norm_cdf, bs_price, parse_legs, run_options_backtest, _bs_delta,
# select_option_contract, _requote_contract moved to options_pricing.py
# (2026-09-04 structure split, see docs/PROJECT_STRUCTURE_PLAN.md Phase 1)
# - imported at the top of this file.


@app.get("/options-backtest")
def options_backtest_endpoint(
    symbol: str,
    legs: str,
    expiry_days: int = 15,
    iv_mode: str = "realized",
    lookback: str = "2y",
    step_days: int = 5,
    r: float = 0.0525,
):
    """
    Rolling-window historical backtest for a multi-leg options strategy, priced
    with Black-Scholes. No historical options-chain data source is wired in -
    this simulates fair-value premiums against the underlying's REAL price
    history (yfinance), it does not replay actual historical option prices.

    legs     - comma-separated TYPE:ACTION:OFFSET, e.g. "C:buy:0.0,C:sell:0.03"
               TYPE: C=call, P=put, U=underlying (long only)
               ACTION: buy | sell
               OFFSET: strike = spot_at_entry * (1 + OFFSET)
    iv_mode  - "realized" (trailing 20-day realized vol, annualized) or "flat14"
    """
    df = fetch_ohlc(symbol, lookback, "1d")
    parsed_legs = parse_legs(legs)
    result = run_options_backtest(df, parsed_legs, expiry_days, iv_mode, r, step_days)

    closes = df["Close"].to_numpy(dtype=float)
    log_ret = np.diff(np.log(closes))
    spot = float(closes[-1])
    sma20 = float(np.mean(closes[-20:]))
    sma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else None
    realized_vol_20d = float(np.std(log_ret[-20:]) * math.sqrt(252)) if len(log_ret) >= 20 else None
    trend_60d_pct = float((closes[-1] / closes[-60] - 1) * 100) if len(closes) >= 60 else None

    return {
        "symbol": symbol,
        "legs": parsed_legs,
        "params": {"expiry_days": expiry_days, "iv_mode": iv_mode, "lookback": lookback, "step_days": step_days},
        "current": {
            "spot": round(spot, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2) if sma50 else None,
            "realized_vol_20d_pct": round(realized_vol_20d * 100, 2) if realized_vol_20d else None,
            "trend_60d_pct": round(trend_60d_pct, 2) if trend_60d_pct else None,
        },
        "backtest": result["summary"],
        "sample_trades": result["trades"],
    }


IST_OFFSET_MIN = 330  # UTC+5:30, no holiday calendar
# ORB_STRATEGY_PREFIX moved to constants.py (imported at top of this file) -
# this used to be a second definition site for the same value, found during
# the 2026-09-04 structure-split verification pass.

DOCS_TRADE_OUTCOMES_PATH = os.path.join(os.path.dirname(__file__), "docs", "trade_outcomes_log.json")
# Moved up from further down in this file (2026-09-07) so today_realized_pnl
# can read it too - see that function and _durable_trade_outcomes_since for
# why: this is the durable, git-tracked closed-trade record (synced by
# journal-sync.yml) that survives a Render redeploy, unlike the live DB's
# own `trades` table (free tier, no persistent disk).


def ist_now() -> dt.datetime:
    return dt.datetime.utcnow() + dt.timedelta(minutes=IST_OFFSET_MIN)


def ist_midnight_epoch(now_ist: dt.datetime) -> float:
    midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_ist - dt.timedelta(minutes=IST_OFFSET_MIN)
    return midnight_utc.replace(tzinfo=dt.timezone.utc).timestamp()


def _durable_trade_outcomes_since(since_ts: float) -> list[dict]:
    """Closed trades from the durable, git-tracked journal
    (docs/trade_outcomes_log.json, kept current by journal-sync.yml),
    filtered to exit_time_utc >= since_ts. This is the record that
    SURVIVES a Render redeploy - the live DB's own `trades` table does
    not (free tier, no persistent disk: a redeploy starts a brand-new
    empty DB). Never raises - a missing/unreadable file just means
    nothing to merge in, not a crash."""
    try:
        with open(DOCS_TRADE_OUTCOMES_PATH) as f:
            all_trades = json.load(f)
    except Exception:
        return []
    return [t for t in all_trades if t.get("exit_time_utc", 0) >= since_ts]


def _closed_in_durable_log(symbol: str, entry_price: float, entry_ts: float) -> bool:
    """True if docs/trade_outcomes_log.json (see _durable_trade_outcomes_since
    above) already recorded THIS exact trade as closed - matched by symbol +
    entry price (small float tolerance), exit at or after this trade's own
    entry_ts. Guards reconcile_open_positions_from_journal against
    resurrecting a position from a state/open_positions.json snapshot that's
    stale (up to ~15 min behind, worse mid-day - see journal-sync.yml's own
    cadence comment) and predates a real close the scheduler already made
    and durably logged.

    BUG found live 2026-09-08 (explicit user finding, /live dashboard
    screenshot): AGL.NS and BHANDARI.NS both showed LIVE/open, 7h old - but
    docs/trade_outcomes_log.json already had a closed entry for the SAME
    symbol+entry_price (AGL via eod_squareoff, BHANDARI via stale_timeout),
    hours earlier. Every restart since then kept resurrecting the pre-close
    open_positions.json snapshot, undoing an exit that had already happened
    and was already durably recorded - same restart-race class as the
    real_positions bugs found and fixed earlier this session (see
    _sync_real_positions_external's own comment), just in the paper-side
    journal this time. Paper data doesn't need that fix's synchronous
    external mirror (no real money at stake, and the existing ~15-min git
    journal cadence is otherwise fine) - it only needed to stop undoing a
    close it had ALREADY durably recorded, which is what this check does."""
    for t in _durable_trade_outcomes_since(entry_ts):
        if t.get("symbol") != symbol:
            continue
        if abs(float(t.get("entry_price_native", 1e18)) - entry_price) < 1e-6:
            return True
    return False


def _merge_closed_trades(db_trades: list[dict], durable_trades: list[dict]) -> list[dict]:
    """Unions this DB instance's own closed-trade dicts with the durable
    journal's, deduped by (symbol, rounded exit_time_utc) - both share the
    same shape (symbol, exit_time_utc, pnl_inr, ...; see daily_summary's
    closed_trades.append() and journal-sync.yml's own jq transform, which
    copies that exact shape into the durable file). db_trades wins on a
    key collision (this instance's own fresh computation); a durable-only
    entry means that trade closed, then the DB got wiped by a redeploy,
    before this instance ever saw it.

    Found live 2026-09-07 as the root cause of three related, previously
    unexplained symptoms: today's realized P&L silently resetting toward
    zero after a mid-day redeploy, the account then blowing well past its
    intended daily-loss cap in aggregate (the halt logic re-armed with a
    full budget it hadn't earned), and the trade-view dashboard's win-rate/
    closed-trades count not matching reality. All three traced to the same
    bug: today_realized_pnl/daily_summary read ONLY the live DB's `trades`
    table, which a redeploy empties. See docs/TRADING_CONSTRAINTS.md."""
    merged: dict[tuple, dict] = {}
    for t in durable_trades:
        merged[(t.get("symbol"), round(t.get("exit_time_utc", 0)))] = t
    for t in db_trades:
        merged[(t.get("symbol"), round(t.get("exit_time_utc", 0)))] = t
    return list(merged.values())


# India's New Tax Regime slabs, FY2025-26/AY2026-27 (confirmed via web
# search 2026-09-07 - PIB's own Budget 2025 press release, corroborated by
# ClearTax/Bajaj/IndiaFirst Life; this is the DEFAULT regime since Budget
# 2023). (upper bound INR, marginal rate on the band up to that bound):
INDIA_NEW_REGIME_SLABS_INR = [
    (400_000, 0.0), (800_000, 0.05), (1_200_000, 0.10), (1_600_000, 0.15),
    (2_000_000, 0.20), (2_400_000, 0.25), (float("inf"), 0.30),
]
# Section 87A rebate (new regime): total taxable income up to this amount
# owes ZERO NET TAX - not just the 0% slab up to Rs 4L, a full rebate on
# whatever the slab table would otherwise compute. Marginal relief right
# at this edge (a narrow band just above Rs 12L can still owe less than
# the naive slab sum) is NOT implemented here - flagged as a
# simplification, not silently smoothed over.
INDIA_87A_REBATE_THRESHOLD_INR = 1_200_000


def estimate_speculative_income_tax_inr(profit_inr: float) -> float:
    """Automatic tax estimate on a speculative-business-income profit
    figure (2026-09-07, explicit user instruction: "not an input like 30%
    or something" - no manual rate; "fetch api data from kotak and
    understand it to reach to actual tax" - compute it for real). Applies
    India's actual New Regime progressive slabs (INDIA_NEW_REGIME_SLABS_INR)
    plus the Section 87A full rebate below Rs 12L.

    SIMPLIFICATION, stated plainly rather than hidden: Indian slabs are
    progressive across TOTAL annual income from every source (salary,
    other business income, etc.) - this project has no way to know that
    and has no manual input for it either now, so it treats the given
    profit_inr AS IF it were the sole/total annual income for the
    marginal-rate lookup. That's the best fully-automatic estimate
    possible without asking for income data; a real filing depends on
    the full picture, and this stays a planning estimate, not tax advice.

    Zero on a loss or zero profit - a speculative LOSS is never a
    negative tax, it only carries forward against future speculative
    gains (see today_realized_pnl's own docstring)."""
    if profit_inr <= 0:
        return 0.0
    if profit_inr <= INDIA_87A_REBATE_THRESHOLD_INR:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in INDIA_NEW_REGIME_SLABS_INR:
        if profit_inr <= lower:
            break
        tax += (min(profit_inr, upper) - lower) * rate
        lower = upper
    return round(tax, 2)


def today_realized_pnl(conn, since_ts: float) -> float:
    """Realized P&L today across all auto-signal ('orb-*') trades, all symbols -
    this is the shared capital/risk pool the daily loss cap applies to.

    Builds the cost-basis book from the FULL trade history (not just today's
    rows) so a position opened before today's cutoff still has a correct avg
    price - needed for any market whose session can span the IST midnight
    boundary (e.g. US markets, ~19:00-01:30 IST), where the entry and exit
    would otherwise land in different day-buckets and this would wrongly
    treat the exit as a sell with no matching buy. Only sells at/after
    `since_ts` count toward the returned figure.

    2026-09-07: merges in the durable journal (see
    _durable_trade_outcomes_since/_merge_closed_trades) so a same-day
    redeploy can no longer silently erase realized losses/gains from this
    figure - the daily-loss-cap halt this feeds must stay correct across
    a redeploy, not just within one DB instance's lifetime.

    Also 2026-09-07: since_ts is bumped forward to the PAPER-only manual
    reset point (runtime_settings key daily_loss_reset_epoch) if one was
    set later than the normal IST-midnight cutoff - see that key's own
    entry in RUNTIME_SETTINGS_META for the full reasoning (a "resume
    trading" button next to the paper daily loss budget on trade-view).

    2026-09-07 (second pass), explicit user instruction: "all data
    remains in sync with kotak transaction details... unless i do
    non-real money transaction." When real trading is active, NSE-equity
    paper trades are EXCLUDED here and replaced by get_real_pnl_today_inr
    (Kotak's own ground truth) instead - real trading only ever mirrors
    NSE equity paper entries (stage 3 scope, see kotak_real_orders.py),
    so those two figures represent the SAME underlying activity and must
    not be double-counted. Paper trades on anything real trading doesn't
    touch at all (MCX/options/indices - anything not ending '.NS') still
    count via the paper book below - that IS the "non-real money
    transaction" carve-out the instruction named: genuine paper-only
    activity legitimately diverges and still needs its own risk
    tracking, since nothing real is watching it. Falls back to paper-only
    NSE-equity accounting (never silently drops it) if Kotak's real P&L
    can't be fetched right now - this shared figure also drives paper-
    only instruments that have nothing to do with a Kotak API hiccup."""
    since_ts = max(since_ts, get_runtime_setting(conn, "daily_loss_reset_epoch"))
    real_trading_active = is_real_trading_enabled(conn)

    def _real_covered(symbol: str) -> bool:
        return real_trading_active and symbol.endswith(".NS")

    all_trades = conn.execute(
        "SELECT symbol, action, qty, price, fx_to_inr, ts FROM trades WHERE strategy LIKE ? ORDER BY id",
        (ORB_STRATEGY_PREFIX + "%",),
    ).fetchall()
    book: dict[str, dict] = {}
    db_closed = []
    for t in all_trades:
        # Normalize to INR/unit at the row's own fx rate so symbols in
        # different currencies (NSE in INR, US/crypto in USD) can be summed
        # together correctly - mixing raw $ and Rs numbers would silently
        # misstate P&L by the exchange rate (~83-88x for USD).
        price_inr = t["price"] * t["fx_to_inr"]
        b = book.setdefault(t["symbol"], {"qty": 0.0, "avg": 0.0})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * price_inr)) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
        else:
            pnl = (price_inr - b["avg"]) * min(t["qty"], b["qty"])
            b["qty"] -= t["qty"]
            if t["ts"] >= since_ts and not _real_covered(t["symbol"]):
                db_closed.append({"symbol": t["symbol"], "exit_time_utc": t["ts"], "pnl_inr": pnl})
    durable = [d for d in _durable_trade_outcomes_since(since_ts) if not _real_covered(d.get("symbol", ""))]
    merged = _merge_closed_trades(db_closed, durable)
    paper_total = sum(t.get("pnl_inr", 0.0) for t in merged)

    if not real_trading_active:
        return paper_total
    real_pnl = get_real_pnl_today_inr(since_ts=since_ts)
    if real_pnl is None:
        return paper_total  # Kotak unreachable right now - never pretend zero real loss
    return paper_total + real_pnl


def deployed_notional(conn) -> float:
    """Capital currently tied up in open auto-signal positions, across all
    symbols - capital is shared and finite (only Rs 2L total), so this caps
    how much a new entry can size into regardless of that trade's own risk
    budget. Without this, two symbols breaking out in the same poll cycle
    could each size a full position independently and jointly overspend the
    account. entry_price is native currency; fx_to_inr (captured at entry)
    converts it to INR so USD positions (SPY etc.) don't get sized as if
    $1 == Rs 1."""
    rows = conn.execute(
        "SELECT qty, entry_price, fx_to_inr FROM signal_state WHERE status = 'long'"
    ).fetchall()
    equity_notional = sum(r["qty"] * r["entry_price"] * r["fx_to_inr"] for r in rows)
    opt_rows = conn.execute(
        "SELECT contracts, entry_premium, fx_to_inr FROM option_state"
    ).fetchall()
    # Same shared pool as equities (docs/TRADING_CONSTRAINTS.md) - an open
    # option position's cost basis (premium paid, its real max loss on a
    # total wipeout) counts against the same capital cap so options and
    # equities can't jointly overspend the account.
    option_notional = sum(r["contracts"] * 100 * r["entry_premium"] * r["fx_to_inr"] for r in opt_rows)
    return equity_notional + option_notional


# ---------------------------------------------------------------------------
# Options overlay: buy real, currently-quoted calls/puts on symbols with a
# live yfinance options chain (SPY/QQQ/AAPL - see OPTIONS_ELIGIBLE_SYMBOLS).
# NSE/BSE index and stock options are explicitly NOT covered here - there is
# no real chain/IV data for them without a broker connection (Kotak Neo,
# not yet wired up - docs/TRADING_CONSTRAINTS.md); synthesizing one would be
# exactly the kind of fabricated-data shortcut this project has repeatedly
# ruled out. The equity engine above (_auto_signal_core) stays long-only and
# untouched by any of this - direction detection here is a read-only mirror
# of its own bullish logic (plus the bearish case it deliberately doesn't
# trade), used only to decide "buy a call" vs "buy a put".
# 2026-09-03: expanded from just SPY/QQQ/AAPL per explicit user instruction
# ("don't skip stocks with options available") - every name here is a
# heavily-optioned, deeply liquid US mega-cap/ETF, so chain availability
# isn't in question. Each must also be a WATCHLIST entry (session hours/
# currency/risk_pct come from there) - see the WATCHLIST comment above this
# set for why it's a curated list, not literally every optionable US stock.
# Raw yfinance tickers aren't how anyone actually refers to the NSE
# indices ("^NSEI" means nothing at a glance - it's NIFTY 50) - this is
# purely a display label, never used for any fetch/lookup, so a symbol
# missing here just falls back to showing its raw ticker.
SYMBOL_DISPLAY_NAMES = {
    "^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY", "^BSESN": "SENSEX",
    "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "CRUDE OIL",
}


def _display_name(symbol: str) -> str:
    return SYMBOL_DISPLAY_NAMES.get(symbol, symbol)


# OPTIONS_ELIGIBLE_SYMBOLS and the rest of the OPTIONS_* constants moved to
# constants.py; _bs_delta, select_option_contract, _requote_contract moved
# to options_pricing.py (2026-09-04 structure split, see
# docs/PROJECT_STRUCTURE_PLAN.md Phase 1) - all imported at the top of this
# file. (OPTIONS_ELIGIBLE_SYMBOLS itself is still emptied for the same
# 2026-09-03 NSE-only-rescope reason as before - see constants.py's own
# comment on it.)


TREND_WEAKENED_MIN_CONFIDENCE = 0.95  # explicit user instruction 2026-09-03:
# the early "trend weakened" exit must only fire on a statistically real
# reversal, not a marginal single-bar SMA crossover - if confidence falls
# short, the trade stays open (stop/target/eod-squareoff still apply).

ENTRY_BREAKOUT_MARGIN_PCT = 0.1  # explicit user instruction 2026-09-04
# ("make stronger trade entries... more transaction means more taxes"):
# orb_breakout now requires the close to clear the opening-range high by
# at least this % (not just touch/tick above it), on top of also requiring
# TREND_WEAKENED_MIN_CONFIDENCE-level trend confidence (see _auto_signal_
# core's entry check) - together these filter out the marginal setups
# that were closing for a few rupees of P&L (real 2026-09-04 closed
# trades: rr_achieved 0.05 and 0.38, far short of the 3.0 target).

VOLUME_CONFIRM_LOOKBACK = 20  # bars, same window bullish_engulfing's own
# (pre-existing, opt-in) volume_confirm already used - now MANDATORY for
# every strategy and every symbol, explicit user instruction 2026-09-08:
# "volume is must have trigger constraint while deciding the trade entry
# for all trades... without volume it will be difficult to [judge] the
# directional movement of the stocks" (+ a same-day follow-up: "Price
# action are not coming into picture for all ur trades. Very less
# movement can be seen in ur selected trades. So high volume trades
# should be chosen"). Was previously read but only ACTED on for
# bullish_engulfing, and only when a symbol's own WATCHLIST entry opted
# in (volume_confirm=True) - most symbols never set it, so orb_breakout
# (the default strategy almost every symbol actually runs) was never
# volume-gated at all. Now applied unconditionally to BOTH strategies
# (see _volume_confirms's call sites in _auto_signal_core) - the
# `volume_confirm` parameter/WATCHLIST field is kept for backward API
# compatibility but no longer toggles anything on/off; the check always
# runs as one more required confluence flag alongside breakout/trend/
# confidence (explicit user instruction, same day: "keep a combo of
# three four green flags before the trade entry").


def _volume_confirms(vol_series: np.ndarray) -> tuple[bool, float | None]:
    """True if the CURRENT bar's volume exceeds the average of the
    VOLUME_CONFIRM_LOOKBACK bars immediately before it (current bar
    excluded from its own average) - real participation behind this
    move, not a low-volume drift that's easy to reverse and gives no
    real evidence of directional conviction. Returns
    (confirmed, avg_volume); avg_volume is None (and confirmed is always
    False) when there isn't enough prior history yet - a missing or
    zero average is never treated as a pass, same fail-closed discipline
    as every other real gate in this engine."""
    if len(vol_series) < VOLUME_CONFIRM_LOOKBACK + 1:
        return False, None
    cur_vol = float(vol_series[-1])
    avg_vol = float(np.mean(vol_series[-(VOLUME_CONFIRM_LOOKBACK + 1):-1]))
    if avg_vol <= 0:
        return False, avg_vol
    return cur_vol > avg_vol, avg_vol


def _moving_average(closes: np.ndarray, period: int, ma_type: str = "ema") -> float:
    """The fast/slow trend average this engine's whole entry/exit gate is
    built on - SMA (flat rolling mean, the default, UNCHANGED live
    behavior) or EMA (exponentially-weighted, opt-in via ma_type="ema").

    Added 2026-09-08, explicit user instruction: "Check whether people
    are using SMA or only EMA in place of SMA. There is a need for u to
    rethink on the prioritisation." Verified via web search rather than
    assumed: 9/21 EMA (the SAME periods sma_fast/sma_slow already default
    to here) is the most-used intraday crossover combination among day
    traders specifically because EMA reacts faster to recent price than
    SMA - the whole point of a 5-min-bar intraday engine trying to catch
    a move early, not lagging it. Real evidence favoring a switch, but
    switching the trend read that gates EVERY entry/exit on a live-money
    system is a real behavioral change that deserves a backtest
    comparison first (the existing sweep tooling already supports
    comparing configurations) - so this defaults to "sma" (zero change
    to current live behavior) and is opt-in per-symbol via WATCHLIST's
    ma_type field, not flipped globally by this change alone.

    EMA computed via the standard recursive formula (alpha = 2/(period+1),
    seeded from the window's own first value) over the same trailing
    `period`-bar window SMA already uses - not pandas' own .ewm() (which
    would need the FULL closes history for its own warm-up, not just this
    window) so behavior is directly comparable at the same window size."""
    window = closes[-period:]
    if ma_type == "ema":
        alpha = 2.0 / (period + 1)
        ema = float(window[0])
        for c in window[1:]:
            ema = alpha * float(c) + (1 - alpha) * ema
        return ema
    return float(np.mean(window))


def _trend_confidence(closes: np.ndarray, sma_fast: int, sma_slow: int, ma_type: str = "ema") -> float:
    """One-tailed statistical confidence, via the normal CDF, that the
    sma_fast/sma_slow gap's sign is a real move and not just noise around a
    flat/random-walk price - the same normal-distribution machinery
    _bs_delta already uses (_norm_cdf) applied to trend strength instead of
    option delta, not a fudged threshold.

    Treats each SMA as an independent sample mean of the closes in its own
    window, so the standard error of their gap is
    sigma_price * sqrt(1/sma_fast + 1/sma_slow), where sigma_price is the
    recent per-bar price volatility (std of returns * price level). The
    gap's z-score against that standard error, run through the normal CDF,
    is the confidence that a gap this size wouldn't show up by chance.
    Returns 0.0 (never confident) when there isn't enough same-day history
    yet to estimate volatility - direction alone is not evidence."""
    n = len(closes)
    if n < sma_slow + 2:
        return 0.0
    sma_f = _moving_average(closes, sma_fast, ma_type)
    sma_s = _moving_average(closes, sma_slow, ma_type)
    spread = sma_f - sma_s
    window = closes[-(sma_slow + 1):]
    rets = np.diff(window) / window[:-1]
    sigma_ret = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    if not np.isfinite(sigma_ret) or sigma_ret <= 0:
        return 0.0
    sigma_price = sigma_ret * sma_s
    se = sigma_price * math.sqrt(1.0 / sma_fast + 1.0 / sma_slow)
    if not np.isfinite(se) or se <= 0:
        return 0.0
    z = abs(spread) / se
    return _norm_cdf(z)


def _compute_trend(symbol: str, sma_fast: int, sma_slow: int, tz_offset_min: int,
                    interval: str = "5m", ma_type: str = "ema"):
    """Same sma_fast/sma_slow trend read _auto_signal_core computes at
    every check (not just at entry) - factored out so the options overlay's
    open-position management can check it too. Reuses fetch_ohlc's own
    180s cache, so calling this for a symbol already checked elsewhere this
    tick is normally a cache hit, not a fresh network call. Returns
    (direction, confidence): direction is 'up'/'down'/None (None = not
    enough candles yet), confidence is _trend_confidence's 0..1 read on
    that direction (0.0 alongside a direction just means "not enough same-
    day history to size it yet" - the caller decides what bar to hold it
    to, e.g. TREND_WEAKENED_MIN_CONFIDENCE for the early-exit check).

    2026-09-09: closes now comes from the full multi-day `df`, not
    today_df - same fix and same reasoning as _auto_signal_core's own
    closes (see its comment there for the full root cause: a today-only
    window made sma_f/sma_s/confidence mathematically unable to exist for
    the first 1-4+ hours of every session).

    2026-09-09 (explicit user instruction: "stop using SMA and replace it
    with EMA with immediate effect everywhere"): this function never
    actually had ma_type support before - it hardcoded plain np.mean
    (SMA) regardless of what the rest of the engine was doing, the one
    place in this whole trend-read family that was inconsistent even
    before today's switch. Now uses the same _moving_average/
    _trend_confidence machinery every other trend read uses, defaulting
    to "ema" like the rest."""
    try:
        df = fetch_ohlc(symbol, "5d", interval)
        closes = df["Close"].to_numpy(dtype=float)
    except Exception:
        return None, 0.0
    if len(closes) < max(sma_fast, sma_slow):
        return None, 0.0
    sma_f = _moving_average(closes, sma_fast, ma_type)
    sma_s = _moving_average(closes, sma_slow, ma_type)
    direction = "up" if sma_f > sma_s else "down"
    return direction, _trend_confidence(closes, sma_fast, sma_slow, ma_type)


TRAIL_ACTIVATE_R = 0.5          # don't trail at all below 0.5R unrealized gain - backtested
# 2026-09-03 (.github/workflows/trailing-stop-threshold-backtest.yml) against
# 380 real orb_breakout entries (12 NSE symbols, ~59 days of 5-min data):
# 0.5R beat 1.0R/1.5R/2.0R/no-trailing on every metric (win rate, total R,
# profit factor) - see docs/TRADING_CONSTRAINTS.md "Trailing stop loss"
# for the full comparison table and the bigger caveat it also surfaced.
TRAIL_BREAKEVEN_BUFFER_PCT = 0.1  # breakeven-lock sits slightly above entry, not exactly on it
TRAIL_CHANDELIER_K = 3.0        # standard Chandelier Exit multiplier (Chuck LeBeau's own default)
TRAIL_ATR_PERIOD = 14           # standard ATR lookback


def _trailing_stop_target(df: pd.DataFrame, today_df: pd.DataFrame, entry_price: float,
                           initial_stop: float, entry_ts: float, tz_offset_min: int) -> float | None:
    """Long-only trailing-stop candidate for THIS tick (see docs/TRADING_CONSTRAINTS.md
    "Trailing stop loss" for the full rationale). Two stages, gated on R =
    entry_price - initial_stop (the trade's OWN original risk, frozen at
    entry - see signal_state.initial_stop_loss - so this doesn't move the
    goalposts as the stop itself trails):

      1. Below TRAIL_ACTIVATE_R * R of unrealized gain: not activated yet -
         returns None, caller keeps the existing stop untouched.
      2. At/above that: locks to breakeven (+ a small buffer to cover
         round-trip cost) at minimum, then ratchets further via a
         Chandelier Exit - highest close since THIS trade's own entry,
         minus TRAIL_CHANDELIER_K * ATR(TRAIL_ATR_PERIOD) - as price
         extends. ATR is read off `df` (the multi-day history already
         fetched this tick), not `today_df` alone, so there's enough bars
         for a real ATR reading even early in today's own session.

    Returns the candidate stop (native currency), or None if not yet
    activated. The caller takes max(current_stop, candidate) - this
    function only ever proposes moving the stop UP; it never proposes
    loosening it, and never proposes anything before activation."""
    r = entry_price - initial_stop
    if r <= 0:
        return None
    last_close = float(today_df["Close"].iloc[-1])
    if (last_close - entry_price) < TRAIL_ACTIVATE_R * r:
        return None

    breakeven_stop = entry_price * (1 + TRAIL_BREAKEVEN_BUFFER_PCT / 100)

    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    if len(close) < TRAIL_ATR_PERIOD + 1:
        return breakeven_stop  # not enough bars for a real ATR yet - breakeven lock still applies

    prev_close = close[:-1]
    true_range = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )
    atr = float(np.mean(true_range[-TRAIL_ATR_PERIOD:]))

    # Highest close since THIS trade's own entry - same-day only (this
    # engine is intraday, squared off every day, so entry never crosses a
    # session boundary). Mirrors the mins-since-local-midnight comparison
    # _auto_signal_core already uses for mins_now/today_df["mins"].
    entry_local = dt.datetime.utcfromtimestamp(entry_ts) + dt.timedelta(minutes=tz_offset_min)
    entry_mins = entry_local.hour * 60 + entry_local.minute
    since_entry = today_df[today_df["mins"] >= entry_mins]
    highest_close = float(since_entry["Close"].max()) if not since_entry.empty else last_close

    chandelier_stop = highest_close - TRAIL_CHANDELIER_K * atr
    return max(breakeven_stop, chandelier_stop)


LEADING_TARGET_MIN_CONFIDENCE = TREND_WEAKENED_MIN_CONFIDENCE  # explicit
# user instruction 2026-09-08: "keep updating the target higher and
# higher if the confidence is high and signal is strong" - reuses the
# SAME statistical bar (95%, via _trend_confidence) new entries and the
# trend-weakened exit already trust for "strong," rather than inventing
# a separate number here.


def _leading_target_extend(current_target: float, entry_price: float, initial_stop: float,
                            rr: float, last_close: float, trend: str | None,
                            closes: np.ndarray, sma_fast: int, sma_slow: int,
                            ma_type: str = "ema") -> float | None:
    """Long-only LEADING (trailing-UP) target candidate - the mirror
    image of _trailing_stop_target for the other side of the trade.
    Explicit user instruction 2026-09-08: "updating the leading target
    so that all trades are between range of trailing SL and leading
    target."

    Only ever proposes moving the target UP (never down), and only once
    price has actually REACHED the current target AND the trend is still
    genuinely strong (trend == 'up' at >= LEADING_TARGET_MIN_CONFIDENCE -
    the same bar this engine already requires to open a trade in the
    first place, not a separately-invented "strong" threshold). Extension
    step is one more R-multiple of the trade's OWN original risk
    (entry_price - initial_stop) - a trade originally aimed at 3R that
    keeps re-qualifying steps up to 6R, then 9R, and so on, for as long
    as the signal keeps re-confirming itself at each step, instead of
    being forced to book profit the instant the first target is touched
    while the move is still clearly working.

    Returns the candidate target (native currency), or None if price
    hasn't reached the current target, the trend has flipped, or
    confidence has fallen below the bar - the caller then falls through
    to the normal target_hit exit, so a trade that stops re-qualifying
    still books its (already-extended) profit rather than riding on with
    no upper bound at all."""
    if last_close < current_target:
        return None
    r = entry_price - initial_stop
    if r <= 0 or trend != "up":
        return None
    if _trend_confidence(closes, sma_fast, sma_slow, ma_type) < LEADING_TARGET_MIN_CONFIDENCE:
        return None
    return current_target + rr * r


# ---- Capital reallocation: exit part of a weaker live position to fund a
# stronger new signal, when the capital pool is genuinely full (2026-09-03,
# explicit user instruction - see docs/TRADING_CONSTRAINTS.md "Capital
# reallocation" for the full rationale and the guardrails these constants
# encode). This is the "cross-symbol best-signal-wins" fast-follow the
# capital-sizing block's own comment already flagged as a future step -
# NOT a license to chase every shinier signal: the trailing-stop backtest
# already showed cutting a position early, on its own, tends to destroy
# value here - so this only ever fires when there's a genuine capital
# shortage (not routinely), only trims the SINGLE weakest eligible
# position, never below breakeven, and is capped per day.
REALLOCATION_MIN_CONFIDENCE_GAP = 0.20  # new candidate's trend confidence must
# exceed an existing position's by at least this much - not "any edge",
# a clear, auditable gap (using the same 0-1 _trend_confidence scale the
# 95%-confidence trend_weakened exit already uses).
REALLOCATION_MAX_PER_DAY = 2  # hard ceiling - bounds how much churn this can
# ever introduce even if the capital pool is repeatedly maxed out; a
# smaller number than "as many as qualify" on purpose.


def _count_reallocations_today(conn, since_ts: float) -> int:
    rows = conn.execute(
        "SELECT raw_payload FROM trades WHERE action = 'sell' AND ts >= ? AND strategy LIKE ?",
        (since_ts, ORB_STRATEGY_PREFIX + "%"),
    ).fetchall()
    count = 0
    for r in rows:
        try:
            if json.loads(r["raw_payload"]).get("exit_reason") == "partial_exit_reallocated":
                count += 1
        except Exception:
            continue
    return count


def _find_reallocation_source(conn, new_symbol: str, new_confidence: float, needed_capital_inr: float):
    """Looks across every OTHER open equity position for one weak enough,
    and safe enough, to partially exit in favor of `new_symbol`'s stronger
    signal. Eligibility (ALL must hold, not just the confidence gap):
      - still trending the direction that justified holding ("up" - a
        position already trending down would exit via trend_weakened on
        its own shortly anyway, no special handling needed here).
      - unrealized P&L >= 0 - NEVER realize a loss just to chase a new
        opportunity; only ever trims something already at or above
        breakeven.
      - its own current trend confidence trails new_confidence by at least
        REALLOCATION_MIN_CONFIDENCE_GAP.
    Among eligible positions, picks the one with the LOWEST confidence
    (the weakest link) - if it's still not enough capital on its own, that
    single position is trimmed as far as it can go and nothing else is
    touched (bounded blast radius, one position at a time, never a cascade
    across several to fund one new entry).
    Returns None if nothing eligible, else a dict describing the trim."""
    watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in WATCHLIST}
    open_state = conn.execute(
        "SELECT * FROM signal_state WHERE status = 'long' AND symbol != ?", (new_symbol,)
    ).fetchall()

    best = None
    for row in open_state:
        sym = row["symbol"]
        cfg = watchlist_by_symbol.get(sym)
        if not cfg:
            continue  # no live params to evaluate against (e.g. a recovered/delisted symbol) - skip, don't guess
        try:
            last_close = float(fetch_ohlc(sym, "1d", cfg.get("interval", "5m"))["Close"].iloc[-1])
        except Exception:
            continue
        unrealized_inr = (last_close - row["entry_price"]) * row["qty"] * row["fx_to_inr"]
        if unrealized_inr < 0:
            continue
        direction, confidence = _compute_trend(
            sym, cfg["sma_fast"], cfg["sma_slow"], cfg["tz_offset_min"], cfg.get("interval", "5m")
        )
        if direction != "up":
            continue
        if (new_confidence - confidence) < REALLOCATION_MIN_CONFIDENCE_GAP:
            continue
        if best is None or confidence < best["confidence"]:
            best = {
                "symbol": sym, "confidence": confidence, "last_close": last_close,
                "entry_price": row["entry_price"], "fx_to_inr": row["fx_to_inr"], "qty": row["qty"],
            }

    if best is None:
        return None

    # Sized off entry_price (not current price) - deployed_notional() itself
    # measures deployed capital that way, so freeing capital "as
    # deployed_notional sees it" needs the same basis or the caller's
    # post-trim capital math would be wrong.
    entry_notional_per_unit = best["entry_price"] * best["fx_to_inr"]
    qty_to_sell = min(best["qty"], needed_capital_inr / entry_notional_per_unit) if entry_notional_per_unit > 0 else 0.0
    qty_to_sell = round(qty_to_sell, 6)
    if qty_to_sell <= 0:
        return None
    best["qty_to_sell"] = qty_to_sell
    return best


def _execute_partial_exit(conn, symbol: str, qty_to_sell: float, last_close: float, freed_for_symbol: str, new_confidence: float):
    """Sells qty_to_sell out of an open position that _find_reallocation_source
    already vetted, WITHOUT closing the rest of it - the remaining qty keeps
    running under its existing stop/target/trailing-stop exactly as before,
    just smaller. Logged with its own exit_reason so it's fully visible
    (not folded into an ordinary stop/target exit) in the trade log and
    durable trade history."""
    row = conn.execute("SELECT * FROM signal_state WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        return 0.0
    entry_fx = row["fx_to_inr"]
    pnl_native = (last_close - row["entry_price"]) * qty_to_sell
    pnl_inr = pnl_native * entry_fx
    remaining_qty = round(row["qty"] - qty_to_sell, 6)

    # Best-effort real strategy tag for the record (same book-lookup the
    # closed-trades/open-positions endpoints already use) - falls back to a
    # clearly-labeled placeholder rather than guessing.
    buy_row = conn.execute(
        "SELECT strategy FROM trades WHERE symbol = ? AND action = 'buy' ORDER BY id DESC LIMIT 1", (symbol,)
    ).fetchone()
    strategy_tag = buy_row["strategy"] if buy_row else f"{ORB_STRATEGY_PREFIX}unknown"

    payload = {
        "symbol": symbol, "action": "sell", "qty": qty_to_sell, "price": last_close,
        "fx_to_inr": entry_fx, "strategy": strategy_tag, "exit_reason": "partial_exit_reallocated",
        "entry_price": row["entry_price"], "remaining_qty": remaining_qty,
        "freed_capital_for_symbol": freed_for_symbol, "new_candidate_confidence": round(new_confidence, 4),
        "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
    }
    apply_paper_trade(conn, symbol, "sell", qty_to_sell, last_close)
    conn.execute(
        "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
        "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
        (time.time(), symbol, qty_to_sell, last_close, entry_fx, strategy_tag, json.dumps(payload)),
    )
    if remaining_qty <= 1e-9:
        conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
    else:
        conn.execute("UPDATE signal_state SET qty = ? WHERE symbol = ?", (remaining_qty, symbol))
    conn.commit()
    return pnl_inr


def _detect_direction_signal(symbol: str, orb_minutes: int, sma_fast: int, sma_slow: int,
                              trend_sma: int, tz_offset_min: int, open_min: int, interval: str = "5m"):
    """Direction-only signal (bullish/bearish/None) for the options overlay.
    Mirrors _auto_signal_core's own orb_breakout-with-trend and
    bullish_engulfing entry logic, PLUS their bearish mirrors (orb breakdown,
    bearish engulfing) that the equity engine deliberately never trades (it
    stays long-only). This function trades nothing itself and never opens an
    equity position - it only tells the options layer below which direction,
    if any, the same evidence-backed patterns are currently pointing."""
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)
    today_str = now_local.strftime("%Y-%m-%d")
    try:
        df = fetch_ohlc(symbol, "5d", interval)
        ts = pd.to_datetime(df["Date"])
        ts_utc = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
        ts_local = ts_utc + pd.Timedelta(minutes=tz_offset_min)
        df = df.assign(ts_local=ts_local)
        df["date_local"] = df["ts_local"].dt.strftime("%Y-%m-%d")
        today_df = df[df["date_local"] == today_str].reset_index(drop=True)
    except Exception as e:
        return None, f"data_error: {e}", None
    if today_df.empty or len(df) < 2:
        return None, "no_data_yet", None
    today_df = today_df.copy()
    today_df["mins"] = today_df["ts_local"].dt.hour * 60 + today_df["ts_local"].dt.minute

    last_close = float(today_df.iloc[-1]["Close"])
    closes = today_df["Close"].to_numpy(dtype=float)
    sma_f = float(np.mean(closes[-sma_fast:])) if len(closes) >= sma_fast else None
    sma_s = float(np.mean(closes[-sma_slow:])) if len(closes) >= sma_slow else None
    trend = ("up" if sma_f > sma_s else "down") if (sma_f is not None and sma_s is not None) else None

    orb_cutoff = open_min + orb_minutes
    orb_df = today_df[today_df["mins"] < orb_cutoff]
    if not orb_df.empty and today_df["mins"].max() >= orb_cutoff:
        orb_high, orb_low = float(orb_df["High"].max()), float(orb_df["Low"].min())
        if last_close > orb_high and trend == "up":
            return "bullish", "orb_breakout_with_trend", last_close
        if last_close < orb_low and trend == "down":
            return "bearish", "orb_breakdown_with_trend", last_close

    cur_bar, prev_bar = df.iloc[-1], df.iloc[-2]
    cur_bullish, cur_bearish = cur_bar["Close"] > cur_bar["Open"], cur_bar["Close"] < cur_bar["Open"]
    prev_bearish, prev_bullish = prev_bar["Close"] < prev_bar["Open"], prev_bar["Close"] > prev_bar["Open"]
    trend_ok_up = trend_ok_down = True
    if trend_sma > 0:
        full_closes = df["Close"].to_numpy(dtype=float)
        if len(full_closes) < trend_sma:
            trend_ok_up = trend_ok_down = False
        else:
            sma_ref = float(np.mean(full_closes[-trend_sma:]))
            trend_ok_up, trend_ok_down = last_close > sma_ref, last_close < sma_ref

    if (cur_bullish and prev_bearish and cur_bar["Open"] <= prev_bar["Close"]
            and cur_bar["Close"] >= prev_bar["Open"] and trend_ok_up):
        return "bullish", "bullish_engulfing", last_close
    if (cur_bearish and prev_bullish and cur_bar["Open"] >= prev_bar["Close"]
            and cur_bar["Close"] <= prev_bar["Open"] and trend_ok_down):
        return "bearish", "bearish_engulfing", last_close

    return None, "no_signal", last_close


def _options_signal_core(
    underlying: str, capital: float = 400000, daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0, rr: float = 3.0, option_stop_pct: float = OPTIONS_STOP_PCT,
    orb_minutes: int = 15, sma_fast: int = 9, sma_slow: int = 21, trend_sma: int = 20,
    interval: str = "5m", tz_offset_min: int = IST_OFFSET_MIN, open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30, squareoff_min: int = 15 * 60 + 20, trade_weekends: bool = False,
    currency: str = "USD",
):
    """Options equivalent of _auto_signal_core: same shared capital pool,
    daily-loss cap, RR-minimum and EOD-squareoff discipline
    (docs/TRADING_CONSTRAINTS.md), applied to a real call/put contract
    instead of the underlying. `underlying` must be in OPTIONS_ELIGIBLE_SYMBOLS.
    Position is tracked in option_state, keyed by "{underlying}:OPT-{RIGHT}"
    so it can never collide with that same symbol's own equity position in
    signal_state, and its buy/sell legs are logged into the SAME `trades`
    table (qty = contracts*100, price = premium/share) so today's realized
    P&L and the daily loss cap automatically include it alongside equities -
    one account, one shared risk budget, regardless of instrument."""
    if underlying not in OPTIONS_ELIGIBLE_SYMBOLS:
        return {"underlying": underlying, "status": "not_options_eligible"}

    now_ist = ist_now()
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)
    today_str = now_local.strftime("%Y-%m-%d")
    mins_now = now_local.hour * 60 + now_local.minute

    if not trade_weekends and now_local.weekday() >= 5:
        return {"underlying": underlying, "status": "closed_weekend", "time_local": str(now_local)}
    if mins_now < open_min:
        return {"underlying": underlying, "status": "pre_open", "time_local": str(now_local)}
    is_squareoff_time = mins_now >= squareoff_min
    if mins_now > close_min:
        return {"underlying": underlying, "status": "closed", "time_local": str(now_local)}

    with closing(get_db()) as conn:
        since_ts = ist_midnight_epoch(now_ist)
        realized_today = today_realized_pnl(conn, since_ts)
        daily_loss_cap = capital * daily_risk_pct / 100
        remaining_budget = max(0.0, daily_loss_cap - max(0.0, -realized_today))
        halted = remaining_budget <= 0

        try:
            fx_to_inr = get_fx_to_inr(currency)
        except HTTPException as e:
            return {"underlying": underlying, "status": "fx_error", "detail": e.detail}

        result = {
            "underlying": underlying, "status": "checked", "time_local": str(now_local),
            "realized_today": round(realized_today, 2), "budget_remaining": round(remaining_budget, 2),
            "halted_for_day": halted, "action_taken": "none",
        }

        # ---- manage any open option position on this underlying (either right) ----
        for right in ("call", "put"):
            opt_symbol = f"{underlying}:OPT-{right.upper()}"
            row = conn.execute("SELECT * FROM option_state WHERE opt_symbol = ?", (opt_symbol,)).fetchone()
            if not row:
                continue

            premium = _requote_contract(underlying, row["expiry"], row["strike"], right)
            exit_reason = None
            dte_left = (dt.datetime.strptime(row["expiry"], "%Y-%m-%d") - dt.datetime.utcnow()).days
            if halted:
                exit_reason = "daily_loss_cap_hit"
            elif dte_left <= 0:
                exit_reason = "expiry_reached"
            elif is_squareoff_time:
                exit_reason = "eod_squareoff"
            elif premium is not None and premium >= row["target_premium"]:
                exit_reason = "target_hit"
            elif premium is not None and premium <= row["stop_premium"]:
                exit_reason = "stop_hit"
            else:
                # Same "is the trend that justified this trade still
                # intact?" check the equity engine runs on every open
                # position (docs/TRADING_CONSTRAINTS.md) - a call is a
                # bullish bet (exit if the underlying's trend flips down),
                # a put is a bearish bet (exit if it flips up). Only acted
                # on at TREND_WEAKENED_MIN_CONFIDENCE (95%) or better - a
                # marginal single-bar crossover is noise, not evidence the
                # setup broke, and must never close the trade. Standing
                # policy per explicit user instruction 2026-09-03.
                trend_now, trend_conf = _compute_trend(underlying, sma_fast, sma_slow, tz_offset_min, interval)
                trend_confident = trend_conf >= TREND_WEAKENED_MIN_CONFIDENCE
                if right == "call" and trend_now == "down" and trend_confident:
                    exit_reason = "trend_weakened"
                elif right == "put" and trend_now == "up" and trend_confident:
                    exit_reason = "trend_weakened"

            if exit_reason:
                # A stale/failed requote must never block a forced exit
                # (daily halt, EOD, expiry) - fall back to entry premium
                # (0 P&L) rather than leaving a position open past the risk
                # framework's own hard deadlines.
                exit_premium = premium if premium is not None else row["entry_premium"]
                contracts = row["contracts"]
                qty = contracts * 100
                entry_fx = row["fx_to_inr"]
                pnl_native = (exit_premium - row["entry_premium"]) * qty
                pnl_inr = pnl_native * entry_fx
                risk_per_contract = row["entry_premium"] - row["stop_premium"]
                rr_achieved = round((exit_premium - row["entry_premium"]) / risk_per_contract, 2) if risk_per_contract else None
                payload = {
                    "symbol": opt_symbol, "underlying": underlying, "right": right, "action": "sell",
                    "qty": qty, "contracts": contracts, "price": exit_premium, "currency": currency,
                    "fx_to_inr": entry_fx, "strategy": OPTIONS_STRATEGY_TAG, "exit_reason": exit_reason,
                    "entry_price": row["entry_premium"], "stop_loss": row["stop_premium"],
                    "target": row["target_premium"], "rr_target": rr, "rr_achieved": rr_achieved,
                    "strike": row["strike"], "expiry": row["expiry"],
                    "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
                    "pnl_pct_of_capital": round(100 * pnl_inr / capital, 3),
                }
                apply_paper_trade(conn, opt_symbol, "sell", qty, exit_premium)
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
                    (time.time(), opt_symbol, qty, exit_premium, entry_fx, OPTIONS_STRATEGY_TAG, json.dumps(payload)),
                )
                conn.execute("DELETE FROM option_state WHERE opt_symbol = ?", (opt_symbol,))
                conn.commit()
                result.update(action_taken=f"exited_{right}_{exit_reason}", exit_pnl_inr=payload["pnl_inr"], rr_achieved=rr_achieved)
                return result

            result["open_position"] = dict(row)
            return result

        # ---- look for a new entry ----
        if halted:
            result["action_taken"] = "blocked_daily_loss_cap"
            return result
        if not is_trading_enabled(conn):
            result["action_taken"] = "trading_paused"
            return result
        if is_squareoff_time:
            result["action_taken"] = "no_new_entries_market_closing"
            return result

        direction, reason, spot = _detect_direction_signal(
            underlying, orb_minutes, sma_fast, sma_slow, trend_sma, tz_offset_min, open_min, interval,
        )
        result["direction_signal"] = direction
        result["direction_reason"] = reason
        result["spot"] = spot
        if not direction or spot is None:
            result["action_taken"] = "no_signal"
            return result

        right = "call" if direction == "bullish" else "put"
        contract, err = select_option_contract(underlying, spot, right)
        if contract is None:
            result["action_taken"] = "no_qualifying_contract"
            result["reason"] = err
            return result

        entry_premium = contract["premium"]
        stop_premium = round(entry_premium * (1 - option_stop_pct / 100), 4)
        target_premium = round(entry_premium * (1 + rr * option_stop_pct / 100), 4)
        risk_per_contract_native = entry_premium - stop_premium
        risk_per_contract_inr = risk_per_contract_native * 100 * fx_to_inr
        if risk_per_contract_inr <= 0:
            result["action_taken"] = "invalid_stop_skipped"
            return result

        available_capital_inr = max(0.0, capital - deployed_notional(conn))
        max_single_trade_inr = capital / CAPITAL_TRANCHES
        usable_capital_inr = min(available_capital_inr, max_single_trade_inr)

        # Per-trade risk is risk_per_trade_pct% of the capital actually
        # INVESTED IN THIS TRADE (usable_capital_inr), not of the whole
        # account - same explicit standing policy as the equity engine
        # (see _auto_signal_core). Sizing no longer shrinks as the day's
        # running P&L worsens (explicit user instruction 2026-09-03 -
        # "I want net loss to be 2% for all trades for the day, not that
        # loss budget") - remaining_budget stays a separate, independently-
        # enforced HALT: once net loss for the day reaches daily_risk_pct%,
        # `halted` blocks every new entry outright (see above), rather than
        # this sizing math quietly shrinking trades as that threshold gets
        # closer. Every entry sizes at its own full risk_per_trade_pct
        # until the moment trading actually halts.
        risk_amount_inr = usable_capital_inr * risk_per_trade_pct / 100
        contracts = math.floor(risk_amount_inr / risk_per_contract_inr)
        # 1 contract (100 shares) is the smallest tradeable unit - real
        # option premiums often make even 1 contract's risk-at-stop exceed
        # this one trade's risk_per_trade_pct target (unlike equities, which
        # can size down to a fraction of a share). Rather than silently
        # zeroing out a real, qualified signal the same way the pre-fix
        # integer-floored equity qty did, take the smallest unit whenever
        # its own risk still fits the FULL remaining daily-loss budget - the
        # same "one trade can use the whole day's budget" ceiling
        # docs/TRADING_CONSTRAINTS.md already applies to equities when
        # risk_per_trade_pct == daily_risk_pct, just made explicit here for
        # the contract-quantization case.
        if contracts < 1 and risk_per_contract_inr <= remaining_budget:
            contracts = 1

        notional_per_contract_inr = entry_premium * 100 * fx_to_inr
        if notional_per_contract_inr > 0:
            contracts = min(contracts, math.floor(usable_capital_inr / notional_per_contract_inr))

        if contracts < 1:
            result["action_taken"] = (
                "insufficient_capital" if available_capital_inr < notional_per_contract_inr
                else "budget_too_small_for_1_contract"
            )
            result["available_capital_inr"] = round(available_capital_inr, 2)
            result["contract_considered"] = contract
            return result

        opt_symbol = f"{underlying}:OPT-{right.upper()}"
        qty = contracts * 100
        notional_inr = round(qty * entry_premium * fx_to_inr, 2)
        payload = {
            "symbol": opt_symbol, "underlying": underlying, "right": right, "action": "buy",
            "qty": qty, "contracts": contracts, "price": entry_premium, "currency": currency,
            "fx_to_inr": fx_to_inr, "strategy": OPTIONS_STRATEGY_TAG, "entry_reason": reason,
            "strike": contract["strike"], "expiry": contract["expiry"], "dte": contract["dte"],
            "iv": contract["iv"], "atm_iv": contract["atm_iv"], "delta": contract["delta"],
            "stop_loss": stop_premium, "target": target_premium, "rr_target": rr,
            "risk_amount_inr": round(risk_amount_inr, 2), "notional_inr": notional_inr,
        }
        apply_paper_trade(conn, opt_symbol, "buy", qty, entry_premium)
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
            (time.time(), opt_symbol, qty, entry_premium, fx_to_inr, OPTIONS_STRATEGY_TAG, json.dumps(payload)),
        )
        conn.execute(
            "INSERT INTO option_state "
            "(opt_symbol, underlying, day, right, expiry, strike, contracts, entry_premium, "
            "stop_premium, target_premium, entry_iv, entry_delta, entry_ts, fx_to_inr) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(opt_symbol) DO UPDATE SET day=excluded.day, expiry=excluded.expiry, "
            "strike=excluded.strike, contracts=excluded.contracts, entry_premium=excluded.entry_premium, "
            "stop_premium=excluded.stop_premium, target_premium=excluded.target_premium, "
            "entry_iv=excluded.entry_iv, entry_delta=excluded.entry_delta, entry_ts=excluded.entry_ts, "
            "fx_to_inr=excluded.fx_to_inr",
            (opt_symbol, underlying, today_str, right, contract["expiry"], contract["strike"], contracts,
             entry_premium, stop_premium, target_premium, contract["iv"], contract["delta"], time.time(), fx_to_inr),
        )
        conn.commit()
        result.update(action_taken=f"entered_{right}", entry=payload)
        return result


@app.get("/options-signal")
def options_signal(
    underlying: str, capital: float = 400000, daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0, rr: float = 3.0, option_stop_pct: float = OPTIONS_STOP_PCT,
    orb_minutes: int = 15, sma_fast: int = 9, sma_slow: int = 21, trend_sma: int = 20,
    interval: str = "5m", tz_offset_min: int = -240, open_min: int = 570,
    close_min: int = 960, squareoff_min: int = 950, trade_weekends: bool = False, currency: str = "USD",
):
    """HTTP wrapper around _options_signal_core - see that function's and the
    options-overlay module docstring above for the actual rules. Defaults
    match the US-market session (SPY/QQQ/AAPL, the only options-eligible
    symbols today - OPTIONS_ELIGIBLE_SYMBOLS)."""
    return _options_signal_core(
        underlying=underlying, capital=capital, daily_risk_pct=daily_risk_pct,
        risk_per_trade_pct=risk_per_trade_pct, rr=rr, option_stop_pct=option_stop_pct,
        orb_minutes=orb_minutes, sma_fast=sma_fast, sma_slow=sma_slow, trend_sma=trend_sma,
        interval=interval, tz_offset_min=tz_offset_min, open_min=open_min, close_min=close_min,
        squareoff_min=squareoff_min, trade_weekends=trade_weekends, currency=currency,
    )


VOL_CONTRACTION_RATIO = 0.5  # today's ORB range < this * recent-days' average = contraction signal


def _orb_range_contraction_signal(df: pd.DataFrame, today_str: str, open_min: int, orb_minutes: int,
                                   today_orb_range: float) -> bool | None:
    """True if today's opening-range (High-Low over the first orb_minutes
    after open_min) is unusually narrow vs the same window on recent
    prior days already present in `df` (the same 5d fetch _auto_signal_core
    itself made - no extra network cost) - a volatility-contraction/squeeze
    proxy for the Long Straddle's entry signal (docs/STRATEGY_LOG.md row
    #3, added 2026-09-07, NOT YET BACKTESTED - see that row's own note).
    None when there isn't enough prior-day data in the window to compare
    against (never invents a signal from too little data) or the day's
    own range is invalid."""
    if today_orb_range is None or today_orb_range <= 0:
        return None
    prior_days = sorted(d for d in df["date_local"].unique() if d != today_str)
    if len(prior_days) < 2:
        return None
    prior_ranges = []
    for d in prior_days:
        day_df = df[df["date_local"] == d]
        mins = day_df["ts_local"].dt.hour * 60 + day_df["ts_local"].dt.minute
        orb_df = day_df[mins < open_min + orb_minutes]
        if orb_df.empty:
            continue
        prior_ranges.append(float(orb_df["High"].max()) - float(orb_df["Low"].min()))
    if len(prior_ranges) < 2:
        return None
    avg_prior_range = sum(prior_ranges) / len(prior_ranges)
    if avg_prior_range <= 0:
        return None
    return today_orb_range < VOL_CONTRACTION_RATIO * avg_prior_range


def _auto_signal_core(
    symbol: str,
    capital: float = 400000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 3.0,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    interval: str = "5m",
    tz_offset_min: int = IST_OFFSET_MIN,
    open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30,
    squareoff_min: int = 15 * 60 + 20,
    trade_weekends: bool = False,
    currency: str = "INR",
    strategy: str = "orb_breakout",
    trend_sma: int = 0,
    volume_confirm: bool = False,
    min_entry_confidence_pct: float = TREND_WEAKENED_MIN_CONFIDENCE * 100,
    max_hold_minutes: float = 120.0,
    ma_type: str = "ema",  # 2026-09-09: SMA -> EMA everywhere, explicit user instruction
):
    """
    Plain function version of the /auto-signal logic - callable directly
    (no HTTP round-trip) by both the /auto-signal endpoint below and the
    in-process background scheduler (see WATCHLIST/_scheduler_loop), so
    there is exactly one implementation of the actual trading rules.

    Intraday opening-range-breakout (ORB) signal engine, long-only, paper trades
    only. Designed to be called repeatedly (e.g. every 5 min during market
    hours via a GitHub Actions cron) - all state (open position, today's
    realized P&L) is persisted in SQLite so it survives Render restarts/sleeps
    between calls. `interval` sets the candle size this all runs on (1m, 2m,
    5m, 15m, 30m, 60m/1h - anything yfinance supports intraday); orb_minutes,
    sma_fast/slow are all in that candle's own units (minutes / bar-count).
    Note: polling faster than `interval` gains nothing - a new candle only
    closes every `interval`. This is same-day only (ORB needs an intraday
    opening range); a multi-day/swing engine on daily+ candles is a separate,
    not-yet-built strategy shape.

    Market session is fully configurable, so this same engine covers any
    market/asset class, not just NSE - tz_offset_min/open_min/close_min/
    squareoff_min are all minutes-since-local-midnight in that market's own
    timezone (defaults = NSE/BSE, IST 9:15-15:30). For a 24/7 market (e.g.
    crypto), pass open_min=0, close_min=1439, squareoff_min=1439,
    trade_weekends=true. NOTE: the shared Rs-capital daily-loss cap and
    capital-deployed cap (see deployed_notional/today_realized_pnl) always
    reset at IST midnight regardless of this market's own session, since
    that's the single account's "day" - a position whose session spans IST
    midnight (e.g. US markets, ~19:00-01:30 IST) is handled correctly for
    P&L (see today_realized_pnl's docstring) but still counts against
    *today's* (IST) budget at exit even if it opened "yesterday" IST.

    Rules (all tweakable via query params):
      - Opening range = high/low of the first `orb_minutes` after the market
        opens (open_min, in its own local time).
      - Entry: candle closes ENTRY_BREAKOUT_MARGIN_PCT% above the opening
        range high (not just any tick above it) AND SMA(fast) > SMA(slow)
        with at least TREND_WEAKENED_MIN_CONFIDENCE trend confidence (not
        just any positive gap) - both tightened 2026-09-04, explicit user
        instruction, to cut down on marginal-edge entries. Long only - no
        shorting in this book.
      - Stop-loss: the strategy's own technical level (opening-range low),
        capped at stop_pct% max below entry - whichever is tighter, so max
        loss per trade is bounded at stop_pct% of that trade's value even if
        the ORB range is wider. Target: entry + rr * (entry - stop).
      - Position size: risk_amount / (entry - stop), where risk_amount =
        min(risk_per_trade_pct% of capital, remaining daily loss budget) -
        i.e. how much capital gets deployed into the trade is set so a
        stop_pct% move costs at most risk_per_trade_pct% of capital.
      - Daily loss cap: daily_risk_pct% of capital. Once today's realized loss
        (across all symbols AND all markets - the capital is one shared pool)
        hits this, no new entries and any open position is squared off
        immediately. With risk_per_trade_pct == daily_risk_pct (both 2% by
        default), one stopped-out trade can use the whole day's budget - by
        design, per the user's stated risk rule.
      - End-of-day square-off at squareoff_min regardless of stop/target.

    `currency` is the symbol's OWN quote currency ("INR" for NSE/BSE, "USD"
    for US stocks/ETFs and crypto). All price levels fetched from yfinance
    (close, orb_high/low, stop, target) stay in that native currency - they
    have to, since that's what the live quote is in. Only capital sizing,
    the daily-loss/capital caps, and reported P&L are converted to INR
    (via a live USD/INR rate, fetched the same cached way as price data),
    because capital and the caps are one shared Rs 2L pool across every
    market. Getting this wrong (treating $1 == Rs 1) would size USD
    positions ~83-88x too large in real terms.

    `strategy` selects the ENTRY trigger only ("orb_breakout" - the above -
    or "bullish_engulfing", a candlestick-pattern entry backtested
    2026-09-03, docs/strategy_log.xlsx). Stop-loss/target/EOD-squareoff/
    daily-loss-cap risk management is identical either way - deliberately
    NOT the open-ended "hold until opposite signal" exit the backtest used,
    so every live strategy stays on the same bounded-risk framework
    (docs/TRADING_CONSTRAINTS.md), not whatever exit its own backtest
    happened to use.
    """
    if strategy == "orb_breakout":
        strategy_tag = f"{ORB_STRATEGY_PREFIX}{orb_minutes}m-sma{sma_fast}-{sma_slow}"
    elif strategy == "bullish_engulfing":
        strategy_tag = f"{ORB_STRATEGY_PREFIX}bullish-engulfing-trend{trend_sma}"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown live strategy {strategy!r}")
    now_ist = ist_now()
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_min)
    today_str = now_local.strftime("%Y-%m-%d")
    mins_now = now_local.hour * 60 + now_local.minute

    if not trade_weekends and now_local.weekday() >= 5:
        return {"symbol": symbol, "status": "closed_weekend", "time_local": str(now_local)}
    if mins_now < open_min:
        return {"symbol": symbol, "status": "pre_open", "time_local": str(now_local)}

    is_squareoff_time = mins_now >= squareoff_min
    is_market_open = mins_now <= close_min
    if not is_market_open:
        return {"symbol": symbol, "status": "closed", "time_local": str(now_local)}

    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM signal_state WHERE symbol = ?", (symbol,)).fetchone()
        if row and row["day"] != today_str:
            conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
            conn.commit()
            row = None

        # Shared account budget always resets on the IST calendar day,
        # regardless of which market/timezone this call is for.
        since_ts = ist_midnight_epoch(now_ist)
        realized_today = today_realized_pnl(conn, since_ts)
        daily_loss_cap = capital * daily_risk_pct / 100
        loss_so_far = max(0.0, -realized_today)
        remaining_budget = max(0.0, daily_loss_cap - loss_so_far)
        halted = remaining_budget <= 0

        try:
            fx_to_inr = get_fx_to_inr(currency)
        except HTTPException as e:
            return {"symbol": symbol, "status": "fx_error", "detail": e.detail}

        try:
            df = fetch_ohlc(symbol, "5d", interval)
            ts = pd.to_datetime(df["Date"])
            ts_utc = ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
            ts_local = ts_utc + pd.Timedelta(minutes=tz_offset_min)
            df = df.assign(ts_local=ts_local)
            df["date_local"] = df["ts_local"].dt.strftime("%Y-%m-%d")
            today_df = df[df["date_local"] == today_str].reset_index(drop=True)
        except Exception as e:
            return {"symbol": symbol, "status": "data_error", "detail": str(e)}

        if today_df.empty:
            return {"symbol": symbol, "status": "no_intraday_data_yet", "time_local": str(now_local)}

        today_df["mins"] = today_df["ts_local"].dt.hour * 60 + today_df["ts_local"].dt.minute

        vol_contraction_signal = None
        if strategy == "orb_breakout":
            orb_cutoff = open_min + orb_minutes
            orb_df = today_df[today_df["mins"] < orb_cutoff]
            if orb_df.empty or today_df["mins"].max() < orb_cutoff:
                return {
                    "symbol": symbol, "status": "waiting_for_opening_range",
                    "bars_so_far": len(today_df), "time_local": str(now_local),
                }
            orb_high = float(orb_df["High"].max())
            orb_low = float(orb_df["Low"].min())
            # Volatility-contraction signal (2026-09-07, explicit user
            # instruction: "there are strategies where put and call are
            # together less than half of total cost too" -> Long Straddle,
            # docs/STRATEGY_LOG.md row #3, "Expect big move, direction
            # unknown (vol expansion)"). Computed here from `df` this call
            # already fetched (no extra network cost) purely so
            # _straddle_signal_core has it without re-fetching OHLC itself.
            # NOT YET BACKTESTED - see STRATEGY_LOG's own caution; a simple,
            # documented proxy (today's opening range unusually narrow vs
            # the same window on recent prior days already in this 5d
            # dataset), not a claim of evidenced edge.
            vol_contraction_signal = _orb_range_contraction_signal(
                df, today_str, open_min, orb_minutes, orb_high - orb_low,
            )
        else:
            # bullish_engulfing needs no opening range - just enough candles
            # (across days, same as its backtest) to compare two consecutive
            # bars. orb_high/orb_low stay unset here; filled from the
            # pattern candle itself below if/when it fires, purely so
            # signal_state's existing columns have a meaningful "structural
            # reference level" regardless of which strategy is live.
            if len(df) < 2:
                return {
                    "symbol": symbol, "status": "waiting_for_pattern_data",
                    "bars_so_far": len(today_df), "time_local": str(now_local),
                }
            orb_high = orb_low = None

        last = today_df.iloc[-1]
        last_close = float(last["Close"])

        # Multi-day closes (df, not today_df) for the trend/SMA/confidence
        # read - 2026-09-09, explicit user finding: "why don't you detect
        # any signal in first one hour of market open while most traders
        # do that early trade." Root cause: this used to be today_df-only,
        # so sma_f needed sma_fast bars INTO TODAY before it existed at
        # all (45 min for the default sma_fast=9 on 5m bars), sma_s needed
        # sma_slow bars (105 min for sma_slow=21, up to 250 min/~4h10m for
        # the sma_slow=50 symbols), and _trend_confidence needed
        # sma_slow+2 bars before it could return anything above 0.0 (its
        # own "not enough same-day history yet" floor) - a mathematical
        # impossibility for the first 1-4+ hours of every session,
        # regardless of how strong the actual move was. _volume_confirms
        # right below already reads df (not today_df) for exactly this
        # reason; this brings the trend read into line with that same,
        # already-established precedent instead of being the one
        # inconsistent piece. Standard practice on any real chart too - a
        # 9/21 EMA/SMA on an intraday chart is continuous across session
        # boundaries, not reset to zero every morning. orb_high/orb_low/
        # last_close (the actual ORB definition and breakout trigger)
        # remain strictly today-only, unchanged - only the TREND context
        # now has enough history to be computable right at the open.
        closes = df["Close"].to_numpy(dtype=float)
        sma_f = _moving_average(closes, sma_fast, ma_type) if len(closes) >= sma_fast else None
        sma_s = _moving_average(closes, sma_slow, ma_type) if len(closes) >= sma_slow else None
        trend = ("up" if sma_f > sma_s else "down") if (sma_f is not None and sma_s is not None) else None

        result = {
            "symbol": symbol, "status": "checked", "time_local": str(now_local),
            "currency": currency, "fx_to_inr": round(fx_to_inr, 4),
            "last_close": last_close, "orb_high": orb_high, "orb_low": orb_low,
            "sma_fast": sma_f, "sma_slow": sma_s, "trend": trend,
            "capital": capital, "daily_loss_cap": daily_loss_cap,
            "realized_today": round(realized_today, 2),
            "realized_today_pct": round(100 * realized_today / capital, 3),
            "budget_remaining": round(remaining_budget, 2),
            "halted_for_day": halted, "action_taken": "none",
            "is_squareoff_time": is_squareoff_time, "vol_contraction_signal": vol_contraction_signal,
        }

        # ---- manage an existing open position ----
        if row and row["status"] == "long":
            # Trailing stop - ratchet stop_loss up (NEVER down) before any
            # exit check below runs, so stop_hit already sees today's trail.
            # initial_stop_loss is the frozen entry-time stop (R yardstick);
            # falls back to the live stop_loss for a pre-migration row that
            # predates the column (see signal_state's own comment).
            current_stop = row["stop_loss"]
            trail_candidate = _trailing_stop_target(
                df, today_df, row["entry_price"], row["initial_stop_loss"] or row["stop_loss"],
                row["entry_ts"], tz_offset_min,
            )
            if trail_candidate is not None and trail_candidate > current_stop:
                current_stop = trail_candidate
                conn.execute("UPDATE signal_state SET stop_loss = ? WHERE symbol = ?", (current_stop, symbol))
                # Without this, the ratchet was computed correctly every tick
                # (visible in /scheduler-attempts' own per-tick result) but
                # silently discarded - sqlite3 connections don't autocommit,
                # and this position-management branch's only OTHER commit()
                # sits inside `if exit_reason:` below, which a still-open
                # position never reaches. The connection closing at the end
                # of `with closing(get_db())` rolled the UPDATE back before
                # /daily-summary's own fresh SELECT ever saw it - confirmed
                # 2026-09-03 from the live GC=F/SI=F positions: their
                # scheduler-attempts-computed stop had clearly ratcheted
                # (e.g. SI=F 65.79 -> 66.52) while daily-summary's (and so
                # trade-view's) stop_loss_native was stuck at the original.
                conn.commit()

            # Leading (trailing-UP) target - explicit user instruction
            # 2026-09-08: "keep updating the target higher and higher if
            # the confidence is high and signal is strong... so that all
            # trades are between range of trailing SL and leading
            # target." Mirrors the trailing-stop ratchet above: checked
            # (and possibly extended) BEFORE the exit_reason chain below,
            # so a just-extended target is already what target_hit
            # compares against this same tick - see
            # _leading_target_extend's own docstring for the full logic.
            current_target = row["target"]
            if last_close >= current_target:
                extended_target = _leading_target_extend(
                    current_target, row["entry_price"], row["initial_stop_loss"] or row["stop_loss"],
                    rr, last_close, trend, closes, sma_fast, sma_slow, ma_type,
                )
                if extended_target is not None:
                    current_target = extended_target
                    conn.execute("UPDATE signal_state SET target = ? WHERE symbol = ?", (current_target, symbol))
                    conn.commit()

            exit_reason = None
            if halted:
                exit_reason = "daily_loss_cap_hit"
            elif last_close >= current_target:
                exit_reason = "target_hit"
            elif last_close <= current_stop:
                exit_reason = "stop_hit"
            elif trend == "down" and _trend_confidence(closes, sma_fast, sma_slow, ma_type) >= TREND_WEAKENED_MIN_CONFIDENCE:
                # The position is long because trend was "up" at entry
                # (orb_breakout requires it directly; bullish_engulfing's
                # own trend_sma filter serves the same purpose) - if the
                # short-term trend (same sma_fast/sma_slow this function
                # already recomputes every check) has since flipped
                # against the trade, that's real evidence the setup that
                # justified holding is gone, not just the market's normal
                # noise around a fixed stop/target. Exit now instead of
                # riding it all the way down to stop_loss on a trade whose
                # own premise has already broken - standing policy per
                # explicit user instruction 2026-09-03 (docs/TRADING_CONSTRAINTS.md).
                #
                # Gated at TREND_WEAKENED_MIN_CONFIDENCE (95%, via
                # _trend_confidence's normal-CDF read on the SMA gap vs
                # recent volatility) per explicit user instruction
                # 2026-09-03: a marginal single-bar crossover is noise, not
                # evidence the setup broke, and must NOT close the trade -
                # it just rides on to its existing stop/target/eod-squareoff.
                exit_reason = "trend_weakened"
            elif (
                (time.time() - row["entry_ts"]) >= max_hold_minutes * 60
                and current_stop <= (row["initial_stop_loss"] or row["stop_loss"])
            ):
                # Time-based stale-position exit - explicit user
                # instruction 2026-09-08: "If a target is not hit and
                # neither the stop loss is hit means that stock moves in
                # sideways... capital has limitation and it should be
                # used for better profit opportunities rather than being
                # stuck in a sideways moving equity stock." Only reached
                # if NONE of the above already exited this tick (target/
                # stop/trend-weakened all take priority, same as before).
                #
                # The second condition is the important refinement, found
                # via a local integration test before this ever went
                # live: "neither hit" taken literally would also catch a
                # trade whose LEADING TARGET keeps extending (real,
                # ongoing momentum, the opposite of sideways) just
                # because it hasn't technically touched its
                # ever-receding target. current_stop <= initial_stop
                # means the trailing stop has NEVER activated (see
                # TRAIL_ACTIVATE_R, 0.5R) - i.e. this trade has not even
                # earned half an R of favorable movement in its entire
                # life, which is the actual, unambiguous definition of
                # "stuck sideways" this instruction describes. A trade
                # that's moved enough to activate its trailing stop (or
                # extend its leading target) is by definition not
                # sideways and stays governed by stop/target instead.
                # max_hold_minutes is a live runtime setting
                # (RUNTIME_SETTINGS_META), not hardcoded - default 120
                # min, tunable without a redeploy.
                exit_reason = "stale_timeout"
            elif is_squareoff_time:
                exit_reason = "eod_squareoff"

            if exit_reason:
                qty = row["qty"]
                entry_fx = row["fx_to_inr"]  # same rate used at entry, for a consistent round-trip
                pnl_native = (last_close - row["entry_price"]) * qty
                pnl_inr = pnl_native * entry_fx
                # rr_achieved is measured against the ORIGINAL planned risk
                # (initial_stop_loss), not the trailed stop - otherwise a
                # trade that trailed close to exit would report an inflated
                # R-multiple off its own shrunken stop_dist.
                stop_dist = row["entry_price"] - (row["initial_stop_loss"] or row["stop_loss"])
                rr_achieved = round((last_close - row["entry_price"]) / stop_dist, 2) if stop_dist else None
                payload = {
                    "symbol": symbol, "action": "sell", "qty": qty, "price": last_close,
                    "currency": currency, "fx_to_inr": entry_fx,
                    "strategy": strategy_tag, "exit_reason": exit_reason,
                    "entry_price": row["entry_price"], "stop_loss": current_stop,
                    "initial_stop_loss": row["initial_stop_loss"],
                    "trailing_active": current_stop > (row["initial_stop_loss"] or row["stop_loss"]),
                    "target": current_target,
                    "leading_target_active": current_target > row["target"],
                    "rr_target": rr, "rr_achieved": rr_achieved,
                    "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
                    "pnl_pct_of_capital": round(100 * pnl_inr / capital, 3),
                }
                apply_paper_trade(conn, symbol, "sell", qty, last_close)
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
                    (time.time(), symbol, qty, last_close, entry_fx, strategy_tag, json.dumps(payload)),
                )
                conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
                conn.commit()
                result.update(
                    action_taken=f"exited_{exit_reason}", exit_pnl_inr=payload["pnl_inr"],
                    exit_pnl_pct=payload["pnl_pct_of_capital"], rr_achieved=rr_achieved,
                )
                return result

            result["open_position"] = {**dict(row), "stop_loss": current_stop, "target": current_target}
            return result

        # ---- look for a new entry ----
        if halted:
            result["action_taken"] = "blocked_daily_loss_cap"
            return result
        if not is_trading_enabled(conn):
            result["action_taken"] = "trading_paused"
            return result
        if is_squareoff_time:
            result["action_taken"] = "no_new_entries_market_closing"
            return result

        if strategy == "orb_breakout":
            # Stronger entries, explicit user instruction 2026-09-04: too
            # many trades were closing at a few rupees of P&L (e.g. real
            # closed trades this session hit only rr_achieved 0.05/0.38 -
            # a tiny fraction of the 3.0 target) - more transactions also
            # means more tax events for no real edge. Two tightenings, both
            # reusing existing, already-justified thresholds rather than
            # inventing new numbers:
            #   1. The breakout must clear orb_high by a real margin, not
            #      just touch it - ENTRY_BREAKOUT_MARGIN_PCT filters the
            #      marginal single-tick "breakouts" that are really just
            #      noise around the level.
            #   2. The trend must be confidently up, not just
            #      SMA-fast > SMA-slow by any amount - defaults to the SAME
            #      TREND_WEAKENED_MIN_CONFIDENCE (95%) bar already trusted
            #      for the early-exit check, but is now live-editable via
            #      the min_entry_confidence_pct runtime setting (see
            #      RUNTIME_SETTINGS_META/trade-view's constraints panel) -
            #      the exit-side constant itself is untouched by that knob.
            #   3. Real volume behind the move, not just a low-conviction
            #      drift through the level - see VOLUME_CONFIRM_LOOKBACK's
            #      own comment (explicit user instruction 2026-09-08:
            #      "volume is must have trigger constraint... for all
            #      trades"). This is the 4th required confluence flag
            #      alongside breakout/trend/confidence, per the same-day
            #      instruction to require "a combo of three four green
            #      flags before the trade entry" rather than one indicator.
            volume_ok, vol_avg = _volume_confirms(df["Volume"].to_numpy(dtype=float))
            breakout_level = orb_high * (1 + ENTRY_BREAKOUT_MARGIN_PCT / 100)
            entry_signal = (
                last_close > breakout_level and trend == "up"
                and _trend_confidence(closes, sma_fast, sma_slow, ma_type) >= min_entry_confidence_pct / 100
                and volume_ok
            )
            structural_low = orb_low
            entry_reason = "orb_breakout_with_trend"
            result["volume_gate"] = {
                "confirmed": volume_ok, "avg_volume": vol_avg,
                "current_volume": float(df["Volume"].iloc[-1]) if len(df) else None,
            }
        else:  # bullish_engulfing - see add_strategy_signal() for the backtested version
            cur_bar, prev_bar = df.iloc[-1], df.iloc[-2]
            cur_bullish = cur_bar["Close"] > cur_bar["Open"]
            prev_bearish = prev_bar["Close"] < prev_bar["Open"]
            entry_signal = bool(
                cur_bullish and prev_bearish
                and cur_bar["Open"] <= prev_bar["Close"] and cur_bar["Close"] >= prev_bar["Open"]
            )
            if entry_signal and trend_sma > 0:
                full_closes = df["Close"].to_numpy(dtype=float)
                if len(full_closes) < trend_sma:
                    entry_signal = False
                else:
                    entry_signal = last_close > float(np.mean(full_closes[-trend_sma:]))
            # Volume confirmation is now UNCONDITIONAL (2026-09-08, explicit
            # user instruction: "volume is must have trigger constraint...
            # for all trades") - previously gated behind the volume_confirm
            # parameter/WATCHLIST field, which most symbols never opted
            # into. That parameter is kept (API compatibility) but no
            # longer read here; _volume_confirms is the same shared check
            # orb_breakout now also requires - see its own docstring.
            volume_ok, vol_avg = _volume_confirms(df["Volume"].to_numpy(dtype=float))
            if entry_signal:
                entry_signal = volume_ok
            result["volume_gate"] = {
                "confirmed": volume_ok, "avg_volume": vol_avg,
                "current_volume": float(cur_bar["Volume"]) if "Volume" in df.columns else None,
            }
            structural_low = float(cur_bar["Low"])
            orb_high, orb_low = float(cur_bar["High"]), structural_low  # for result/signal_state display only
            entry_reason = f"bullish_engulfing_trend{trend_sma}"

        # Sentiment gate (2026-09-07, explicit user instruction: "i want
        # this info to be used for sector specific knowledge to pick
        # assets for trading ... in almost real time") - a soft, fail-
        # open filter on top of the strategy's own technical signal, read
        # from docs/sentiment_log/*.md (the external news-scan routine's
        # own output - see sentiment_signals.py's docstring for exactly
        # what is/isn't parseable from it). Never invents a reason to
        # enter; only ever SUPPRESSES a technically-valid entry when the
        # latest known sentiment for this symbol's proxy is Bearish.
        # result["sentiment_gate"] is always set (even when entry_signal
        # was already False) so /scheduler-pipeline's per-symbol detail
        # shows what sentiment data this tick actually saw.
        sentiment_allowed, sentiment_reason = True, "not_checked_no_entry_signal"
        if entry_signal:
            sentiment_allowed, sentiment_reason = sentiment_signals.allows_entry(symbol, ist_now().strftime("%Y-%m-%d"))
            if not sentiment_allowed:
                entry_signal = False
                entry_reason = f"{entry_reason}_but_{sentiment_reason}"
        result["sentiment_gate"] = {"allowed": sentiment_allowed, "reason": sentiment_reason}

        if entry_signal:
            # Stop is the strategy's own technical level (opening-range low
            # for orb_breakout, the entry candle's own low for
            # bullish_engulfing), capped at stop_pct% max risk - whichever
            # is tighter (closer to entry) wins, so the trade never risks
            # more than the cap even if the structural level is wider.
            stop_loss_cap = last_close * (1 - stop_pct / 100)
            stop_loss = max(structural_low, stop_loss_cap)
            stop_dist = last_close - stop_loss
            if stop_dist <= 0:
                result["action_taken"] = "invalid_stop_skipped"
                return result
            target = last_close + rr * stop_dist

            # risk_amount is Rs (part of the shared capital pool); stop_dist
            # is native currency (e.g. USD for SPY) - must convert one to
            # the other's currency before dividing, or a USD stop distance
            # gets divided into a Rs budget as if $1 == Rs 1.
            stop_dist_inr = stop_dist * fx_to_inr

            # Capital is shared and finite - cap qty so this trade's notional
            # doesn't push total deployed capital across all open symbols
            # past `capital`. Also: no single new trade may claim more than
            # one tranche (capital / CAPITAL_TRANCHES) of the pool, even if
            # more is sitting free - reserves room for other opportunities
            # to be taken in parallel instead of one big position locking
            # out everything else for the rest of the day (this happened
            # for real 2026-09-03: one BTC-USD entry used the entire pool).
            # Whichever symbol is evaluated first in a poll cycle still gets
            # first claim within its tranche limit; a true cross-symbol
            # "best signal wins" ranking is a fast-follow.
            available_capital_inr = max(0.0, capital - deployed_notional(conn))
            max_single_trade_inr = capital / CAPITAL_TRANCHES
            usable_capital_inr = min(available_capital_inr, max_single_trade_inr)
            notional_per_unit_inr = last_close * fx_to_inr

            # Capital reallocation (2026-09-03, explicit user instruction -
            # docs/TRADING_CONSTRAINTS.md "Capital reallocation"): the pool
            # is genuinely full - before giving up on this signal, see if a
            # weaker, still-fine (breakeven-or-better, still trending the
            # right way) live position should hand over just enough capital
            # to fund it. Only tried when there's a real shortage (not
            # routinely), one position at a time, capped per day - see
            # REALLOCATION_MIN_CONFIDENCE_GAP/REALLOCATION_MAX_PER_DAY.
            if usable_capital_inr < notional_per_unit_inr and notional_per_unit_inr > 0:
                if _count_reallocations_today(conn, since_ts) < REALLOCATION_MAX_PER_DAY:
                    new_confidence = _trend_confidence(closes, sma_fast, sma_slow, ma_type)
                    source = _find_reallocation_source(
                        conn, symbol, new_confidence, max_single_trade_inr - available_capital_inr
                    )
                    if source is not None:
                        _execute_partial_exit(
                            conn, source["symbol"], source["qty_to_sell"], source["last_close"],
                            symbol, new_confidence,
                        )
                        available_capital_inr = max(0.0, capital - deployed_notional(conn))
                        usable_capital_inr = min(available_capital_inr, max_single_trade_inr)
                        result["reallocated_from"] = {
                            "symbol": source["symbol"], "qty_sold": source["qty_to_sell"],
                            "its_confidence": round(source["confidence"], 4),
                            "new_candidate_confidence": round(new_confidence, 4),
                        }

            # Per-trade risk is risk_per_trade_pct% of the capital actually
            # INVESTED IN THIS TRADE (usable_capital_inr - the tranche/
            # available-capital-capped amount this trade can deploy), not
            # risk_per_trade_pct% of the whole account - explicit standing
            # policy (2026-09-03). Sizing no longer shrinks as the day's
            # running P&L worsens (explicit user instruction 2026-09-03 -
            # "I want net loss to be 2% for all trades for the day, not
            # that loss budget") - remaining_budget stays a separate,
            # independently-enforced HALT: once net loss for the day
            # reaches daily_risk_pct%, `halted` blocks every new entry
            # outright (see blocked_daily_loss_cap above), rather than this
            # sizing math quietly shrinking trades as that threshold gets
            # closer. Every entry sizes at its own full risk_per_trade_pct
            # until the moment trading actually halts.
            risk_amount_inr = usable_capital_inr * risk_per_trade_pct / 100
            # Fractional qty, not integer-floored: a high-priced unit (gold
            # ~Rs 4.2L/oz, BTC ~Rs 73L/coin) costs more than this account's
            # entire Rs 2L capital, so int() silently zeroed every such
            # trade to "insufficient_capital" regardless of the strategy's
            # real edge - confirmed this had been blocking every BTC-USD/
            # ETH-USD entry all session. Real brokers (crypto exchanges,
            # fractional-share equity brokers, gold ETF/mini-lot products)
            # support this; treat it the same way here rather than
            # silently discarding a good signal to a rounding artifact.
            qty = risk_amount_inr / stop_dist_inr if stop_dist_inr > 0 else 0.0

            if notional_per_unit_inr > 0:
                qty = min(qty, usable_capital_inr / notional_per_unit_inr)
            qty = round(qty, 6)

            # NSE cash equities trade in WHOLE SHARES only - no fractional
            # delivery orders, confirmed from Kotak's own place_order
            # validation (quantity must be a positive integer string, see
            # kotak_real_orders.py/req_data_validation.py). Explicit user
            # instruction 2026-09-04 ("mimic as per NSE rules") after a real
            # confusion this caused: paper showed ITC.NS qty=3.767898,
            # HINDUNILVR.NS qty=0.506073 - positions no real NSE order could
            # ever match, which is exactly backwards for a rehearsal meant
            # to mirror what stage 3 will actually do. Floored, not rounded
            # - never round UP past what the risk budget actually allows.
            # Deliberately scoped to nse_equity only - the fractional-qty
            # design above this comment was itself a deliberate fix for
            # high-priced non-NSE units (BTC/ETH/gold) where int() had been
            # silently zeroing every real-edge signal; that reasoning still
            # holds for those asset classes, just not for NSE cash equities.
            if _asset_class_and_source(symbol)[0] == "nse_equity":
                qty = float(math.floor(qty))

            # A trade sized to a few rupees isn't a real position - guard
            # against dust-sized fills from float rounding rather than
            # requiring a whole unit.
            MIN_TRADE_NOTIONAL_INR = 100.0
            if qty <= 0 or qty * notional_per_unit_inr < MIN_TRADE_NOTIONAL_INR:
                result["action_taken"] = (
                    "insufficient_capital" if available_capital_inr < notional_per_unit_inr
                    else "budget_too_small_for_1_unit"
                )
                result["available_capital_inr"] = round(available_capital_inr, 2)
                return result

            notional_inr = qty * last_close * fx_to_inr
            payload = {
                "symbol": symbol, "action": "buy", "qty": qty, "price": last_close,
                "currency": currency, "fx_to_inr": fx_to_inr,
                "strategy": strategy_tag, "entry_reason": entry_reason,
                "stop_loss": stop_loss, "target": target, "rr_target": rr,
                "risk_amount_inr": round(risk_amount_inr, 2),
                "risk_pct_of_capital": round(100 * risk_amount_inr / capital, 3),
                "notional_native": round(qty * last_close, 2), "notional_inr": round(notional_inr, 2),
                "reallocated_from": result.get("reallocated_from"),
            }
            apply_paper_trade(conn, symbol, "buy", qty, last_close)
            conn.execute(
                "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
                (time.time(), symbol, qty, last_close, fx_to_inr, strategy_tag, json.dumps(payload)),
            )
            conn.execute(
                "INSERT INTO signal_state "
                "(symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, entry_ts, orb_high, orb_low, fx_to_inr, interval) "
                "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET day=excluded.day, status=excluded.status, "
                "entry_price=excluded.entry_price, stop_loss=excluded.stop_loss, "
                "initial_stop_loss=excluded.initial_stop_loss, "
                "target=excluded.target, qty=excluded.qty, entry_ts=excluded.entry_ts, "
                "orb_high=excluded.orb_high, orb_low=excluded.orb_low, fx_to_inr=excluded.fx_to_inr, "
                "interval=excluded.interval",
                (symbol, today_str, last_close, stop_loss, stop_loss, target, qty, time.time(), orb_high, orb_low, fx_to_inr, interval),
            )
            conn.commit()
            result.update(action_taken="entered_long", entry=payload)
            return result

        result["action_taken"] = "no_signal"
        return result


@app.get("/auto-signal")
def auto_signal(
    symbol: str,
    capital: float = 400000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 3.0,
    orb_minutes: int = 15,
    sma_fast: int = 9,
    sma_slow: int = 21,
    interval: str = "5m",
    tz_offset_min: int = IST_OFFSET_MIN,
    open_min: int = 9 * 60 + 15,
    close_min: int = 15 * 60 + 30,
    squareoff_min: int = 15 * 60 + 20,
    trade_weekends: bool = False,
    currency: str = "INR",
    strategy: str = "orb_breakout",
    trend_sma: int = 0,
    volume_confirm: bool = False,
    min_entry_confidence_pct: float = TREND_WEAKENED_MIN_CONFIDENCE * 100,
    max_hold_minutes: float = 120.0,
    ma_type: str = "ema",  # 2026-09-09: SMA -> EMA everywhere, explicit user instruction
):
    """HTTP wrapper around _auto_signal_core - see that function's docstring
    for the actual rules. Kept as a thin pass-through so manual/GH-Actions
    calls and the in-process scheduler share one implementation."""
    return _auto_signal_core(
        symbol=symbol, capital=capital, daily_risk_pct=daily_risk_pct,
        risk_per_trade_pct=risk_per_trade_pct, stop_pct=stop_pct, rr=rr,
        orb_minutes=orb_minutes, sma_fast=sma_fast, sma_slow=sma_slow, interval=interval,
        tz_offset_min=tz_offset_min, open_min=open_min, close_min=close_min,
        squareoff_min=squareoff_min, trade_weekends=trade_weekends, currency=currency,
        strategy=strategy, trend_sma=trend_sma, volume_confirm=volume_confirm,
        min_entry_confidence_pct=min_entry_confidence_pct, max_hold_minutes=max_hold_minutes,
        ma_type=ma_type,
    )


# ---------------------------------------------------------------------------
# In-process scheduler: replaces reliance on GitHub Actions' `schedule:` cron
# for the actual timing of entries/exits. GH Actions scheduled runs proved
# unreliable in practice (2026-09-02: ~1 of ~75 expected 5-min NSE polls
# actually fired; similar drop rate on crypto/US - see docs/KNOWN_ISSUES.md).
# This loop runs inside the same always-imported process Render keeps alive,
# checking every SCHEDULER_INTERVAL_SECONDS with no dependency on any
# external trigger. It does NOT fix Render free-tier sleep (the process
# stops running entirely when asleep, scheduler included) - only an
# always-on paid plan does that. The external GH Actions workflows are kept
# as a redundant backstop (harmless: _auto_signal_core is idempotent, checked
# against DB state on every call) and, more importantly, as one of the ways
# the server gets woken back up.
# ---------------------------------------------------------------------------

# 2026-09-03: rescoped to NSE/BSE ONLY, per explicit user instruction -
# "currently work on only Indian stock market and stocks available to
# Indian trader via Kotak Neo and Zerodha accounts. Screen only these
# stocks and index." Every non-Indian entry (crypto, US mega-caps/ETFs,
# COMEX gold futures) is removed - none of those are instruments an Indian
# trader can actually place through Kotak Neo or Zerodha, so backtesting/
# paper-trading them had no path to ever becoming real trades. The open
# GC=F position was force-closed (POST /trading-control?action=kill, then
# resumed) before this change landed, so nothing was orphaned by its
# removal from WATCHLIST. Options overlay is correspondingly disabled
# (OPTIONS_ELIGIBLE_SYMBOLS = [] below) - it only ever covered US
# underliers; real NSE F&O still requires the same Kotak Neo broker
# connection as real NSE cash-market data does (see docs/
# TRADING_CONSTRAINTS.md's standing NSE-data-gating rule) and stays off
# until that exists, never synthesized as a workaround.
# NSE stock universe - expanded 2026-09-03 per explicit user pushback on
# the earlier 15-name curated list: "Use list for now from public
# available listing of assets... why not u getting whole set of assets."
# Fair - a hand-picked 15 was an arbitrary editorial cut. This is the
# Nifty 100 (Nifty 50 + Nifty Next 50) - NSE's own published index
# constituent lists, i.e. an actual "public available listing," not
# picks of my own. ~6.7x the previous list. Still short of literally
# every NSE-listed stock (~2,000+, most illiquid/thinly-traded, some
# ticker-symbol drift possible below since index composition changes
# periodically - a stale/wrong ticker fails safe as one symbol's
# data_error, never a crash) - going further (Nifty 200/500, or a workflow
# that fetches NSE's live official list instead of this hardcoded one) is
# a reasonable next step if this still isn't enough.
NSE_STOCK_DEFAULT_PARAMS = {
    "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
    "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
    "trade_weekends": False, "currency": "INR",
    "risk_pct": 1.0, "stop_pct": 1.0,  # unproven -> half ceiling until evidenced, same as before
}
NSE_STOCK_UNIVERSE = [
    # Nifty 50
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "ASIANPAINT.NS",
    "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS",
    "NESTLEIND.NS", "BAJAJFINSV.NS", "POWERGRID.NS", "NTPC.NS", "TATAMOTORS.NS",
    "TATASTEEL.NS", "M&M.NS", "INDUSINDBK.NS", "JSWSTEEL.NS", "ADANIENT.NS",
    "ADANIPORTS.NS", "COALINDIA.NS", "GRASIM.NS", "HINDALCO.NS", "CIPLA.NS",
    "DRREDDY.NS", "EICHERMOT.NS", "TECHM.NS", "BRITANNIA.NS", "DIVISLAB.NS",
    "APOLLOHOSP.NS", "BAJAJ-AUTO.NS", "TATACONSUM.NS", "SBILIFE.NS", "HDFCLIFE.NS",
    "LTIM.NS", "SHRIRAMFIN.NS", "TRENT.NS", "HEROMOTOCO.NS", "UPL.NS",
    # Nifty Next 50
    "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS", "DMART.NS", "BANKBARODA.NS",
    "BOSCHLTD.NS", "CANBK.NS", "CHOLAFIN.NS", "DABUR.NS", "DLF.NS",
    "GODREJCP.NS", "HAVELLS.NS", "HAL.NS", "HINDPETRO.NS", "ICICIGI.NS",
    "ICICIPRULI.NS", "INDIGO.NS", "IOC.NS", "IRFC.NS", "JINDALSTEL.NS",
    "JIOFIN.NS", "LICI.NS", "MARICO.NS", "MOTHERSON.NS", "MUTHOOTFIN.NS",
    "NHPC.NS", "ONGC.NS", "PIDILITIND.NS", "PNB.NS", "PFC.NS",
    "RECLTD.NS", "SIEMENS.NS", "SRF.NS", "TATAPOWER.NS", "TORNTPHARM.NS",
    "UNIONBANK.NS", "MCDOWELL-N.NS", "VEDL.NS", "ZOMATO.NS", "ZYDUSLIFE.NS",
    "BEL.NS", "BPCL.NS", "GAIL.NS", "NAUKRI.NS", "LUPIN.NS",
    "POLYCAB.NS", "UBL.NS",
]

def _load_nse_universe_from_file() -> list[str]:
    """Loads the full NSE EQ-series universe from docs/nse_universe.json -
    real data pulled from Kotak's own scrip master (kotak_neo.py:
    scrip_master(), via GET /kotak-neo/nse-universe), not a hand-picked
    index list. Falls back to the hardcoded Nifty 100 (NSE_STOCK_UNIVERSE
    above) if the file is missing, unreadable, or looks too small to
    trust - same "a data problem degrades, never crashes, the live app"
    discipline as every other external fetch in this file.

    Explicit user instructions (2026-09-05): "there is just 103 stocks in
    the list. why not nifty 500 for this... all and nifty 500 all
    inclusive", then "cant you source it from kotak neo. all the tickers
    which it can provide." This is broader than Nifty 500 membership -
    Kotak's scrip master carries no index-membership column, so it's
    every EQ-series NSE stock (~2,600), ETFs included, not just the 500
    names in that index.

    NOT fetched live at import time (would make every process start
    depend on Kotak's login flow succeeding) - reads the committed JSON
    snapshot instead. See refresh-nse-universe.yml for the weekly
    (Monday) job that keeps docs/nse_universe.json itself current."""
    import json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "nse_universe.json")
    try:
        with open(path) as f:
            data = json.load(f)
        symbols = data.get("symbols") or []
        if len(symbols) < 500:
            raise ValueError(f"only {len(symbols)} symbols in {path} - too small to trust")
        return symbols
    except Exception as e:
        print(f"[nse_universe] {path} unusable ({e}) - falling back to hardcoded Nifty 100 list")
        return list(NSE_STOCK_UNIVERSE)


# Scale tradeoff, flagged rather than silently absorbed: growing from the
# ~103-symbol Nifty 100 list to the ~2,600-symbol full EQ universe below
# means round-robin entry-scanning (SCHEDULER_ENTRY_SCAN_BATCH_SIZE,
# further down) takes a full rotation from ~4.5 minutes to well over an
# hour at the CURRENT batch size - each flat symbol's entry condition is
# checked far less often. Deliberately did NOT bump the batch size to
# compensate here: more symbols fetched per 30s tick raises real risk of
# either tripping Yahoo Finance's unofficial rate limit or making one
# tick's wall-clock time exceed SCHEDULER_INTERVAL_SECONDS on Render's
# free-tier CPU - both are worse failure modes than slower rotation. Left
# for a deliberate follow-up decision instead of guessing.
NSE_FULL_UNIVERSE = _load_nse_universe_from_file()

# Per-symbol evidenced param overrides - explicit user instruction
# 2026-09-07 ("the nse equity or index win rate is low... how r u
# planning to improve it" -> "do whatever you can so that whole day
# becomes profitable"). Real /sweep backtest evidence (60d, 5m,
# orb_breakout, grid: orb_minutes 10/15/30 x sma_fast 5/9/14 x sma_slow
# 21/50 - 18 combos per symbol) - judged the same way gold's own
# evidence bar requires: not the single best combo (curve-fit risk on
# one historical window), but pct_profitable_combos and median_total_pnl
# too, so a real, repeatable edge across nearby params, not a lone spike:
#   RELIANCE.NS:  77.8% of combos profitable, median +11.1, best 56.7% win rate
#   TCS.NS:       83.3% of combos profitable, median +98.95, best 69.0% win rate
#   ICICIBANK.NS: 94.4% of combos profitable, median +25.9, best 56.8% win rate
#   INFY.NS:      100%  of combos profitable, median +52.4, best 64.7% win rate
# All four cleared risk_pct/stop_pct from the 1% "unproven" default to
# the full 2% ceiling - same bar gold already cleared.
# HDFCBANK.NS was ALSO swept the same day and came back the OPPOSITE way
# (0% of 18 combos profitable, median -64.45, best win rate only 36.1%) -
# left at the conservative 1% default deliberately, not raised. Real
# evidence here argues against this exact strategy/param range on this
# symbol - flagging rather than silently leaving it unexamined. The rest
# of NSE_FULL_UNIVERSE hasn't been swept yet - stays on the untuned
# default until it has, same "unproven -> half ceiling" rule as always.
NSE_STOCK_PARAM_OVERRIDES = {
    "RELIANCE.NS": {"orb_minutes": 15, "sma_fast": 5, "sma_slow": 21, "risk_pct": 2.0, "stop_pct": 2.0},
    "TCS.NS": {"orb_minutes": 10, "sma_fast": 14, "sma_slow": 50, "risk_pct": 2.0, "stop_pct": 2.0},
    "ICICIBANK.NS": {"orb_minutes": 10, "sma_fast": 5, "sma_slow": 21, "risk_pct": 2.0, "stop_pct": 2.0},
    "INFY.NS": {"orb_minutes": 30, "sma_fast": 9, "sma_slow": 50, "risk_pct": 2.0, "stop_pct": 2.0},
    # MARUTI.NS: 83.3% of combos profitable, median +136.0 - added in a
    # second sweep batch the same day (9 more Nifty50 names tested; this
    # was the only one of the 9 to clear the bar - HDFCBANK/HINDUNILVR/
    # BHARTIARTL/KOTAKBANK/LT/AXISBANK/ASIANPAINT all came back negative,
    # SBIN/BAJFINANCE flat - left on the untuned default, none raised).
    # Its own best combo's win rate (46.9%) is BELOW 50% - the edge here
    # is bigger average wins vs losses, not a favorable coin-flip, a
    # genuinely different profile from the other four above.
    "MARUTI.NS": {"orb_minutes": 30, "sma_fast": 14, "sma_slow": 21, "risk_pct": 2.0, "stop_pct": 2.0},
}

WATCHLIST = [
    # NSE/BSE indices - IST 9:15-15:30, weekdays. Params from 2026-09-02
    # research (docs/daily_logs/2026-09-02-entry-trigger-research.md).
    # risk_pct/stop_pct: 2% is the account-wide MAXIMUM
    # (docs/TRADING_CONSTRAINTS.md), not a fixed rate - set lower per
    # symbol where evidence supports it. NIFTY/BANKNIFTY/SENSEX run the
    # full evidence-backed ceiling (2%) - real 60-day backtest evidence
    # behind this exact strategy.
    {"symbol": "^NSEI", "orb_minutes": 30, "sma_fast": 5, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False, "currency": "INR", "risk_pct": 2.0, "stop_pct": 2.0},
    {"symbol": "^NSEBANK", "orb_minutes": 5, "sma_fast": 9, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False, "currency": "INR", "risk_pct": 2.0, "stop_pct": 2.0},
    {"symbol": "^BSESN", "orb_minutes": 30, "sma_fast": 20, "sma_slow": 50,
     "tz_offset_min": IST_OFFSET_MIN, "open_min": 555, "close_min": 930, "squareoff_min": 920,
     "trade_weekends": False, "currency": "INR", "risk_pct": 2.0, "stop_pct": 2.0},
] + [
    {"symbol": sym, **NSE_STOCK_DEFAULT_PARAMS, **NSE_STOCK_PARAM_OVERRIDES.get(sym, {})}
    for sym in NSE_FULL_UNIVERSE
] + [
    # MCX commodities - restored 2026-09-03 per explicit user instruction
    # ("keep all those assets listed in Zerodha") - unlike crypto and US
    # equities (genuinely not offered by Kotak Neo/Zerodha at all, so they
    # stay excluded), gold/silver/crude oil ARE real Zerodha-tradable
    # instruments via the MCX segment. yfinance has no free MCX ticker, so
    # these run on the international futures contract as a PRICE-ACTION
    # PROXY for the real MCX contract each maps to (real symbol names
    # confirmed by the user 2026-09-03, matters once Kotak Neo/Zerodha
    # execution actually needs the MCX-side symbol):
    #   GC=F (COMEX Gold, USD/troy oz)   -> MCX "GOLD"
    #   SI=F (COMEX Silver, USD/troy oz) -> MCX "SILVER" (30 kg, 999 purity contract)
    #   CL=F (NYMEX WTI Crude, USD/bbl)  -> MCX "CRUDEOIL" (MCX's own contract
    #                                       is explicitly WTI-benchmarked)
    # MCX's own INR price differs from each of these (import duty, currency,
    # local demand/supply) but tracks the same underlying commodity closely
    # enough that a candlestick pattern/breakout signal should transfer
    # directionally. Same near-24h shape as before (COMEX/NYMEX close
    # weekends same as MCX broadly does).
    # Gold: real evidence already exists (100% of 24 swept combos
    # profitable, best 65% win rate/+676.50 over 60d -
    # docs/strategy_log.xlsx, from before this symbol was briefly removed
    # then restored) - full 2% ceiling, same bar as the NSE indices.
    # Silver/crude: no evidence yet - half ceiling (1%) until they earn one.
    # BUG found live 2026-09-08 (explicit user finding: "if the commodity
    # market is open then why this error? GOLD/SILVER/CRUDE OIL -
    # waiting_for_opening_range"): open_min=0 assumed the ORB window
    # (mins 0-14) falls right after UTC midnight - but a live /history
    # pull for GC=F (period=1d, interval=5m) showed the FIRST bar of every
    # UTC-dated "today" bucket lands at 2026-09-08T00:00:00-04:00 =
    # 04:00 UTC, not 00:00 UTC - Yahoo's own intraday data for these US-
    # exchange futures is day-bucketed against US Eastern midnight, not
    # UTC midnight. The old open_min=0 window (00:00-00:14 UTC) therefore
    # fell entirely inside a 4-hour span with ZERO bars, every single day
    # - orb_df was always empty, permanently stuck at
    # "waiting_for_opening_range" regardless of how many hours the actual
    # market had been open. This had likely never generated a single live
    # entry for gold/silver/crude since these were added, despite paper-
    # tracking running the whole time. open_min=240 (4:00 UTC = US Eastern
    # midnight, EDT) matches where real data is confirmed to start.
    # CAVEAT this codebase already accepts elsewhere (see IST_OFFSET_MIN's
    # own "no holiday calendar" comment): no DST tracking here either - US
    # Eastern is EDT (UTC-4) roughly mid-March to early November and EST
    # (UTC-5) the rest of the year, so this drifts by up to 1 hour outside
    # EDT season. Re-verify against a live /history pull after the next
    # US DST changeover if the "waiting_for_opening_range" symptom returns.
    {"symbol": "GC=F", "orb_minutes": 15, "sma_fast": 20, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 240, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": False, "currency": "USD", "risk_pct": 2.0, "stop_pct": 2.0},
    {"symbol": "SI=F", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 240, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
    {"symbol": "CL=F", "orb_minutes": 15, "sma_fast": 9, "sma_slow": 21,
     "tz_offset_min": 0, "open_min": 240, "close_min": 1439, "squareoff_min": 1439,
     "trade_weekends": False, "currency": "USD", "risk_pct": 1.0, "stop_pct": 1.0},
]

# ---------------------------------------------------------------------------
# Kill switch / pause-resume - explicit standing user instruction 2026-09-03:
# "I want to decide when to do trading and when not." A single master
# switch (trading_control, one row) gates every NEW entry across every
# symbol/instrument - equity and options alike - checked inside
# _auto_signal_core/_options_signal_core themselves (not just in
# _scheduler_loop) so the redundant GH Actions backstop calls
# (live-signals*.yml, which hit /auto-signal and /options-signal directly)
# can't bypass a pause. Pausing NEVER stops managing an already-open
# position - stop/target/trend/eod-squareoff keep running exactly as
# before, since an unwatched open position would be far more dangerous
# than a paused account. The kill switch (action=kill) goes further: force-
# closes every open position right now at the best available price AND
# pauses, so nothing reopens on the very next tick.
def is_trading_enabled(conn) -> bool:
    row = conn.execute("SELECT enabled FROM trading_control WHERE id = 1").fetchone()
    return bool(row["enabled"]) if row else True  # never explicitly set -> default ON


# --- Stage 3: real order placement (2026-09-04) -----------------------------
REAL_TRADING_DAILY_CAP_INR = 2000.0  # explicit user instruction 2026-09-04 ("use 2000 as whole" -
# confirmed via AskUserQuestion to mean "raise the daily cap to Rs 2000",
# same per-IST-day semantics as the original Rs 500 cap, not a lifetime
# ceiling), raised from the original Rs 500.


def is_real_trading_enabled(conn) -> bool:
    """TWO independent gates, both required - explicit user instruction,
    2026-09-04: (1) the paper kill switch (trading_control.enabled) - real
    entries are only ever attempted right after _auto_signal_core itself
    returns "entered_long" for an equity, which the kill switch already
    blocks when off, so this function doesn't re-check it directly, and
    (2) REAL_TRADING_ENABLED, a Render env var set manually there, kept
    deliberately separate from any code push or UI action so real trading
    can never turn on by itself.

    Until today this also checked a third gate - a real_trading_control DB
    row, toggled via a token-gated popup on trade-view. That popup was
    removed per explicit user instruction ("I will control real money
    trade from env variable manually whenever needed"); this function was
    NOT updated at the same time, so the DB row - stuck at enabled=1 with
    no UI left to see or change it - kept silently gating real trading
    with no visibility. Found live and fixed same-day: dropped that check
    entirely rather than leave an invisible switch armed. See
    docs/TRADING_CONSTRAINTS.md for the full history if this needs
    revisiting."""
    return os.environ.get("REAL_TRADING_ENABLED") == "YES"


def _real_today_spent_inr(conn) -> float:
    """Sum of today's (IST calendar day) CONFIRMED real buy notional -
    the only thing that counts against REAL_TRADING_DAILY_CAP_INR. Sourced
    entirely from real_trades, which this codebase populates itself at
    order-attempt time using a verified live LTP - not from parsing
    Kotak's own trade_report()/order_report() (see kotak_real_orders.py's
    module docstring for why those aren't trusted for this)."""
    today = ist_now().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(notional_inr), 0) AS s FROM real_trades "
        "WHERE day = ? AND side = 'B' AND status = 'confirmed'",
        (today,),
    ).fetchone()
    return float(row["s"] or 0.0)


_T1_HOLDINGS_MARKER = "T1 holdings"  # exact substring Kotak's own RMS rejection uses
# Found live 2026-09-09 (MEDICAMEQ.NS - Medicamen Biotech Ltd, actually a
# regulatory Trade-to-Trade/T2T-segment stock, not just Kotak's own T1-
# holdings RMS check): the SAME same-day-sell restriction can surface
# under a COMPLETELY different message - "Insufficient quantity held for
# this order... Selling Trade-to-Trade stocks on the same day of purchase
# is not allowed." This is a harder constraint than a broker RMS quirk -
# it's SEBI/exchange surveillance-category enforced, meaning NEITHER a
# target NOR (once triggered) a stop-loss can ever complete same-day for
# a T2T stock, no workaround possible until T+1. Both markers are
# checked; the flag/table name stays "t1_restricted" (not renamed to
# avoid a migration) but now covers both root causes equally.
_T2T_SAME_DAY_MARKER = "Trade-to-Trade stocks on the same day"

# real_t1_restricted external persistence (Upstash Redis) - 2026-09-09,
# found live right after making the restriction PERMANENT: MEDICAMEQ.NS
# and SILVERCASE.NS had already been confirmed T1/T2T-restricted (a real
# Kotak rejection, logged), but real_t1_restricted is a plain SQLite
# table exactly as ephemeral as every other one on this Render service -
# the very next deploy (of the "make it permanent" fix itself, and every
# one since) wiped it clean again, so the dashboard's own target_status
# fell back to "not_yet_attempted" instead of "blocked" and a fresh real
# entry attempt tomorrow would have hit the exact same wall all over
# again - the "permanent" fix wasn't actually permanent against this
# app's own restart cadence. Same Upstash-mirror pattern as real_positions/
# rr_cursor/check_counts/runtime_settings above, applied here as one JSON
# snapshot of the whole table.
_T1_RESTRICTED_REDIS_KEY = "tv_paper_bot:real_t1_restricted:v1"


def _sync_t1_restricted_external(conn) -> None:
    """Call right after a new row is flagged. Best-effort and silent, same
    pattern as every other _sync_*_external above."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return
    try:
        rows = conn.execute("SELECT symbol, day, flagged_at, detail FROM real_t1_restricted").fetchall()
        snapshot = [dict(r) for r in rows]
        requests.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{_T1_RESTRICTED_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            data=json.dumps(snapshot).encode("utf-8"),
            timeout=5,
        )
    except Exception as e:
        print(f"[t1_restricted_external] sync failed (non-fatal): {e}")


def hydrate_t1_restricted_from_external(conn) -> int:
    """Startup-time restore, sourced from Upstash - real-time, so a
    restriction confirmed on ANY earlier day/restart survives every
    future restart, making the 2026-09-09 'permanent, not day-scoped' fix
    to _is_t1_restricted actually permanent in practice, not just in
    intent. Returns how many rows were restored (0 if Upstash is unset/
    unreachable/empty)."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return 0
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{_T1_RESTRICTED_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("result")
        if not raw:
            return 0
        snapshot = json.loads(raw)
        if not isinstance(snapshot, list):
            return 0
    except Exception as e:
        print(f"[t1_restricted_external] hydrate failed (non-fatal): {e}")
        return 0

    restored = 0
    for row in snapshot:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO real_t1_restricted (symbol, day, flagged_at, detail) VALUES (?, ?, ?, ?)",
                (row["symbol"], row["day"], row["flagged_at"], row.get("detail")),
            )
            restored += 1
        except (KeyError, TypeError, ValueError):
            continue
    if restored:
        conn.commit()
    return restored


def _flag_if_t1_restricted(conn, symbol: str, detail: str | None) -> None:
    """Records `symbol` as T1/T2T-restricted for today the first time its
    detail string carries either of Kotak's own same-day-sell rejection
    markers - see real_t1_restricted's own CREATE TABLE comment for the
    full reasoning, and _T2T_SAME_DAY_MARKER's own comment above for why
    there are two. Call this at every site that logs a real SL/exit
    rejection detail. Idempotent (day-scoped PRIMARY KEY, INSERT OR
    IGNORE) and never raises - a failure to flag must never break the
    real order flow it's observing."""
    if not detail or (_T1_HOLDINGS_MARKER not in detail and _T2T_SAME_DAY_MARKER not in detail):
        return
    today = ist_now().strftime("%Y-%m-%d")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO real_t1_restricted (symbol, day, flagged_at, detail) VALUES (?, ?, ?, ?)",
            (symbol, today, time.time(), detail),
        )
        conn.commit()
        _sync_t1_restricted_external(conn)
        print(f"[T1-restricted] {symbol} flagged for {today} - new real entries blocked permanently: {detail}")
    except Exception as e:
        print(f"[T1-restricted] failed to flag {symbol} (non-fatal): {e}")


def _is_t1_restricted(conn, symbol: str) -> bool:
    """True if `symbol` has EVER hit a T1-holdings or Trade-to-Trade (T2T)
    same-day-sell rejection, on any day - checked before any NEW real
    equity entry (see _maybe_place_real_entry). Equity-only: F&O
    positions aren't CNC holdings and carry no T1/T2T settlement
    restriction, so this is never checked on that path.

    PERMANENT, not day-scoped, as of 2026-09-09 (explicit user
    instruction: "if we can't exit same day then pick strategy
    accordingly... else dont pick these restricted assets" - a T2T/T1
    classification is a structural attribute of the STOCK ITSELF (its
    exchange trading segment), not a one-day fluke that clears overnight.
    Live finding the same day: MEDICAMEQ.NS and SILVERCASE.NS both hit
    this same wall, and the OLD day-scoped check meant tomorrow's
    scheduler would cheerfully re-enter the exact same T2T stock with
    real capital and get exactly the same rejection again - this
    strategy's whole design assumes a same-day exit is always possible,
    so a symbol that has ever proven otherwise is permanently
    incompatible with it, not just "restricted today." real_t1_restricted
    itself still records EACH day a rejection is newly confirmed (its own
    day-scoped PRIMARY KEY, unchanged - useful audit history), but this
    read now checks for ANY row ever, regardless of which day it was
    inserted on."""
    return conn.execute(
        "SELECT 1 FROM real_t1_restricted WHERE symbol = ?", (symbol,)
    ).fetchone() is not None


def _log_real_attempt(conn, symbol, side, status, kotak_trading_symbol=None, qty=None,
                       price_est=None, notional_inr=None, order_id=None, detail=None, raw_response=None):
    conn.execute(
        "INSERT INTO real_trades (ts, day, symbol, kotak_trading_symbol, side, qty, price_est, "
        "notional_inr, status, order_id, detail, raw_response) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (time.time(), ist_now().strftime("%Y-%m-%d"), symbol, kotak_trading_symbol, side, qty,
         price_est, notional_inr, status, order_id, detail,
         json.dumps(raw_response, default=str) if raw_response is not None else None),
    )
    conn.commit()


def _log_real_order_event(conn, symbol, leg, event, kotak_trading_symbol=None, order_id=None,
                           prev_state=None, new_state=None, detail=None):
    """Appends one row to the order state-transition log (real_order_events -
    see its own CREATE TABLE comment) - explicit user instruction
    2026-09-08: "I want to see the log of what order you have placed and
    from what prev state to what current new order state." Called
    alongside (never instead of) whatever else a call site already does
    (real_positions updates, _log_real_attempt for entry/exit) - this
    table's only job is a complete, human-readable, forever-kept history
    of every entry/exit/sl/target order-state change this app makes.
    Never raises on its own account - a plain INSERT/commit, same
    simplicity as _log_real_attempt above."""
    conn.execute(
        "INSERT INTO real_order_events (ts, symbol, kotak_trading_symbol, leg, event, order_id, "
        "prev_state, new_state, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (time.time(), symbol, kotak_trading_symbol, leg, event, order_id, prev_state, new_state, detail),
    )
    conn.commit()


def is_real_fo_trading_enabled() -> bool:
    """SEPARATE gate from is_real_trading_enabled (equity) - explicit
    user instruction 2026-09-07 ("i can update the capital any time. so
    build it right now"). Same single-env-var pattern is_real_trading_
    enabled itself settled on 2026-09-04 (a DB-row second switch was
    tried and found to be an invisible, un-manageable gate - see that
    function's own docstring) - REAL_FO_TRADING_ENABLED is a Render env
    var set manually there, independent of REAL_TRADING_ENABLED, so
    turning on equity real trading never silently turns on F&O too
    (much larger notional/margin per lot)."""
    return os.environ.get("REAL_FO_TRADING_ENABLED") == "YES"


def _real_fo_today_spent_inr(conn) -> float:
    """Sum of today's (IST calendar day) CONFIRMED real F&O buy notional
    (premium * qty for a bought option) - what real_fo_daily_cap_inr
    actually caps. Mirrors _real_today_spent_inr's own reasoning exactly,
    sourced from real_fo_trades (this codebase's own record, populated at
    order-attempt time), not from Kotak's own trade/order reports."""
    today = ist_now().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(notional_inr), 0) AS s FROM real_fo_trades "
        "WHERE day = ? AND side = 'B' AND status = 'confirmed'",
        (today,),
    ).fetchone()
    return float(row["s"] or 0.0)


def _log_real_fo_attempt(conn, leg_key, side, status, kotak_trading_symbol=None, qty=None,
                          price_est=None, notional_inr=None, order_id=None, detail=None, raw_response=None):
    conn.execute(
        "INSERT INTO real_fo_trades (ts, day, leg_key, kotak_trading_symbol, side, qty, price_est, "
        "notional_inr, status, order_id, detail, raw_response) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (time.time(), ist_now().strftime("%Y-%m-%d"), leg_key, kotak_trading_symbol, side, qty,
         price_est, notional_inr, status, order_id, detail,
         json.dumps(raw_response, default=str) if raw_response is not None else None),
    )
    conn.commit()


def _maybe_place_real_entry(conn, symbol: str):
    """Mirrors a paper "entered_long" as a REAL buy, ONLY when every gate
    holds. Called from _scheduler_loop right after _auto_signal_core
    returns action_taken == "entered_long" for an equity symbol - never
    from inside _auto_signal_core itself, so paper trading's own logic
    stays completely unaware of real trading. Never raises - any
    unexpected error here must not break the scheduler tick (see the
    try/except around this call site)."""
    if not is_real_trading_enabled(conn):
        return  # expected default state - not logged, this isn't an "attempt"

    asset_class, _, _ = _asset_class_and_source(symbol)
    if asset_class != "nse_equity":
        _log_real_attempt(conn, symbol, "B", "skipped_not_eligible_asset_class")
        return

    if conn.execute("SELECT 1 FROM real_positions WHERE symbol = ?", (symbol,)).fetchone():
        _log_real_attempt(conn, symbol, "B", "skipped_already_open")
        return

    if _is_t1_restricted(conn, symbol):
        _log_real_attempt(
            conn, symbol, "B", "skipped_t1_restricted",
            detail="permanently avoided - a real T1-holdings/T2T same-day-sell rejection was "
                   "confirmed for this symbol before, and this strategy needs a same-day exit "
                   "to be possible every time",
        )
        return

    import kotak_live_feed
    tick = kotak_live_feed.get_live_ticks().get(symbol)
    if not tick or not tick.get("ltp") or not tick.get("trading_symbol"):
        _log_real_attempt(conn, symbol, "B", "skipped_no_live_tick")
        return
    ltp = float(tick["ltp"])
    kotak_symbol = tick["trading_symbol"]
    if ltp <= 0:
        _log_real_attempt(conn, symbol, "B", "skipped_no_live_tick", kotak_trading_symbol=kotak_symbol)
        return

    # Real qty - explicit user instruction 2026-09-08: "Qty should be same
    # as you pick in render. No hard coding needed." The paper engine
    # (_auto_signal_core, same tick, same symbol) already sized this exact
    # signal and wrote its qty to signal_state - read that back rather
    # than inventing a separate real sizing formula, then cap it down (an
    # integer floor, NSE cash equities are whole-share-only) by whatever
    # real money actually allows: the remaining real_daily_cap_inr budget
    # AND the real account's own available capital. min() of the three -
    # never buy more than the paper signal called for, and never more
    # than real money can actually afford, whichever is smaller.
    paper_row = conn.execute(
        "SELECT qty, stop_loss, target FROM signal_state WHERE symbol = ? AND status = 'long'", (symbol,)
    ).fetchone()
    paper_qty = paper_row["qty"] if paper_row and paper_row["qty"] else 0
    remaining_cap_inr = get_runtime_setting(conn, "real_daily_cap_inr") - _real_today_spent_inr(conn)
    real_capital_for_sizing = get_scheduler_capital_inr()
    max_by_cap = math.floor(remaining_cap_inr / ltp) if ltp > 0 else 0
    max_by_capital = math.floor(real_capital_for_sizing / ltp) if ltp > 0 else 0
    qty = int(min(paper_qty, max_by_cap, max_by_capital))
    if qty <= 0:
        _log_real_attempt(
            conn, symbol, "B", "skipped_insufficient_real_qty", kotak_trading_symbol=kotak_symbol,
            price_est=ltp,
            detail=f"paper qty {paper_qty}, 1 share = Rs{ltp:.2f} - capped to 0 by "
                   f"remaining daily cap Rs{remaining_cap_inr:.2f} (max {max_by_cap}) "
                   f"and/or real capital Rs{real_capital_for_sizing:.2f} (max {max_by_capital})",
        )
        return

    # REAL daily loss cap - added 2026-09-07 ("when ur data had been in
    # sync with kotak then it would have seen the live trades and taken
    # the wise step for the 2% calculations"), 2026-09-08 (moved to the
    # shared _real_loss_budget - "keep it as a % of total money available
    # at the beginning of day. kotak balance" - a FIXED day-open capital
    # basis, joint with F&O, not a live-refreshing per-check figure). See
    # that function's own docstring/module comment for the full reasoning.
    # Fails CLOSED: an unknown real-P&L state refuses the entry rather
    # than trading blind.
    loss_check = _real_loss_budget(conn)
    if loss_check["real_pnl_today"] is None:
        _log_real_attempt(
            conn, symbol, "B", "skipped_real_pnl_unknown", kotak_trading_symbol=kotak_symbol,
            price_est=ltp, detail=loss_check["detail"],
        )
        return
    if not loss_check["ok"]:
        _log_real_attempt(
            conn, symbol, "B", "skipped_real_daily_loss_cap_hit", kotak_trading_symbol=kotak_symbol,
            price_est=ltp, detail=loss_check["detail"],
        )
        return

    import kotak_real_orders
    result = kotak_real_orders.place_real_entry(kotak_symbol, qty, ltp)
    if result.get("ok"):
        now = time.time()
        # Resync to Kotak's OWN confirmed fill data when available, not
        # the pre-trade estimate - explicit user instruction 2026-09-08:
        # "the exact buy or sell price vary due to gap in time of
        # execution... resync data ... to match all decision making based
        # on execution data." result["qty"]/["fill_price"] ARE the real
        # fldQty/avgPrc from Kotak's order_report when
        # fill_price_confirmed is True (see kotak_real_orders.
        # place_real_entry) - falls back to the requested qty/ltp estimate
        # only when Kotak hasn't reported a fill yet.
        real_qty = int(result["qty"])
        real_entry_price = result["fill_price"]
        conn.execute(
            "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
            "entry_order_id, opened_at, day) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, kotak_symbol, real_qty, real_entry_price, result["order_id"], now,
             ist_now().strftime("%Y-%m-%d")),
        )
        _log_real_attempt(
            conn, symbol, "B", "confirmed", kotak_trading_symbol=kotak_symbol,
            qty=real_qty, price_est=real_entry_price, notional_inr=real_qty * real_entry_price,
            order_id=result["order_id"], raw_response=result.get("raw_response"),
            detail=None if result["fill_price_confirmed"] else "fill not yet confirmed by Kotak - using requested qty/estimated LTP",
        )
        print(f"[REAL TRADE] BUY {real_qty} {kotak_symbol} (order {result['order_id']}) "
              f"~Rs{real_entry_price:.2f} (fill_confirmed={result['fill_price_confirmed']})")
        _log_real_order_event(
            conn, symbol, "entry", "confirmed", kotak_trading_symbol=kotak_symbol,
            order_id=result["order_id"], prev_state="no position",
            new_state=f"long {real_qty} @ Rs{real_entry_price:.2f}",
            detail=None if result["fill_price_confirmed"] else "fill not yet confirmed by Kotak",
        )
        _sync_real_positions_external(conn)

        # Real resting stop-loss (2026-09-07, explicit user instruction:
        # "share stop-loss/trailing-stop to Kotak") - the paper stop this
        # SAME tick's _auto_signal_core just computed and wrote to
        # signal_state is the only stop this real position has ever had;
        # mirror it to the broker immediately so it's protected even if
        # this app never runs another tick. Best-effort: a failed SL
        # placement is logged but does NOT undo the real entry above -
        # the position genuinely exists at Kotak either way, and
        # _maybe_sync_real_stop_loss retries placing it on every later
        # tick for as long as real_positions.sl_order_id stays NULL.
        if paper_row and paper_row["stop_loss"]:
            sl_result = kotak_real_orders.place_real_stop_loss(
                kotak_symbol, real_qty, round(paper_row["stop_loss"], 2)
            )
            if sl_result.get("ok"):
                conn.execute(
                    "UPDATE real_positions SET sl_order_id = ?, sl_trigger_price = ? WHERE symbol = ?",
                    (sl_result["order_id"], sl_result["trigger_price"], symbol),
                )
                print(f"[REAL TRADE] SL resting @ Rs{sl_result['trigger_price']:.2f} for {kotak_symbol} "
                      f"(order {sl_result['order_id']})")
                _log_real_order_event(
                    conn, symbol, "sl", "placed", kotak_trading_symbol=kotak_symbol,
                    order_id=sl_result["order_id"], prev_state="none",
                    new_state=f"resting SELL trigger Rs{sl_result['trigger_price']:.2f}",
                )
                _sync_real_positions_external(conn)
            else:
                print(f"[REAL TRADE] SL placement FAILED for {kotak_symbol}: {sl_result.get('detail')} "
                      f"- position open at Kotak with NO resting stop yet, will retry next tick")
                _log_real_order_event(
                    conn, symbol, "sl", "failed", kotak_trading_symbol=kotak_symbol,
                    prev_state="none", new_state="none (placement failed)", detail=sl_result.get("detail"),
                )
                _flag_if_t1_restricted(conn, symbol, sl_result.get("detail"))

        # Real resting target/profit-booking order (2026-09-08, explicit
        # user instruction: "place the target you have planned for each
        # trade so that it can be booked once reached") - same immediate-
        # mirror reasoning as the SL leg above, for the other side of the
        # trade. Best-effort like the SL placement: a failure is logged
        # but does not undo the real entry - see kotak_real_orders'
        # "Real resting target" docstring for why this one is NOT retried
        # on a later tick the way the SL is.
        if paper_row and paper_row["target"]:
            target_result = kotak_real_orders.place_real_target(
                kotak_symbol, real_qty, round(paper_row["target"], 2)
            )
            if target_result.get("ok"):
                conn.execute(
                    "UPDATE real_positions SET target_order_id = ?, target_price = ? WHERE symbol = ?",
                    (target_result["order_id"], target_result["target_price"], symbol),
                )
                print(f"[REAL TRADE] TARGET resting @ Rs{target_result['target_price']:.2f} for {kotak_symbol} "
                      f"(order {target_result['order_id']})")
                _log_real_order_event(
                    conn, symbol, "target", "placed", kotak_trading_symbol=kotak_symbol,
                    order_id=target_result["order_id"], prev_state="none",
                    new_state=f"resting SELL limit Rs{target_result['target_price']:.2f}",
                )
                _sync_real_positions_external(conn)
            else:
                print(f"[REAL TRADE] TARGET placement FAILED for {kotak_symbol}: {target_result.get('detail')} "
                      f"- position open at Kotak with NO resting target, profit-booking still handled by "
                      f"the scheduler's own per-tick poll instead")
                # Still record the INTENDED target price even though no real
                # order backs it (2026-09-09, explicit user instruction:
                # "Show me on render what is target for each entered trade")
                # - target_order_id stays null (honest: no real order is
                # resting), but target_price is no longer conflated with
                # "only ever set on a confirmed order" - the dashboard reads
                # target_status (target_order_id null + real_t1_restricted/
                # real_order_events lookup, see /real-open-positions) to
                # show WHY, right next to this number.
                conn.execute(
                    "UPDATE real_positions SET target_price = ? WHERE symbol = ?",
                    (round(paper_row["target"], 2), symbol),
                )
                _log_real_order_event(
                    conn, symbol, "target", "failed", kotak_trading_symbol=kotak_symbol,
                    prev_state="none", new_state="none (placement failed)", detail=target_result.get("detail"),
                )
                # Found live 2026-09-09 (MEDICAMEQ.NS): a plain limit SELL
                # target can get Kotak's own T1-holdings RMS rejection even
                # when the SL leg above (a contingent/trigger order) placed
                # fine for the very same same-day CNC position -
                # _flag_if_t1_restricted's own docstring says to call it at
                # every real SL/exit rejection site; this one was missing.
                _flag_if_t1_restricted(conn, symbol, target_result.get("detail"))
    else:
        _log_real_attempt(
            conn, symbol, "B", "failed", kotak_trading_symbol=kotak_symbol, price_est=ltp,
            detail=result.get("detail"), raw_response=result.get("raw_response"),
        )
        print(f"[REAL TRADE] BUY FAILED {kotak_symbol}: {result.get('detail')}")
        _log_real_order_event(
            conn, symbol, "entry", "failed", kotak_trading_symbol=kotak_symbol,
            prev_state="no position", new_state="no position (buy failed)", detail=result.get("detail"),
        )


def _kotak_symbol_still_open(kotak_trading_symbol: str) -> bool | None:
    """Ground-truth check against Kotak's OWN positions(), same query
    shape as get_real_capital_deployed_inr - added 2026-09-08 after a
    live-confirmed duplicate-exit finding (see _maybe_place_real_exit):
    a Render restart landing between a real exit order being CONFIRMED
    and its real_positions row's DELETE actually committing (SQLite,
    wiped on every restart like every other table here) restores that
    row from the last journal snapshot as if the position were still
    open - if a second exit attempt then fires off this stale state, it
    places a REAL duplicate sell with no legitimate open position behind
    it, drawing from whatever the account happens to hold in that symbol
    (confirmed live: this drew from a separate manually-purchased holding
    in the same symbol, not this app's own tracked shares - net position
    ended up flat by coincidence, not by design).

    Returns True if Kotak shows a genuinely open (not fully squared-off)
    position for this exact trading symbol, False if it shows none/fully
    squared off, or None on a fetch failure (fails OPEN - never used to
    silently swallow a legitimate exit over a transient API hiccup; see
    the caller)."""
    try:
        import kotak_neo
        positions = kotak_neo.positions()
        rows = positions.get("data") or [] if isinstance(positions, dict) else []
    except Exception:
        return None
    for row in rows:
        if row.get("trdSym") != kotak_trading_symbol or row.get("exSeg") != "nse_cm":
            continue
        try:
            fl_buy = float(row.get("flBuyQty", 0) or 0)
            fl_sell = float(row.get("flSellQty", 0) or 0)
        except (TypeError, ValueError):
            continue
        if fl_buy > 0 and fl_buy != fl_sell:
            return True
    return False


def _maybe_place_real_exit(conn, symbol: str):
    """Mirrors a paper exit (any exit_reason) as a REAL sell that closes
    the matching real_positions row, if one exists. Deliberately NOT
    gated by is_real_trading_enabled() - see kotak_real_orders.
    place_real_exit's docstring: closing an already-open real position
    must never be blocked by the same switch that gates new entries."""
    row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", (symbol,)).fetchone()
    if not row:
        return  # no real position was ever opened for this paper trade - nothing to close

    import kotak_real_orders

    # BUG found live 2026-09-08 (investigating a related duplicate-SL
    # question): this app's own real_positions row can survive a restart
    # that landed between "the exit already executed at Kotak" and "the
    # DELETE that would have removed this row actually committing" - see
    # _kotak_symbol_still_open's own docstring for the full mechanism.
    # Verify against Kotak's OWN positions() before placing a second real
    # sell for a position that may already be closed - None (fetch
    # failed) still proceeds, since refusing a genuinely-needed exit is
    # worse than risking a check that couldn't run.
    still_open = _kotak_symbol_still_open(row["kotak_trading_symbol"])
    if still_open is False:
        conn.execute("DELETE FROM real_positions WHERE symbol = ?", (symbol,))
        conn.commit()
        _sync_real_positions_external(conn)
        _log_real_attempt(
            conn, symbol, "S", "skipped_already_closed_at_kotak", kotak_trading_symbol=row["kotak_trading_symbol"],
            qty=row["qty"],
            detail="Kotak shows no open position for this symbol - stale real_positions row "
                   "(likely a restart-interrupted DELETE from an earlier exit) cleared without a second sell",
        )
        print(f"[REAL TRADE] SKIPPED duplicate exit for {row['kotak_trading_symbol']} - "
              f"Kotak already shows it closed, stale local row cleared instead of re-selling")
        _log_real_order_event(
            conn, symbol, "exit", "skipped_duplicate", kotak_trading_symbol=row["kotak_trading_symbol"],
            prev_state=f"tracked open (stale), long {row['qty']} @ Rs{row['entry_price']:.2f}",
            new_state="cleared - Kotak already shows this closed",
        )
        return
    # Cancel the resting real stop-loss FIRST (if one was ever placed) -
    # best-effort, never blocks the exit below even if the cancel fails
    # (e.g. the SL already fired, which is itself a valid reason
    # real_positions still shows this row - see the reconcile endpoint).
    # Left behind uncancelled, a stale SL sell order with nothing left
    # to sell once this exit fills would just sit as a harmless rejected
    # order at Kotak, not a real risk - but cancelling first keeps the
    # order book clean and avoids that rejection noise.
    if row["sl_order_id"]:
        cancel_result = kotak_real_orders.cancel_real_order(row["sl_order_id"])
        if cancel_result.get("ok"):
            _log_real_order_event(
                conn, symbol, "sl", "cancelled", kotak_trading_symbol=row["kotak_trading_symbol"],
                order_id=row["sl_order_id"], prev_state=f"resting @ Rs{row['sl_trigger_price']}",
                new_state="cancelled (position exiting)",
            )
        else:
            print(f"[REAL TRADE] SL cancel failed for {row['kotak_trading_symbol']} "
                  f"(order {row['sl_order_id']}): {cancel_result.get('detail')} - proceeding with exit anyway")
            _log_real_order_event(
                conn, symbol, "sl", "cancel_failed", kotak_trading_symbol=row["kotak_trading_symbol"],
                order_id=row["sl_order_id"], prev_state=f"resting @ Rs{row['sl_trigger_price']}",
                new_state="cancel failed - may still be resting", detail=cancel_result.get("detail"),
            )
    # Same reasoning, for the other resting leg (2026-09-08): whichever of
    # SL/target actually triggered this exit, the OTHER one is still
    # resting at Kotak with nothing left to sell once this order fills -
    # cancel it too, best-effort, before placing the exit itself.
    if row["target_order_id"]:
        cancel_result = kotak_real_orders.cancel_real_order(row["target_order_id"])
        if cancel_result.get("ok"):
            _log_real_order_event(
                conn, symbol, "target", "cancelled", kotak_trading_symbol=row["kotak_trading_symbol"],
                order_id=row["target_order_id"], prev_state=f"resting @ Rs{row['target_price']}",
                new_state="cancelled (position exiting)",
            )
        else:
            print(f"[REAL TRADE] target cancel failed for {row['kotak_trading_symbol']} "
                  f"(order {row['target_order_id']}): {cancel_result.get('detail')} - proceeding with exit anyway")
            _log_real_order_event(
                conn, symbol, "target", "cancel_failed", kotak_trading_symbol=row["kotak_trading_symbol"],
                order_id=row["target_order_id"], prev_state=f"resting @ Rs{row['target_price']}",
                new_state="cancel failed - may still be resting", detail=cancel_result.get("detail"),
            )

    result = kotak_real_orders.place_real_exit(row["kotak_trading_symbol"], row["qty"])
    if result.get("ok"):
        conn.execute("DELETE FROM real_positions WHERE symbol = ?", (symbol,))
        # Resync to Kotak's own confirmed fill data for the audit log, same
        # reasoning as the entry side (explicit user instruction 2026-09-08)
        # - fill_price is the real avgPrc when confirmed, else None (the
        # real P&L figure this app displays/gates on is sourced separately,
        # straight from Kotak's own positions() aggregation - see
        # get_real_pnl_today_inr - so this is a logging-accuracy fix, not a
        # P&L-correctness one).
        exit_qty = int(result["qty"])
        _log_real_attempt(
            conn, symbol, "S", "confirmed", kotak_trading_symbol=row["kotak_trading_symbol"],
            qty=exit_qty, price_est=result.get("fill_price"),
            notional_inr=exit_qty * result["fill_price"] if result.get("fill_price") else None,
            order_id=result["order_id"], raw_response=result.get("raw_response"),
            detail=None if result["fill_price_confirmed"] else "fill not yet confirmed by Kotak",
        )
        _sync_real_positions_external(conn)
        print(f"[REAL TRADE] SELL {exit_qty} {row['kotak_trading_symbol']} (order {result['order_id']}) "
              f"(fill_confirmed={result['fill_price_confirmed']})")
        _log_real_order_event(
            conn, symbol, "exit", "confirmed", kotak_trading_symbol=row["kotak_trading_symbol"],
            order_id=result["order_id"],
            prev_state=f"long {row['qty']} @ Rs{row['entry_price']:.2f}",
            new_state=f"closed, {exit_qty} @ Rs{result.get('fill_price') or 0:.2f}",
            detail=None if result["fill_price_confirmed"] else "fill not yet confirmed by Kotak",
        )
    else:
        # The dangerous failure mode: a real position we believe is open
        # and TRIED to close, but couldn't confirm. Left in real_positions
        # deliberately (never guess it closed) - surfaces via
        # GET /kotak-neo/real-positions until a human/retry resolves it.
        _log_real_attempt(
            conn, symbol, "S", "failed", kotak_trading_symbol=row["kotak_trading_symbol"],
            qty=row["qty"], detail=result.get("detail"), raw_response=result.get("raw_response"),
        )
        print(f"[REAL TRADE] SELL FAILED {row['kotak_trading_symbol']}: {result.get('detail')} - POSITION STILL OPEN, NEEDS ATTENTION")
        _log_real_order_event(
            conn, symbol, "exit", "failed", kotak_trading_symbol=row["kotak_trading_symbol"],
            prev_state=f"long {row['qty']} @ Rs{row['entry_price']:.2f}",
            new_state="still open - exit attempt failed", detail=result.get("detail"),
        )
        _flag_if_t1_restricted(conn, symbol, result.get("detail"))


def _maybe_sync_real_stop_loss(conn, symbol: str):
    """Keeps a real position's RESTING stop-loss order at Kotak in step
    with the paper trailing stop _auto_signal_core just ratcheted (see
    the `current_stop = trail_candidate` branch there) - explicit user
    instruction 2026-09-07 ("update stop-loss to Kotak on trigger").
    Called every tick for every symbol (cheap: one SELECT when there's no
    real position for it), right after the entry/exit mirroring above -
    deliberately NOT called from inside _auto_signal_core itself, same
    isolation principle as _maybe_place_real_entry/_exit.

    Only ever moves the resting stop UP (mirrors the paper trail, which
    itself never ratchets down - see _auto_signal_core) and only replaces
    it when the paper stop has actually moved since the last sync, so a
    held position isn't cancel/replaced every single tick for no reason.
    If no SL is resting yet (an earlier placement failed), this also
    retries placing it fresh at the paper stop's current level - see
    _maybe_place_real_entry's own comment on that retry path."""
    real_row = conn.execute("SELECT * FROM real_positions WHERE symbol = ?", (symbol,)).fetchone()
    if not real_row:
        return

    paper_row = conn.execute(
        "SELECT stop_loss FROM signal_state WHERE symbol = ? AND status = 'long'", (symbol,)
    ).fetchone()
    if not paper_row or not paper_row["stop_loss"]:
        return
    new_stop = round(paper_row["stop_loss"], 2)
    current_sl_price = real_row["sl_trigger_price"]

    if current_sl_price is not None and new_stop <= current_sl_price:
        return  # no upward move since the last sync - nothing to do

    import kotak_real_orders
    if real_row["sl_order_id"]:
        cancel_result = kotak_real_orders.cancel_real_order(real_row["sl_order_id"])
        if not cancel_result.get("ok"):
            print(f"[REAL TRADE] trailing-SL cancel failed for {real_row['kotak_trading_symbol']} "
                  f"(order {real_row['sl_order_id']}): {cancel_result.get('detail')} - skipping this sync, will retry next tick")
            return  # don't place a second resting SL on top of one that might still be live
    else:
        # BUG found live 2026-09-08 (explicit user finding, screenshot):
        # TWO live resting SL orders for the same 1-share AGL position,
        # same trigger/limit price, 11 minutes apart. sl_order_id is NULL
        # here for one of two reasons: no SL was ever placed yet (nothing
        # to cancel, genuinely fine), OR - the actual bug - a Render
        # restart landed between an earlier SL placement and the next
        # journal-sync snapshot capturing its order id (real_positions is
        # SQLite, wiped on every restart like every other table, only as
        # fresh as the last snapshot), restoring this position with
        # sl_order_id back to NULL even though a real order was already
        # resting at Kotak. Sweep the broker's OWN order book first (the
        # only ground truth this app's stale/lost tracking can't corrupt)
        # so a leftover live SL is cancelled before a fresh one is placed,
        # instead of accumulating a silent duplicate every time this
        # exact race recurs.
        kotak_real_orders.cancel_existing_resting_sl(real_row["kotak_trading_symbol"])

    sl_result = kotak_real_orders.place_real_stop_loss(real_row["kotak_trading_symbol"], real_row["qty"], new_stop)
    if sl_result.get("ok"):
        conn.execute(
            "UPDATE real_positions SET sl_order_id = ?, sl_trigger_price = ? WHERE symbol = ?",
            (sl_result["order_id"], sl_result["trigger_price"], symbol),
        )
        conn.commit()
        _sync_real_positions_external(conn)
        print(f"[REAL TRADE] trailing SL moved to Rs{new_stop:.2f} for {real_row['kotak_trading_symbol']} "
              f"(order {sl_result['order_id']})")
        _log_real_order_event(
            conn, symbol, "sl", "moved", kotak_trading_symbol=real_row["kotak_trading_symbol"],
            order_id=sl_result["order_id"],
            prev_state=f"Rs{current_sl_price:.2f}" if current_sl_price is not None else "none",
            new_state=f"Rs{new_stop:.2f}",
        )
    else:
        # Old order is already cancelled (or never existed) and the
        # replacement failed - clear sl_order_id so the position isn't
        # left pointing at a dead order id; next tick's retry path
        # (sl_order_id NULL) will try placing a fresh one again.
        conn.execute("UPDATE real_positions SET sl_order_id = NULL WHERE symbol = ?", (symbol,))
        conn.commit()
        _sync_real_positions_external(conn)
        print(f"[REAL TRADE] trailing SL replacement FAILED for {real_row['kotak_trading_symbol']}: "
              f"{sl_result.get('detail')} - position open at Kotak with NO resting stop, will retry next tick")
        _log_real_order_event(
            conn, symbol, "sl", "failed", kotak_trading_symbol=real_row["kotak_trading_symbol"],
            prev_state=f"Rs{current_sl_price:.2f}" if current_sl_price is not None else "none",
            new_state="none (replacement failed)", detail=sl_result.get("detail"),
        )
        _flag_if_t1_restricted(conn, symbol, sl_result.get("detail"))


# --- Real F&O trading (2026-09-07) -------------------------------------------
# Explicit user instruction: "i can update the capital any time. so build it
# right now" (real F&O order placement) + "there are strategies where put and
# call are together less than half of total cost too" (Long Straddle - see
# nse_straddle_state's own table comment). Two strategies wired here:
#   1. Single-leg real CALL, mirroring the ALREADY-EVIDENCED bullish ORB-
#      breakout signal WATCHLIST's own comment cites for NIFTY/BANKNIFTY
#      ("real 60-day backtest evidence behind this exact strategy") - same
#      "mirror a paper decision, invent nothing new" principle as equity
#      real trading. No symmetric real PUT exists - the equity engine is
#      long-only, so there is no evidenced bearish entry to mirror.
#   2. Long Straddle - a genuinely NEW, NOT YET BACKTESTED strategy, paper-
#      tracked unconditionally, real-mirrored only behind its own explicit
#      opt-in (real_straddle_enabled runtime setting, default OFF).
# Both share is_real_fo_trading_enabled()/real_fo_daily_cap_inr as their
# gate/cap - SEPARATE from equity's real_trading_control/real_daily_cap_inr.
#
# MCX entries (2026-09-07, explicit user instruction "also mcx") map to
# the MINI contract's pSymbolName (GOLDM/SILVERM/CRUDEOILM), not the
# full-size one (GOLD/SILVER/CRUDEOIL) WATCHLIST's own comment/
# kotak_live_feed.py use for price-proxy futures - the full-size contract
# has no options chain at all (confirmed live 2026-09-07, see
# nse_fo_chain.py's docstring). Mini is also the right size for a small
# account regardless.
_INDEX_TO_FO_UNDERLYING = {
    "^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY",
    "GC=F": "GOLDM", "SI=F": "SILVERM", "CL=F": "CRUDEOILM",
}


def _maybe_place_real_fo_call_entry(conn, symbol: str, spot: float):
    """Mirrors a paper long (index OR MCX commodity, entered_long) as a
    REAL long call on the matching F&O underlying, sized at exactly 1 lot
    (smallest tradeable unit - same "qty=1" first-version precedent
    kotak_real_orders.py set for equity). Never raises."""
    if not is_real_fo_trading_enabled():
        return
    fo_underlying = _INDEX_TO_FO_UNDERLYING.get(symbol)
    if fo_underlying is None:
        return
    leg_key = f"{fo_underlying}:CALL"
    if conn.execute("SELECT 1 FROM real_fo_positions WHERE leg_key = ?", (leg_key,)).fetchone():
        _log_real_fo_attempt(conn, leg_key, "B", "skipped_already_open")
        return

    import nse_fo_chain
    contract, err = nse_fo_chain.select_nse_option_contract(fo_underlying, spot, "call")
    if contract is None:
        _log_real_fo_attempt(conn, leg_key, "B", "skipped_no_contract", detail=err)
        return

    qty = contract["lot_size"]
    notional_inr = qty * contract["premium"]  # every F&O underlying wired here is INR-native, no fx conversion
    remaining = get_runtime_setting(conn, "real_fo_daily_cap_inr") - _real_fo_today_spent_inr(conn)
    if notional_inr > remaining:
        _log_real_fo_attempt(
            conn, leg_key, "B", "skipped_over_daily_cap", kotak_trading_symbol=contract["kotak_trading_symbol"],
            price_est=contract["premium"], qty=qty,
            detail=f"1 lot = Rs{notional_inr:.2f}, remaining budget Rs{remaining:.2f}",
        )
        return

    # Joint real daily-loss cap (2026-09-08, explicit user instruction:
    # "joint cap... keep it as a % of total money available at the
    # beginning of day") - see _real_loss_budget's own docstring. Same
    # gate equity's _maybe_place_real_entry already enforces; this was
    # the missing half that made it not actually joint before.
    loss_check = _real_loss_budget(conn)
    if loss_check["real_pnl_today"] is None:
        _log_real_fo_attempt(conn, leg_key, "B", "skipped_real_pnl_unknown",
                              kotak_trading_symbol=contract["kotak_trading_symbol"],
                              price_est=contract["premium"], qty=qty, detail=loss_check["detail"])
        return
    if not loss_check["ok"]:
        _log_real_fo_attempt(conn, leg_key, "B", "skipped_real_daily_loss_cap_hit",
                              kotak_trading_symbol=contract["kotak_trading_symbol"],
                              price_est=contract["premium"], qty=qty, detail=loss_check["detail"])
        return

    import kotak_real_fo_orders
    margin_check = kotak_real_fo_orders.check_margin_affordable(
        exchange_segment=contract["exchange_segment"], instrument_token=contract["instrument_token"],
        transaction_type="B", quantity=qty,
    )
    if not margin_check["ok"]:
        _log_real_fo_attempt(
            conn, leg_key, "B", "skipped_margin_unaffordable", kotak_trading_symbol=contract["kotak_trading_symbol"],
            price_est=contract["premium"], qty=qty, detail=margin_check["detail"],
            raw_response=margin_check.get("raw_response"),
        )
        return

    result = kotak_real_fo_orders.place_real_fo_entry(
        contract["kotak_trading_symbol"], contract["exchange_segment"], qty,
    )
    if result.get("ok"):
        conn.execute(
            "INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, "
            "instrument_token, exchange_segment, expiry, strike, lot_size, qty, entry_price, entry_order_id, "
            "opened_at, day) VALUES (?, ?, 'single_leg_call', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (leg_key, fo_underlying, contract["kotak_trading_symbol"], contract["instrument_token"],
             contract["exchange_segment"], contract["expiry"], contract["strike"], contract["lot_size"], qty,
             contract["premium"], result["order_id"], time.time(), ist_now().strftime("%Y-%m-%d")),
        )
        _log_real_fo_attempt(
            conn, leg_key, "B", "confirmed", kotak_trading_symbol=contract["kotak_trading_symbol"],
            qty=qty, price_est=contract["premium"], notional_inr=notional_inr,
            order_id=result["order_id"], raw_response=result.get("raw_response"),
        )
        print(f"[REAL F&O] BUY CALL {qty} {contract['kotak_trading_symbol']} (order {result['order_id']}) "
              f"~Rs{contract['premium']:.2f}")
    else:
        _log_real_fo_attempt(
            conn, leg_key, "B", "failed", kotak_trading_symbol=contract["kotak_trading_symbol"],
            qty=qty, price_est=contract["premium"], detail=result.get("detail"), raw_response=result.get("raw_response"),
        )
        print(f"[REAL F&O] BUY CALL FAILED {contract['kotak_trading_symbol']}: {result.get('detail')}")


def _maybe_place_real_fo_call_exit(conn, symbol: str):
    """Closes the real call leg _maybe_place_real_fo_call_entry opened,
    when the SAME underlying's paper index position exits (any reason).
    No gate of its own - same reasoning as _maybe_place_real_exit:
    closing an already-open position must never be blocked."""
    fo_underlying = _INDEX_TO_FO_UNDERLYING.get(symbol)
    if fo_underlying is None:
        return
    leg_key = f"{fo_underlying}:CALL"
    row = conn.execute("SELECT * FROM real_fo_positions WHERE leg_key = ?", (leg_key,)).fetchone()
    if not row:
        return

    import kotak_real_fo_orders
    result = kotak_real_fo_orders.place_real_fo_exit(row["kotak_trading_symbol"], row["exchange_segment"], row["qty"])
    if result.get("ok"):
        conn.execute("DELETE FROM real_fo_positions WHERE leg_key = ?", (leg_key,))
        _log_real_fo_attempt(
            conn, leg_key, "S", "confirmed", kotak_trading_symbol=row["kotak_trading_symbol"],
            qty=row["qty"], order_id=result["order_id"], raw_response=result.get("raw_response"),
        )
        print(f"[REAL F&O] SELL CALL {row['qty']} {row['kotak_trading_symbol']} (order {result['order_id']})")
    else:
        _log_real_fo_attempt(
            conn, leg_key, "S", "failed", kotak_trading_symbol=row["kotak_trading_symbol"],
            qty=row["qty"], detail=result.get("detail"), raw_response=result.get("raw_response"),
        )
        print(f"[REAL F&O] SELL CALL FAILED {row['kotak_trading_symbol']}: {result.get('detail')} "
              f"- POSITION STILL OPEN, NEEDS ATTENTION")


STRADDLE_STOP_PCT = 40.0    # combined-premium stop, % below entry combined premium
STRADDLE_TARGET_RR = 1.5    # combined-premium target, multiple of the stop distance


def _close_real_straddle_legs(conn, fo_underlying: str):
    """Closes both real straddle legs (whichever are actually open - a
    failed entry earlier may have left only one). No gate - closing must
    never be blocked, same principle as every other real-money exit."""
    import kotak_real_fo_orders
    for right in ("CE", "PE"):
        leg_key = f"{fo_underlying}:STRADDLE-{right}"
        row = conn.execute("SELECT * FROM real_fo_positions WHERE leg_key = ?", (leg_key,)).fetchone()
        if not row:
            continue
        result = kotak_real_fo_orders.place_real_fo_exit(row["kotak_trading_symbol"], row["exchange_segment"], row["qty"])
        if result.get("ok"):
            conn.execute("DELETE FROM real_fo_positions WHERE leg_key = ?", (leg_key,))
            _log_real_fo_attempt(
                conn, leg_key, "S", "confirmed", kotak_trading_symbol=row["kotak_trading_symbol"],
                qty=row["qty"], order_id=result["order_id"], raw_response=result.get("raw_response"),
            )
            print(f"[REAL F&O] SELL STRADDLE-{right} {row['qty']} {row['kotak_trading_symbol']} (order {result['order_id']})")
        else:
            _log_real_fo_attempt(
                conn, leg_key, "S", "failed", kotak_trading_symbol=row["kotak_trading_symbol"],
                qty=row["qty"], detail=result.get("detail"), raw_response=result.get("raw_response"),
            )
            print(f"[REAL F&O] SELL STRADDLE-{right} FAILED {row['kotak_trading_symbol']}: {result.get('detail')} "
                  f"- POSITION STILL OPEN, NEEDS ATTENTION")


def _straddle_signal_core(conn, fo_underlying: str, vol_signal, halted: bool, is_squareoff_time: bool, spot):
    """Long Straddle (docs/STRATEGY_LOG.md row #3) - NOT YET BACKTESTED.
    Paper-tracks unconditionally (nse_straddle_state); real order
    mirroring only when is_real_fo_trading_enabled() AND the
    real_straddle_enabled runtime setting are BOTH on. Called every
    scheduler tick for NIFTY/BANKNIFTY, independent of the directional
    single-leg call mirror above - manages any open straddle first (never
    also opens a new one the same tick), else checks for a fresh entry."""
    import nse_fo_chain
    today_str = ist_now().strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM nse_straddle_state WHERE underlying = ?", (fo_underlying,)).fetchone()

    if row:
        call_c, _ = nse_fo_chain.select_nse_option_contract(fo_underlying, spot, "call") if spot else (None, None)
        put_c, _ = nse_fo_chain.select_nse_option_contract(fo_underlying, spot, "put") if spot else (None, None)
        # Only trust a requote when it's the SAME contract already held -
        # spot moving far enough can shift the "ATM" search to a different
        # strike; mark-to-market against the wrong contract would be worse
        # than falling back to the flat entry premium (never guessed).
        call_premium = call_c["premium"] if call_c and call_c["strike"] == row["strike"] else None
        put_premium = put_c["premium"] if put_c and put_c["strike"] == row["strike"] else None
        combined_now = (call_premium + put_premium) if (call_premium is not None and put_premium is not None) else None
        combined_entry = row["call_entry_premium"] + row["put_entry_premium"]

        dte_left = (dt.datetime.strptime(row["expiry"], "%Y-%m-%d") - dt.datetime.utcnow()).days
        exit_reason = None
        if halted:
            exit_reason = "daily_loss_cap_hit"
        elif dte_left <= 0:
            exit_reason = "expiry_reached"
        elif is_squareoff_time:
            exit_reason = "eod_squareoff"
        elif combined_now is not None:
            stop_dist = combined_entry * STRADDLE_STOP_PCT / 100
            if combined_now <= combined_entry - stop_dist:
                exit_reason = "stop_hit"
            elif combined_now >= combined_entry + STRADDLE_TARGET_RR * stop_dist:
                exit_reason = "target_hit"

        if exit_reason:
            exit_call = call_premium if call_premium is not None else row["call_entry_premium"]
            exit_put = put_premium if put_premium is not None else row["put_entry_premium"]
            fx, qty = row["fx_to_inr"], row["qty"]
            total_pnl_inr = 0.0
            for right, exit_p, entry_p in (("CE", exit_call, row["call_entry_premium"]),
                                            ("PE", exit_put, row["put_entry_premium"])):
                pnl_inr = (exit_p - entry_p) * qty * fx
                total_pnl_inr += pnl_inr
                opt_symbol = f"{fo_underlying}:STRADDLE-{right}"
                payload = {
                    "symbol": opt_symbol, "underlying": fo_underlying, "right": right, "action": "sell",
                    "qty": qty, "price": exit_p, "currency": "INR", "fx_to_inr": fx,
                    "strategy": "long_straddle", "exit_reason": exit_reason,
                    "entry_price": entry_p, "pnl_inr": round(pnl_inr, 2),
                }
                apply_paper_trade(conn, opt_symbol, "sell", qty, exit_p)
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'sell', ?, ?, ?, 'long_straddle', ?)",
                    (time.time(), opt_symbol, qty, exit_p, fx, json.dumps(payload)),
                )
            conn.execute("DELETE FROM nse_straddle_state WHERE underlying = ?", (fo_underlying,))
            conn.commit()
            print(f"[STRADDLE] paper exit {fo_underlying} ({exit_reason}) combined pnl Rs{round(total_pnl_inr, 2)}")
            _close_real_straddle_legs(conn, fo_underlying)  # unconditional - closing is never gated
        return  # managed (or held) this tick - never also check for a new entry the same tick

    # ---- no straddle open - check for a fresh entry ----
    if halted or is_squareoff_time or not vol_signal or spot is None:
        return
    # Once per day per underlying - STRATEGY_LOG's own "not yet
    # backtested" caution argues for the conservative read here.
    if conn.execute(
        "SELECT 1 FROM trades WHERE symbol = ? AND strategy = 'long_straddle' AND ts >= ?",
        (f"{fo_underlying}:STRADDLE-CE", ist_midnight_epoch(ist_now())),
    ).fetchone():
        return

    call_c, _ = nse_fo_chain.select_nse_option_contract(fo_underlying, spot, "call")
    put_c, _ = nse_fo_chain.select_nse_option_contract(fo_underlying, spot, "put")
    if call_c is None or put_c is None or call_c["strike"] != put_c["strike"] or call_c["expiry"] != put_c["expiry"]:
        return  # no matching ATM pair this tick - never force a mismatched strike/expiry pair

    qty = call_c["lot_size"]
    fx = 1.0  # every underlying wired to this strategy (NSE index, MCX commodity) is INR-native
    conn.execute(
        "INSERT INTO nse_straddle_state (underlying, day, expiry, strike, lot_size, qty, "
        "call_entry_premium, put_entry_premium, call_kotak_symbol, put_kotak_symbol, "
        "call_instrument_token, put_instrument_token, entry_ts, fx_to_inr) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fo_underlying, today_str, call_c["expiry"], call_c["strike"], call_c["lot_size"], qty,
         call_c["premium"], put_c["premium"], call_c["kotak_trading_symbol"], put_c["kotak_trading_symbol"],
         call_c["instrument_token"], put_c["instrument_token"], time.time(), fx),
    )
    for right, c in (("CE", call_c), ("PE", put_c)):
        opt_symbol = f"{fo_underlying}:STRADDLE-{right}"
        payload = {
            "symbol": opt_symbol, "underlying": fo_underlying, "right": right, "action": "buy",
            "qty": qty, "price": c["premium"], "currency": "INR", "fx_to_inr": fx,
            "strategy": "long_straddle", "entry_reason": "vol_contraction_signal",
            "strike": c["strike"], "expiry": c["expiry"],
        }
        apply_paper_trade(conn, opt_symbol, "buy", qty, c["premium"])
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'buy', ?, ?, ?, 'long_straddle', ?)",
            (time.time(), opt_symbol, qty, c["premium"], fx, json.dumps(payload)),
        )
    conn.commit()
    print(f"[STRADDLE] paper entry {fo_underlying} strike {call_c['strike']} exp {call_c['expiry']} "
          f"call Rs{call_c['premium']:.2f} put Rs{put_c['premium']:.2f}")

    if not is_real_fo_trading_enabled() or get_runtime_setting(conn, "real_straddle_enabled") < 0.5:
        return

    import kotak_real_fo_orders
    combined_notional = qty * (call_c["premium"] + put_c["premium"])
    remaining = get_runtime_setting(conn, "real_fo_daily_cap_inr") - _real_fo_today_spent_inr(conn)
    if combined_notional > remaining:
        for right, c in (("CE", call_c), ("PE", put_c)):
            _log_real_fo_attempt(
                conn, f"{fo_underlying}:STRADDLE-{right}", "B", "skipped_over_daily_cap",
                kotak_trading_symbol=c["kotak_trading_symbol"], price_est=c["premium"], qty=qty,
                detail=f"combined 2-leg cost Rs{combined_notional:.2f}, remaining budget Rs{remaining:.2f}",
            )
        return

    # Joint real daily-loss cap (2026-09-08) - see _real_loss_budget's own
    # docstring; same gate equity and the single-leg F&O entry both
    # enforce, applied here for the same "never place one leg alone"
    # reasoning as the margin check below.
    loss_check = _real_loss_budget(conn)
    if not loss_check["ok"]:
        status = "skipped_real_pnl_unknown" if loss_check["real_pnl_today"] is None else "skipped_real_daily_loss_cap_hit"
        for right, c in (("CE", call_c), ("PE", put_c)):
            _log_real_fo_attempt(
                conn, f"{fo_underlying}:STRADDLE-{right}", "B", status,
                kotak_trading_symbol=c["kotak_trading_symbol"], price_est=c["premium"], qty=qty,
                detail=loss_check["detail"],
            )
        return

    call_margin = kotak_real_fo_orders.check_margin_affordable(
        call_c["exchange_segment"], call_c["instrument_token"], "B", qty)
    put_margin = kotak_real_fo_orders.check_margin_affordable(
        put_c["exchange_segment"], put_c["instrument_token"], "B", qty)
    if not (call_margin["ok"] and put_margin["ok"]):
        # Never place one leg alone - a naked single leg was not the
        # signal that fired.
        for right, c, m in (("CE", call_c, call_margin), ("PE", put_c, put_margin)):
            _log_real_fo_attempt(
                conn, f"{fo_underlying}:STRADDLE-{right}", "B", "skipped_only_one_leg_affordable",
                kotak_trading_symbol=c["kotak_trading_symbol"], price_est=c["premium"], qty=qty,
                detail=m["detail"], raw_response=m.get("raw_response"),
            )
        return

    for right, c in (("CE", call_c), ("PE", put_c)):
        result = kotak_real_fo_orders.place_real_fo_entry(c["kotak_trading_symbol"], c["exchange_segment"], qty)
        leg_key = f"{fo_underlying}:STRADDLE-{right}"
        if result.get("ok"):
            conn.execute(
                "INSERT INTO real_fo_positions (leg_key, underlying, strategy_tag, kotak_trading_symbol, "
                "instrument_token, exchange_segment, expiry, strike, lot_size, qty, entry_price, entry_order_id, "
                "opened_at, day) VALUES (?, ?, 'long_straddle', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (leg_key, fo_underlying, c["kotak_trading_symbol"], c["instrument_token"], c["exchange_segment"],
                 c["expiry"], c["strike"], c["lot_size"], qty, c["premium"], result["order_id"],
                 time.time(), today_str),
            )
            _log_real_fo_attempt(
                conn, leg_key, "B", "confirmed", kotak_trading_symbol=c["kotak_trading_symbol"],
                qty=qty, price_est=c["premium"], notional_inr=qty * c["premium"],
                order_id=result["order_id"], raw_response=result.get("raw_response"),
            )
            print(f"[REAL F&O] BUY STRADDLE-{right} {qty} {c['kotak_trading_symbol']} (order {result['order_id']})")
        else:
            _log_real_fo_attempt(
                conn, leg_key, "B", "failed", kotak_trading_symbol=c["kotak_trading_symbol"],
                qty=qty, price_est=c["premium"], detail=result.get("detail"), raw_response=result.get("raw_response"),
            )
            print(f"[REAL F&O] BUY STRADDLE-{right} FAILED {c['kotak_trading_symbol']}: {result.get('detail')} "
                  f"- OTHER LEG MAY ALREADY BE OPEN, NEEDS ATTENTION")


def _force_close_all_positions(conn, reason: str) -> dict:
    """The kill switch's actual work: exits EVERY open position - paper
    equity, paper options, AND real Kotak positions (added 2026-09-07) -
    right now, at the best available current price, regardless of where
    price sits versus stop/target. Deliberately standalone from the
    normal tick-based exit code in _auto_signal_core/_options_signal_core -
    an emergency-stop action should never share a code path with (and risk
    being broken by some future change to) the everyday exit logic that
    protects every other open position."""
    watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in WATCHLIST}
    closed = []
    total_pnl_inr = 0.0
    live_rr = get_runtime_setting(conn, "rr")  # for the rr_target field below, live not static

    for row in conn.execute("SELECT * FROM signal_state WHERE status = 'long'").fetchall():
        symbol = row["symbol"]
        cfg = watchlist_by_symbol.get(symbol, {})
        interval = row["interval"] or "5m"
        try:
            df = fetch_ohlc(symbol, "5d", interval)
            exit_price = float(df["Close"].iloc[-1])
        except Exception:
            exit_price = row["entry_price"]  # never let a data hiccup block a kill

        strategy = cfg.get("strategy", "orb_breakout")
        strategy_tag = (
            f"{ORB_STRATEGY_PREFIX}{cfg.get('orb_minutes', 15)}m-sma{cfg.get('sma_fast', 9)}-{cfg.get('sma_slow', 21)}"
            if strategy == "orb_breakout"
            else f"{ORB_STRATEGY_PREFIX}bullish-engulfing-trend{cfg.get('trend_sma', 0)}"
        )
        qty = row["qty"]
        entry_fx = row["fx_to_inr"]
        pnl_native = (exit_price - row["entry_price"]) * qty
        pnl_inr = pnl_native * entry_fx
        stop_dist = row["entry_price"] - row["stop_loss"]
        rr_achieved = round((exit_price - row["entry_price"]) / stop_dist, 2) if stop_dist else None
        payload = {
            "symbol": symbol, "action": "sell", "qty": qty, "price": exit_price,
            "currency": cfg.get("currency", "INR"), "fx_to_inr": entry_fx,
            "strategy": strategy_tag, "exit_reason": reason,
            "entry_price": row["entry_price"], "stop_loss": row["stop_loss"], "target": row["target"],
            "rr_target": live_rr, "rr_achieved": rr_achieved,
            "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
        }
        apply_paper_trade(conn, symbol, "sell", qty, exit_price)
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
            (time.time(), symbol, qty, exit_price, entry_fx, strategy_tag, json.dumps(payload)),
        )
        conn.execute("DELETE FROM signal_state WHERE symbol = ?", (symbol,))
        total_pnl_inr += pnl_inr
        closed.append({"symbol": symbol, "instrument": "equity", "exit_price": exit_price, "pnl_inr": round(pnl_inr, 2)})

    for row in conn.execute("SELECT * FROM option_state").fetchall():
        opt_symbol = row["opt_symbol"]
        exit_premium = _requote_contract(row["underlying"], row["expiry"], row["strike"], row["right"])
        if exit_premium is None:
            exit_premium = row["entry_premium"]  # same stale-requote fallback as the normal exit path

        contracts = row["contracts"]
        qty = contracts * 100
        entry_fx = row["fx_to_inr"]
        pnl_native = (exit_premium - row["entry_premium"]) * qty
        pnl_inr = pnl_native * entry_fx
        risk_per_contract = row["entry_premium"] - row["stop_premium"]
        rr_achieved = round((exit_premium - row["entry_premium"]) / risk_per_contract, 2) if risk_per_contract else None
        payload = {
            "symbol": opt_symbol, "underlying": row["underlying"], "right": row["right"], "action": "sell",
            "qty": qty, "contracts": contracts, "price": exit_premium, "currency": "USD", "fx_to_inr": entry_fx,
            "strategy": OPTIONS_STRATEGY_TAG, "exit_reason": reason,
            "entry_price": row["entry_premium"], "stop_loss": row["stop_premium"], "target": row["target_premium"],
            "rr_target": live_rr, "rr_achieved": rr_achieved,
            "pnl_native": round(pnl_native, 2), "pnl_inr": round(pnl_inr, 2),
        }
        apply_paper_trade(conn, opt_symbol, "sell", qty, exit_premium)
        conn.execute(
            "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
            "VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)",
            (time.time(), opt_symbol, qty, exit_premium, entry_fx, OPTIONS_STRATEGY_TAG, json.dumps(payload)),
        )
        conn.execute("DELETE FROM option_state WHERE opt_symbol = ?", (opt_symbol,))
        total_pnl_inr += pnl_inr
        closed.append({"symbol": opt_symbol, "instrument": "option", "exit_price": exit_premium, "pnl_inr": round(pnl_inr, 2)})

    # REAL Kotak positions - added 2026-09-07 ("Kill switch on render is
    # not killing my live trade on Kotak"). Before this, the kill switch
    # closed ONLY paper positions above - an "emergency stop" that left
    # real money on the table was worse than having no kill switch at all.
    # Unconditional, no is_real_trading_enabled gate - same principle
    # _maybe_place_real_exit already established: closing an already-open
    # real position must never be blocked by any switch, including this
    # one's own reason for existing.
    real_closed = []
    real_close_failed = []
    import kotak_real_orders
    for row in conn.execute("SELECT * FROM real_positions").fetchall():
        if row["sl_order_id"]:
            cancel_result = kotak_real_orders.cancel_real_order(row["sl_order_id"])
            if not cancel_result.get("ok"):
                print(f"[REAL TRADE] KILL SWITCH SL cancel failed for {row['kotak_trading_symbol']} "
                      f"(order {row['sl_order_id']}): {cancel_result.get('detail')} - proceeding with exit anyway")
            _log_real_order_event(
                conn, row["symbol"], "sl", "cancelled" if cancel_result.get("ok") else "cancel_failed",
                kotak_trading_symbol=row["kotak_trading_symbol"], order_id=row["sl_order_id"],
                prev_state=f"resting @ Rs{row['sl_trigger_price']}", new_state="cancelled (kill switch)",
                detail=reason,
            )
        if row["target_order_id"]:
            cancel_result = kotak_real_orders.cancel_real_order(row["target_order_id"])
            if not cancel_result.get("ok"):
                print(f"[REAL TRADE] KILL SWITCH target cancel failed for {row['kotak_trading_symbol']} "
                      f"(order {row['target_order_id']}): {cancel_result.get('detail')} - proceeding with exit anyway")
            _log_real_order_event(
                conn, row["symbol"], "target", "cancelled" if cancel_result.get("ok") else "cancel_failed",
                kotak_trading_symbol=row["kotak_trading_symbol"], order_id=row["target_order_id"],
                prev_state=f"resting @ Rs{row['target_price']}", new_state="cancelled (kill switch)",
                detail=reason,
            )
        result = kotak_real_orders.place_real_exit(row["kotak_trading_symbol"], row["qty"])
        if result.get("ok"):
            conn.execute("DELETE FROM real_positions WHERE symbol = ?", (row["symbol"],))
            _log_real_attempt(
                conn, row["symbol"], "S", "confirmed", kotak_trading_symbol=row["kotak_trading_symbol"],
                qty=row["qty"], order_id=result["order_id"], raw_response=result.get("raw_response"),
                detail=reason,
            )
            real_closed.append({
                "symbol": row["symbol"], "kotak_trading_symbol": row["kotak_trading_symbol"],
                "qty": row["qty"], "order_id": result["order_id"],
            })
            print(f"[REAL TRADE] KILL SWITCH SELL {row['qty']} {row['kotak_trading_symbol']} (order {result['order_id']})")
            _log_real_order_event(
                conn, row["symbol"], "exit", "confirmed", kotak_trading_symbol=row["kotak_trading_symbol"],
                order_id=result["order_id"], prev_state=f"long {row['qty']} @ Rs{row['entry_price']:.2f}",
                new_state="closed (kill switch)", detail=reason,
            )
            _sync_real_positions_external(conn)
        else:
            # Same dangerous-failure handling as _maybe_place_real_exit -
            # left in real_positions, never guessed closed. Surfaced in the
            # kill response itself (not just /kotak-neo/real-positions) so
            # a human sees it immediately.
            _log_real_attempt(
                conn, row["symbol"], "S", "failed", kotak_trading_symbol=row["kotak_trading_symbol"],
                qty=row["qty"], detail=result.get("detail"), raw_response=result.get("raw_response"),
            )
            real_close_failed.append({
                "symbol": row["symbol"], "kotak_trading_symbol": row["kotak_trading_symbol"],
                "qty": row["qty"], "detail": result.get("detail"),
            })
            print(f"[REAL TRADE] KILL SWITCH SELL FAILED {row['kotak_trading_symbol']}: "
                  f"{result.get('detail')} - POSITION STILL OPEN, NEEDS ATTENTION")
            _log_real_order_event(
                conn, row["symbol"], "exit", "failed", kotak_trading_symbol=row["kotak_trading_symbol"],
                prev_state=f"long {row['qty']} @ Rs{row['entry_price']:.2f}",
                new_state="still open - kill switch exit failed", detail=result.get("detail"),
            )
            _flag_if_t1_restricted(conn, row["symbol"], result.get("detail"))

    conn.commit()
    return {
        "closed_count": len(closed), "closed": closed, "total_pnl_inr": round(total_pnl_inr, 2),
        "real_closed_count": len(real_closed), "real_closed": real_closed,
        "real_close_failed_count": len(real_close_failed), "real_close_failed": real_close_failed,
    }


@app.get("/trading-control")
def get_trading_control():
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM trading_control WHERE id = 1").fetchone()
    return dict(row) if row else {"id": 1, "enabled": True, "updated_at": None, "updated_by": None, "reason": None}


@app.post("/trading-control")
def set_trading_control(action: str, reason: str | None = None):
    """The kill switch's HTTP surface. action:
      - 'pause'  - stop taking NEW entries; existing open positions keep
                   being managed normally (stop/target/trend/eod).
      - 'resume' - allow new entries again.
      - 'kill'   - force-close every open position right now (see
                   _force_close_all_positions) AND pause, so nothing
                   reopens on the very next tick.
    """
    if action not in ("pause", "resume", "kill"):
        raise HTTPException(status_code=400, detail="action must be one of: pause, resume, kill")

    with closing(get_db()) as conn:
        if action == "kill":
            summary = _force_close_all_positions(conn, reason or "manual_kill_switch")
            conn.execute(
                "INSERT INTO trading_control (id, enabled, updated_at, updated_by, reason) "
                "VALUES (1, 0, ?, 'user', ?) "
                "ON CONFLICT(id) DO UPDATE SET enabled=0, updated_at=excluded.updated_at, "
                "updated_by=excluded.updated_by, reason=excluded.reason",
                (time.time(), reason or "kill switch"),
            )
            conn.commit()
            return {"status": "killed", "enabled": False, **summary}

        enabled = 1 if action == "resume" else 0
        conn.execute(
            "INSERT INTO trading_control (id, enabled, updated_at, updated_by, reason) "
            "VALUES (1, ?, ?, 'user', ?) "
            "ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by, reason=excluded.reason",
            (enabled, time.time(), reason),
        )
        conn.commit()
        return {"status": "paused" if action == "pause" else "resumed", "enabled": bool(enabled)}


# --- Stage 3: real order placement - HTTP surface ---------------------------
# Token-gated (same KOTAK_NEO_API_TOKEN as every other real-account
# endpoint) - unlike /trading-control (paper, no token needed), these touch
# real money and must never be callable by an unauthenticated request.


@app.get("/real-pnl-today")
def get_real_pnl_today():
    """Real (Kotak) P&L summary only - no token required, unlike
    /real-trading-control. Explicit user instruction (2026-09-07): "why
    token needed. make it without any checks" - deliberately narrower
    than /real-trading-control rather than just dropping that endpoint's
    own gate: this returns ONLY the P&L/budget numbers, never
    open_real_positions (symbol, qty, entry price, order id) or the
    enable/disable switch state - the actual account/order detail stays
    behind the token, only the summary figure the trade-view dashboard
    shows is public. Same numbers as /real-trading-control's own
    real_pnl_today_inr/real_loss_cap_inr/real_loss_budget_remaining_inr -
    see get_real_pnl_today_inr's docstring for how this is computed."""
    with closing(get_db()) as conn:
        loss_check = _real_loss_budget(conn)
    real_capital = get_scheduler_capital_inr()
    real_pnl_today = loss_check["real_pnl_today"]
    real_capital_deployed = get_real_capital_deployed_inr()
    real_loss_cap_inr = round(loss_check["cap_inr"], 2)
    return {
        "real_pnl_today_inr": round(real_pnl_today, 2) if real_pnl_today is not None else None,
        "real_pnl_source": "kotak_positions_today" if real_pnl_today is not None else "unavailable",
        "real_pnl_fetch_error": _real_trades_cache["error"],
        "real_loss_cap_inr": real_loss_cap_inr,
        "real_loss_budget_remaining_inr": (
            round(max(0.0, real_loss_cap_inr - max(0.0, -real_pnl_today)), 2) if real_pnl_today is not None else None
        ),
        # real_loss_cap_inr is now daily_risk_pct% of a FIXED day-open
        # capital snapshot (2026-09-08, explicit user instruction: "keep
        # it as a % of total money available at the beginning of day") -
        # joint across equity + F&O, see _real_loss_budget's own
        # docstring. real_capital_available_inr below stays the LIVE,
        # continuously-refreshing figure (a different concept - "what's
        # available right now", used for position sizing, not the cap) so
        # the two are never conflated.
        "real_capital_day_open_inr": round(loss_check["day_open_capital_inr"], 2),
        "real_capital_available_inr": round(real_capital, 2),
        "real_capital_deployed_inr": real_capital_deployed,
    }


@app.get("/real-trades-today")
def get_real_trades_today():
    """Every closed REAL trade today, Kotak's own ground truth - not just
    the aggregate real_pnl_today_inr, and not this app's own real_trades
    table (which only ever logs orders THIS code places, so it has zero
    record of anything traded directly on Kotak - see get_real_pnl_today_inr's
    docstring for the same gap). Explicit user finding (2026-09-07): "i can
    see no trade here, while you know that trade happened today - they why
    not in sync as of now?" - the trade-view Trade Log table only ever
    showed PAPER trades; this is the real-trade equivalent, merged into
    that same table client-side (see trade-view.html's renderTradeLog).

    No token required, same reasoning as /real-pnl-today ("make it without
    any checks") - per-trade symbol/qty/price is more detail than the
    aggregate, but this is still a closed/historical trade list, not
    account state or order IDs (those stay behind /kotak-neo/positions'
    own token gate). Same fully-squared-off filter as get_real_pnl_today_inr
    (flBuyQty == flSellQty, dated today) - an OPEN real position never
    appears here, only completed round trips.

    2026-09-07 (second pass): now reads get_real_trades_today_list()'s
    shared cache instead of its own separate positions() call - one
    Kotak fetch serves this endpoint, get_real_pnl_today_inr, and the
    account-wide daily-loss figure alike, instead of three."""
    trades_raw = get_real_trades_today_list()
    if trades_raw is None:
        return {"error": _real_trades_cache["error"], "trades": []}
    trades = [
        {**t, "pnl_pct_of_capital": None, "exit_reason": "kotak_real_trade",
         "rr_target": None, "rr_achieved": None, "strategy": "real (Kotak)"}
        for t in trades_raw
    ]
    trades.sort(key=lambda t: t["exit_time_utc"], reverse=True)
    return {"date_ist": ist_now().strftime("%Y-%m-%d"), "trades_count": len(trades), "trades": trades}


@app.get("/real-trades-today-bot-only")
def get_real_trades_today_bot_only():
    """This app's OWN real trading only - both currently-open positions
    and today's closed round-trips - filtered to just the orders THIS
    code itself placed (real_trades/real_positions, tracked by order id),
    unlike /real-trades-today's whole-account Kotak aggregate (which
    deliberately includes manually-placed trades in the same symbol too -
    that was explicit user-requested behavior on 2026-09-07, kept as-is).

    Added 2026-09-08, explicit user request: "add a bot-only real-trade
    view (filtered to just this app's own order IDs, separate from the
    whole-account aggregate) so you have a row that's actually comparable
    to the paper one at a glance" - when a symbol is also traded manually
    outside this app (confirmed live today: AGL), the whole-account
    number and the paper engine's own number are computed from
    unrelated data and were never going to match; THIS view is what
    actually corresponds 1:1 with a single paper decision, since it's
    built from the exact rows _maybe_place_real_entry/_exit themselves
    wrote when mirroring that decision.

    No token required, same reasoning as /real-trades-today and
    /real-pnl-today ("make it without any checks") - real symbol/qty/
    price detail already exposed publicly there; this is the same data,
    just re-filtered and re-shaped.

    closed_trades pairs each day's confirmed BUY with the confirmed SELL
    that follows it for the same symbol, in chronological order - safe
    because this app only ever holds ONE open real position per symbol
    at a time (see real_positions.symbol's PRIMARY KEY), so a B is always
    immediately followed by its own matching S, never interleaved with
    another B for the same symbol before that S. An unmatched trailing
    BUY (position still open) is intentionally left out of closed_trades -
    it's already visible in open_positions instead."""
    today = ist_now().strftime("%Y-%m-%d")
    with closing(get_db()) as conn:
        open_positions = [dict(r) for r in conn.execute("SELECT * FROM real_positions").fetchall()]
        rows = conn.execute(
            "SELECT symbol, kotak_trading_symbol, side, qty, price_est, notional_inr, ts, order_id "
            "FROM real_trades WHERE day = ? AND status = 'confirmed' ORDER BY symbol, ts",
            (today,),
        ).fetchall()
    closed_trades = []
    open_buy_by_symbol: dict = {}
    for r in rows:
        r = dict(r)
        if r["side"] == "B":
            open_buy_by_symbol[r["symbol"]] = r
        elif r["side"] == "S" and r["symbol"] in open_buy_by_symbol:
            buy = open_buy_by_symbol.pop(r["symbol"])
            qty = r["qty"] or buy["qty"] or 0
            pnl_inr = round((r["price_est"] - buy["price_est"]) * qty, 2) if (
                r["price_est"] is not None and buy["price_est"] is not None) else None
            closed_trades.append({
                "symbol": r["symbol"], "kotak_trading_symbol": r["kotak_trading_symbol"],
                "entry_price_native": buy["price_est"], "exit_price_native": r["price_est"],
                "qty": qty, "pnl_inr": pnl_inr,
                "entry_order_id": buy["order_id"], "exit_order_id": r["order_id"],
                "entry_time_utc": buy["ts"], "exit_time_utc": r["ts"],
                "strategy": "real-bot-own",
            })
    closed_trades.sort(key=lambda t: t["exit_time_utc"], reverse=True)
    return {
        "date_ist": today,
        "open_positions": open_positions,
        "closed_trades_count": len(closed_trades),
        "closed_trades": closed_trades,
    }


@app.get("/real-order-log")
def get_real_order_log(days: int = 1):
    """The order STATE-TRANSITION log - explicit user instruction
    2026-09-08: "I want to see the log of what order you have placed and
    from what prev state to what current new order state." Every real
    entry/exit/sl/target state change this app makes gets one row here
    (see _log_real_order_event and real_order_events' own CREATE TABLE
    comment) - this is the raw feed static/order-log.html (GET /order-log)
    renders, newest first.

    days: how many days back to include (default 1 - today only; this
    table is only as durable as the SQLite process it lives in between
    journal-sync snapshots, same caveat as every other real_* table here -
    see docs/real_order_log.json, appended by journal-sync.yml, for the
    permanent record beyond a single Render process's lifetime).

    No token required - same reasoning as /real-trades-today-bot-only:
    this is the same real order data already exposed there, just reshaped
    into a state-transition view."""
    cutoff = time.time() - max(days, 1) * 86400
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT * FROM real_order_events WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
        ).fetchall()
    return {"count": len(rows), "events": [dict(r) for r in rows]}


@app.get("/order-log")
def order_log_page():
    """Order state-transition log page - explicit user instruction
    2026-09-08: "Create a bot where I can see those [order state
    transitions]." Pulls live from /real-order-log client-side, same
    self-refresh pattern as /live and /trade-view."""
    return FileResponse("static/order-log.html")


@app.get("/real-trading-control")
def get_real_trading_control(request: Request):
    _require_kotak_token(request)
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM real_trading_control WHERE id = 1").fetchone()
        open_positions = [dict(r) for r in conn.execute("SELECT * FROM real_positions").fetchall()]
        today_spent_inr = _real_today_spent_inr(conn)
        daily_cap_inr = get_runtime_setting(conn, "real_daily_cap_inr")
        today_str = ist_now().strftime("%Y-%m-%d")
        t1_restricted_today = [
            dict(r) for r in conn.execute(
                "SELECT symbol, flagged_at, detail FROM real_t1_restricted WHERE day = ?", (today_str,)
            ).fetchall()
        ]
        # REAL P&L and its own loss cap - added 2026-09-07, Kotak's own
        # ground truth (see get_real_pnl_today_inr's docstring), NOT the
        # paper-only figure /daily-summary's budget_remaining shows. This
        # is the number that actually answers "how much more can this
        # account lose today before the real-money gate refuses a new
        # entry" - see _real_loss_budget, which every real entry path
        # (equity, F&O single-leg, F&O straddle) now enforces identically
        # (2026-09-08, "joint cap... % of total money available at the
        # beginning of day").
        loss_check = _real_loss_budget(conn)
    db_enabled = bool(row["enabled"]) if row else False
    env_enabled = os.environ.get("REAL_TRADING_ENABLED") == "YES"
    real_pnl_today = loss_check["real_pnl_today"]
    real_loss_cap_inr = round(loss_check["cap_inr"], 2)
    return {
        "db_switch_enabled": db_enabled, "env_var_enabled": env_enabled,
        "real_trading_active": db_enabled and env_enabled,
        "updated_at": row["updated_at"] if row else None,
        "updated_by": row["updated_by"] if row else None,
        "reason": row["reason"] if row else None,
        "daily_cap_inr": daily_cap_inr,
        "today_ist_date": ist_now().strftime("%Y-%m-%d"),  # journal-sync.yml needs this, not just the amount
        "today_spent_inr": round(today_spent_inr, 2),
        "today_remaining_inr": round(daily_cap_inr - today_spent_inr, 2),
        "real_pnl_today_inr": round(real_pnl_today, 2) if real_pnl_today is not None else None,
        "real_pnl_source": "kotak_positions_today" if real_pnl_today is not None else "unavailable",
        "real_pnl_fetch_error": _real_trades_cache["error"],
        "real_loss_cap_inr": real_loss_cap_inr,
        "real_loss_budget_remaining_inr": (
            round(max(0.0, real_loss_cap_inr - max(0.0, -real_pnl_today)), 2) if real_pnl_today is not None else None
        ),
        "real_capital_day_open_inr": round(loss_check["day_open_capital_inr"], 2),
        "open_real_positions": open_positions,
        "t1_restricted_today": t1_restricted_today,
    }


@app.get("/real-open-positions")
def get_real_open_positions():
    """Currently-OPEN real (Kotak) positions, with a LIVE current price and
    computed unrealized P&L per row - no token required, same reasoning as
    /real-pnl-today's own split-out from /real-trading-control (read-only
    display data, not the enable/disable switch or a control action).

    2026-09-09, explicit user finding: the /trade-view dashboard's live
    table showed "No live positions or real trades today" while Kotak's
    own account had a genuinely open real position (MEDICAMEQ.NS) -
    trade-view.html's own refresh() had NO fetch of real_positions'
    currently-open rows at all, only open PAPER positions (/daily-summary)
    and CLOSED real trades (/real-trades-today, /real-trades-today-bot-
    only) - an open-but-not-yet-closed real position had no data source
    anywhere on the page. This is that missing source: current_price comes
    from fetch_ohlc's own cached last close (the same live-price data
    every other price on this page already reads, so this stays
    consistent with the rest of the dashboard, not a second live-price
    path), refreshed on the page's existing 10s poll cycle - no separate
    faster polling loop needed, the gap was the missing fetch, not the
    cadence.

    Also returns any OPEN Kotak position this app never tracked at all
    (source="kotak_untracked" rows, vs "bot_tracked" for real_positions'
    own rows) - a second live finding the same day: Kotak's own Positions
    tab showed 2 more open positions (NEWGEN, SANDUMA) than this endpoint
    did. Never auto-adopted (same reasoning as reconcile's own `adopt`
    param - a human decision, not automatic), but always SHOWN, so the
    dashboard genuinely mirrors what's open at the broker within the
    page's existing 10s poll, not just what this app remembers placing."""
    watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in WATCHLIST}
    with closing(get_db()) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM real_positions").fetchall()]

    result = []
    for r in rows:
        current_price = None
        try:
            cfg = watchlist_by_symbol.get(r["symbol"], {})
            current_price = float(fetch_ohlc(r["symbol"], "1d", cfg.get("interval", "5m"))["Close"].iloc[-1])
        except Exception:
            pass
        invested_inr = round(r["entry_price"] * r["qty"], 2)
        unrealized_pnl_inr = round((current_price - r["entry_price"]) * r["qty"], 2) if current_price is not None else None
        unrealized_pnl_pct = (
            round(100 * unrealized_pnl_inr / invested_inr, 3) if unrealized_pnl_inr is not None and invested_inr else None
        )
        # target_status/target_status_detail (2026-09-09, explicit user
        # instruction: "I don't see any resilient way from ur side that
        # how u r booking profits when the target is reached. Show me on
        # render what is target for each entered trade") - target_price
        # alone doesn't tell the user whether a REAL resting order for it
        # actually exists at Kotak right now, which is exactly what they're
        # asking to see. "resting" = target_order_id is set, a real order
        # is live at the broker. "blocked" = this symbol is flagged
        # real_t1_restricted today (T1-holdings or T2T same-day-sell, see
        # _flag_if_t1_restricted) - a real, unfixable-today reason no
        # target/exit order can complete. "failed" = an attempt was made
        # and rejected for some OTHER reason (surfaced verbatim so it's
        # never silently hidden). "not_yet_attempted" = no target order
        # has been tried at all yet (will be attempted on the next
        # reconcile pass or scheduler tick, per the governance-backfill/
        # entry-flow logic in kotak_neo_reconcile_real_positions).
        target_status, target_status_detail = "resting", None
        if not r["target_order_id"]:
            with closing(get_db()) as conn2:
                # No day filter (2026-09-09) - matches _is_t1_restricted's
                # own fix to the same bug: a restriction confirmed on an
                # EARLIER day must still show as "blocked" today, not
                # silently fall through to "not_yet_attempted"/"failed".
                t1_row = conn2.execute(
                    "SELECT detail FROM real_t1_restricted WHERE symbol = ? ORDER BY flagged_at DESC LIMIT 1",
                    (r["symbol"],),
                ).fetchone()
                if t1_row:
                    target_status, target_status_detail = "blocked", t1_row["detail"]
                else:
                    fail_row = conn2.execute(
                        "SELECT detail FROM real_order_events WHERE symbol = ? AND leg = 'target' "
                        "AND event = 'failed' ORDER BY ts DESC LIMIT 1",
                        (r["symbol"],),
                    ).fetchone()
                    if fail_row:
                        target_status, target_status_detail = "failed", fail_row["detail"]
                    else:
                        target_status = "not_yet_attempted"
        result.append({
            **r,
            "current_price": current_price,
            "invested_inr": invested_inr,
            "unrealized_pnl_inr": unrealized_pnl_inr,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "target_status": target_status,
            "target_status_detail": target_status_detail,
            "source": "bot_tracked",
        })

    # Untracked Kotak positions (2026-09-09, explicit user finding: Kotak's
    # own Positions tab showed 4 open positions - MEDICAMEQ, SILVERCASE
    # (both bot-tracked, above) plus NEWGEN and SANDUMA (neither) - while
    # this endpoint only ever showed the bot-tracked two: "Why not in sync
    # still? I want them to be in sync with at max 10 second delay." Same
    # untracked-detection logic kotak_neo_reconcile_real_positions already
    # uses (flBuyQty/flSellQty/trdSym on nse_cm) - reused here for DISPLAY
    # only, never auto-adopted (adopting means placing real SL/target
    # orders sized off risk parameters this app never decided for a
    # position it didn't open - a human decision, unchanged from the
    # reconcile endpoint's own `adopt` param). Best-effort: a Kotak fetch
    # failure here still returns the bot-tracked rows above, same
    # graceful-degradation the rest of this endpoint already has."""
    try:
        import kotak_neo
        positions_resp = kotak_neo.positions()
        kotak_rows = positions_resp.get("data") or [] if isinstance(positions_resp, dict) else []
        our_trdsyms = {r["kotak_trading_symbol"] for r in rows}
        for kr in kotak_rows:
            try:
                if kr.get("exSeg") != "nse_cm":
                    continue
                fl_buy = float(kr.get("flBuyQty", 0) or 0)
                fl_sell = float(kr.get("flSellQty", 0) or 0)
                net_qty = fl_buy - fl_sell
                if net_qty == 0:
                    continue  # fully squared off - not an open position
                trd_sym = kr.get("trdSym")
                if not trd_sym or trd_sym in our_trdsyms:
                    continue
                buy_amt = float(kr.get("buyAmt", 0) or 0)
                avg_price = round(buy_amt / fl_buy, 2) if fl_buy else None
                bare_symbol = trd_sym[:-3] + ".NS" if trd_sym.endswith("-EQ") else f"{trd_sym}.NS"
                current_price = None
                try:
                    current_price = float(fetch_ohlc(bare_symbol, "1d", "5m")["Close"].iloc[-1])
                except Exception:
                    pass
                invested_inr = round(avg_price * net_qty, 2) if avg_price is not None else None
                unrealized_pnl_inr = (
                    round((current_price - avg_price) * net_qty, 2)
                    if current_price is not None and avg_price is not None else None
                )
                result.append({
                    "symbol": bare_symbol, "kotak_trading_symbol": trd_sym, "qty": int(net_qty),
                    "entry_price": avg_price, "entry_order_id": None, "opened_at": None,
                    "day": ist_now().strftime("%Y-%m-%d"), "sl_order_id": None, "sl_trigger_price": None,
                    "target_order_id": None, "target_price": None,
                    "current_price": current_price, "invested_inr": invested_inr,
                    "unrealized_pnl_inr": unrealized_pnl_inr,
                    "unrealized_pnl_pct": (
                        round(100 * unrealized_pnl_inr / invested_inr, 3)
                        if unrealized_pnl_inr is not None and invested_inr else None
                    ),
                    "target_status": "not_bot_managed", "target_status_detail": None,
                    "source": "kotak_untracked",
                })
            except (TypeError, ValueError):
                continue
    except Exception:
        pass  # Kotak fetch failed - still return the bot-tracked rows above

    return {"open_real_positions": result, "count": len(result)}


@app.get("/kotak-neo/real-fo-control")
def get_real_fo_control(request: Request):
    """Status for the SEPARATE F&O real-trading gate (2026-09-07) - see
    is_real_fo_trading_enabled's own docstring for why this is its own
    switch, not shared with equity's real_trading_control."""
    _require_kotak_token(request)
    with closing(get_db()) as conn:
        open_positions = [dict(r) for r in conn.execute("SELECT * FROM real_fo_positions").fetchall()]
        open_straddles = [dict(r) for r in conn.execute("SELECT * FROM nse_straddle_state").fetchall()]
        today_spent_inr = _real_fo_today_spent_inr(conn)
        daily_cap_inr = get_runtime_setting(conn, "real_fo_daily_cap_inr")
        straddle_enabled = get_runtime_setting(conn, "real_straddle_enabled") >= 0.5
        # Joint real daily-loss cap (2026-09-08) - see _real_loss_budget's
        # own docstring. Same number /real-trading-control shows - this
        # cap is now SHARED across equity and F&O, not a separate F&O-only
        # figure, so both endpoints report the identical joint state.
        loss_check = _real_loss_budget(conn)
    real_pnl_today = loss_check["real_pnl_today"]
    real_loss_cap_inr = round(loss_check["cap_inr"], 2)
    return {
        "env_var_enabled": is_real_fo_trading_enabled(),
        "real_straddle_enabled": straddle_enabled,
        "today_ist_date": ist_now().strftime("%Y-%m-%d"),
        "daily_cap_inr": daily_cap_inr,
        "today_spent_inr": round(today_spent_inr, 2),
        "today_remaining_inr": round(daily_cap_inr - today_spent_inr, 2),
        "real_pnl_today_inr": round(real_pnl_today, 2) if real_pnl_today is not None else None,
        "real_loss_cap_inr": real_loss_cap_inr,
        "real_loss_budget_remaining_inr": (
            round(max(0.0, real_loss_cap_inr - max(0.0, -real_pnl_today)), 2) if real_pnl_today is not None else None
        ),
        "real_capital_day_open_inr": round(loss_check["day_open_capital_inr"], 2),
        "open_real_fo_positions": open_positions,
        "open_paper_straddles": open_straddles,
    }


@app.get("/kotak-neo/nse-fo-chain")
def kotak_neo_nse_fo_chain(request: Request, underlying: str, right: str | None = None, spot: float | None = None):
    """Diagnostic - manually verify nse_fo_chain.py's real contract
    resolution before trusting it live (same "confirm before trusting"
    discipline as every other Kotak-data endpoint in this file).
    `right` ('call'/'put') + `spot` resolves an ATM option contract;
    omit both for the nearest-expiry future instead."""
    _require_kotak_token(request)
    import nse_fo_chain
    if right and spot is not None:
        contract, err = nse_fo_chain.select_nse_option_contract(underlying.upper(), spot, right)
    else:
        contract, err = nse_fo_chain.select_nse_future(underlying.upper())
    return {"contract": contract, "error": err}


@app.post("/real-trading-control")
def set_real_trading_control(request: Request, action: str, reason: str | None = None):
    """The REAL-money kill switch's HTTP surface - completely separate
    from /trading-control (paper). action:
      - 'enable'  - allow real entries (still also needs
                    REAL_TRADING_ENABLED=YES set as an env var - this
                    alone is NOT enough to turn real trading on).
      - 'disable' - stop taking new real entries; any already-open real
                    position keeps being managed normally (its exit is
                    never gated by this switch - see _maybe_place_real_exit).
    """
    _require_kotak_token(request)
    if action not in ("enable", "disable"):
        raise HTTPException(status_code=400, detail="action must be one of: enable, disable")
    enabled = 1 if action == "enable" else 0
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
            "VALUES (1, ?, ?, 'user', ?) "
            "ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by, reason=excluded.reason",
            (enabled, time.time(), reason),
        )
        conn.commit()
    return {"status": "enabled" if enabled else "disabled", "db_switch_enabled": bool(enabled)}


@app.get("/kotak-neo/real-trades")
def kotak_neo_real_trades(request: Request):
    """Full audit log of every real-order attempt (confirmed/failed/
    skipped-and-why) - the permanent record for real money, uncapped."""
    _require_kotak_token(request)
    with closing(get_db()) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM real_trades ORDER BY id DESC").fetchall()]
    return {"count": len(rows), "trades": rows}


# ---------------------------------------------------------------------------
# Startup reconciliation: Render's free tier has no persistent disk, so every
# redeploy wipes the SQLite DB clean - including any open position, which
# would otherwise just vanish from tracking (never checked against its
# stop/target again, no exit ever recorded). state/open_positions.json is a
# plain git-tracked file, not part of the DB, so it survives every redeploy
# (it's baked into each fresh checkout). The GH Actions workflows
# (live-signals*.yml) write it after every poll, so it's never more than one
# poll interval (<=5 min) stale - not perfectly real-time, but a position is
# never silently forgotten.
STATE_JOURNAL_PATH = os.path.join(os.path.dirname(__file__), "state", "open_positions.json")


def reconcile_open_positions_from_journal():
    """Restore any position the journal remembers but a freshly-wiped DB
    doesn't - as a real 'buy' in trades (so today_realized_pnl's cost-basis
    book is correct once it's eventually closed) and as an open row in
    signal_state (so the normal stop/target/eod-squareoff check on the very
    next scheduler tick picks it up and closes it exactly as if the redeploy
    never happened)."""
    if not os.path.exists(STATE_JOURNAL_PATH):
        return
    try:
        with open(STATE_JOURNAL_PATH) as f:
            journal = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_JOURNAL_PATH}: {e}")
        return

    tz_by_symbol = {cfg["symbol"]: cfg["tz_offset_min"] for cfg in WATCHLIST}
    recovered = []
    with closing(get_db()) as conn:
        for pos in journal.get("open_positions", []):
            symbol = pos["symbol"]

            if pos.get("instrument") == "option":
                # A different table (option_state, not signal_state) and a
                # different row shape (strike/expiry/right, no orb_high/low)
                # - see _options_signal_core. Restored the same way in
                # spirit: a real 'buy' leg in trades for correct cost basis,
                # plus the open row so the very next scheduler tick manages
                # it (requote/stop/target/eod-squareoff) exactly as if the
                # redeploy never happened.
                already_open_opt = conn.execute(
                    "SELECT 1 FROM option_state WHERE opt_symbol = ?", (symbol,)
                ).fetchone()
                if already_open_opt:
                    continue
                entry_ts = pos["entry_ts"]
                if _closed_in_durable_log(symbol, pos["entry_price_native"], entry_ts):
                    continue  # already durably closed - stale journal snapshot, don't resurrect
                day_str = (
                    dt.datetime.utcfromtimestamp(entry_ts) + dt.timedelta(minutes=IST_OFFSET_MIN)
                ).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                    "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
                    (entry_ts, symbol, pos["qty"], pos["entry_price_native"], pos["fx_to_inr"],
                     OPTIONS_STRATEGY_TAG, json.dumps({"recovered_from_journal": True, **pos})),
                )
                apply_paper_trade(conn, symbol, "buy", pos["qty"], pos["entry_price_native"])
                conn.execute(
                    "INSERT INTO option_state "
                    "(opt_symbol, underlying, day, right, expiry, strike, contracts, entry_premium, "
                    "stop_premium, target_premium, entry_iv, entry_delta, entry_ts, fx_to_inr) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(opt_symbol) DO UPDATE SET day=excluded.day, expiry=excluded.expiry, "
                    "strike=excluded.strike, contracts=excluded.contracts, entry_premium=excluded.entry_premium, "
                    "stop_premium=excluded.stop_premium, target_premium=excluded.target_premium, "
                    "entry_iv=excluded.entry_iv, entry_delta=excluded.entry_delta, entry_ts=excluded.entry_ts, "
                    "fx_to_inr=excluded.fx_to_inr",
                    (symbol, pos["underlying"], day_str, pos["right"], pos["expiry"], pos["strike"],
                     pos["contracts"], pos["entry_price_native"], pos["stop_loss_native"],
                     pos["target_native"], pos.get("entry_iv"), pos.get("entry_delta"), entry_ts, pos["fx_to_inr"]),
                )
                recovered.append(symbol)
                continue

            already_open = conn.execute(
                "SELECT 1 FROM signal_state WHERE symbol = ? AND status = 'long'", (symbol,)
            ).fetchone()
            if already_open:
                continue
            if _closed_in_durable_log(symbol, pos["entry_price_native"], pos["entry_ts"]):
                continue  # already durably closed - stale journal snapshot, don't resurrect

            entry_ts = pos["entry_ts"]
            tz_offset_min = tz_by_symbol.get(symbol, IST_OFFSET_MIN)
            # Same day derivation _auto_signal_core uses (utcnow + tz offset),
            # applied at entry_ts instead of "now" - if this doesn't match,
            # the very next poll treats the position as stale-from-a-prior-day
            # and silently deletes it (see the row["day"] != today_str check).
            day_str = (
                dt.datetime.utcfromtimestamp(entry_ts) + dt.timedelta(minutes=tz_offset_min)
            ).strftime("%Y-%m-%d")

            # Use the real entry strategy if the journal snapshot carries one
            # (added 2026-09-03, alongside daily_summary()'s own "strategy"
            # field) - only fall back to the generic "recovered" placeholder
            # for an older journal file written before that field existed,
            # where the true originating strategy is genuinely unknown.
            strategy_tag = pos.get("strategy") or f"{ORB_STRATEGY_PREFIX}recovered"
            conn.execute(
                "INSERT INTO trades (ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload) "
                "VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)",
                (entry_ts, symbol, pos["qty"], pos["entry_price_native"], pos["fx_to_inr"],
                 strategy_tag, json.dumps({"recovered_from_journal": True, **pos})),
            )
            apply_paper_trade(conn, symbol, "buy", pos["qty"], pos["entry_price_native"])
            conn.execute(
                "INSERT INTO signal_state "
                "(symbol, day, status, entry_price, stop_loss, initial_stop_loss, target, qty, entry_ts, orb_high, orb_low, fx_to_inr, interval) "
                "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET day=excluded.day, status=excluded.status, "
                "entry_price=excluded.entry_price, stop_loss=excluded.stop_loss, "
                "initial_stop_loss=excluded.initial_stop_loss, "
                "target=excluded.target, qty=excluded.qty, entry_ts=excluded.entry_ts, "
                "orb_high=excluded.orb_high, orb_low=excluded.orb_low, fx_to_inr=excluded.fx_to_inr, "
                "interval=excluded.interval",
                # initial_stop_loss_native only exists in a journal snapshot
                # written after this feature shipped - fall back to
                # stop_loss_native (whatever the live stop was at sync time,
                # possibly already trailed) for an older one, same spirit as
                # the strategy-tag fallback just above.
                (symbol, day_str, pos["entry_price_native"], pos["stop_loss_native"],
                 pos.get("initial_stop_loss_native", pos["stop_loss_native"]),
                 pos["target_native"], pos["qty"], entry_ts, pos["orb_high_native"],
                 pos["orb_low_native"], pos["fx_to_inr"], pos.get("interval", "5m")),
            )
            recovered.append(symbol)
        conn.commit()

    if recovered:
        print(f"[reconcile] restored {len(recovered)} open position(s) from journal: {recovered}")


STATE_TRADING_CONTROL_PATH = os.path.join(os.path.dirname(__file__), "state", "trading_control.json")


def reconcile_trading_control_from_journal():
    """A paused/killed state MUST survive a Render redeploy - the DB (and
    its fresh trading_control row, default enabled=1) gets wiped just like
    open positions do, so without this a pause would silently lift on the
    next push/redeploy, which defeats the entire point of a kill switch.
    journal-sync.yml writes state/trading_control.json from the live
    /trading-control status every sync, the same journal pattern as open
    positions."""
    if not os.path.exists(STATE_TRADING_CONTROL_PATH):
        return
    try:
        with open(STATE_TRADING_CONTROL_PATH) as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_TRADING_CONTROL_PATH}: {e}")
        return
    if saved.get("enabled", True):
        return  # default DB state is already enabled=1 - nothing to restore
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO trading_control (id, enabled, updated_at, updated_by, reason) "
            "VALUES (1, 0, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET enabled=0, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by, reason=excluded.reason",
            (saved.get("updated_at") or time.time(), saved.get("updated_by", "user"),
             saved.get("reason", "restored paused state from journal")),
        )
        conn.commit()
    print("[reconcile] restored PAUSED trading state from journal")


# --- Stage 3 journal reconciliation -----------------------------------------
# Same Render-free-tier-has-no-persistent-disk reality as everything above,
# but higher stakes: an unrecovered real_positions row means a REAL open
# position silently drops off management (never exit-checked again), and an
# unrecovered today's-spend means the Rs 500/day cap could be exceeded after
# a mid-day restart. journal-sync.yml must have KOTAK_NEO_API_TOKEN available
# as a GitHub Actions secret for these two syncs to run at all (they hit
# token-gated endpoints) - if that secret isn't set, this reconciliation is a
# harmless no-op (files just won't exist), but the durability gap it exists
# to close stays open. See docs/TRADING_CONSTRAINTS.md "Stage 3".
STATE_REAL_TRADING_CONTROL_PATH = os.path.join(os.path.dirname(__file__), "state", "real_trading_control.json")
STATE_REAL_POSITIONS_PATH = os.path.join(os.path.dirname(__file__), "state", "real_positions.json")
STATE_REAL_TRADES_TODAY_PATH = os.path.join(os.path.dirname(__file__), "state", "real_trades_today.json")


def reconcile_real_trading_control_from_journal():
    if not os.path.exists(STATE_REAL_TRADING_CONTROL_PATH):
        return
    try:
        with open(STATE_REAL_TRADING_CONTROL_PATH) as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_REAL_TRADING_CONTROL_PATH}: {e}")
        return
    if not saved.get("db_switch_enabled", False):
        return  # default DB state is already enabled=0 - nothing to restore
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO real_trading_control (id, enabled, updated_at, updated_by, reason) "
            "VALUES (1, 1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET enabled=1, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by, reason=excluded.reason",
            (saved.get("updated_at") or time.time(), saved.get("updated_by", "user"),
             saved.get("reason", "restored ENABLED real-trading state from journal")),
        )
        conn.commit()
    print("[reconcile] restored real_trading_control ENABLED state from journal")


def reconcile_real_positions_from_journal():
    """Restore any REAL open position the journal remembers but a freshly-
    wiped DB doesn't. Deliberately does NOT re-place any order - the
    position already exists at the broker; this only restores this app's
    own tracking of it so the next scheduler tick's exit-mirroring
    (_maybe_place_real_exit) can find and manage it again."""
    if not os.path.exists(STATE_REAL_POSITIONS_PATH):
        return
    try:
        with open(STATE_REAL_POSITIONS_PATH) as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_REAL_POSITIONS_PATH}: {e}")
        return
    positions = saved.get("open_real_positions", [])
    if not positions:
        return
    with closing(get_db()) as conn:
        restored = 0
        for pos in positions:
            if conn.execute("SELECT 1 FROM real_positions WHERE symbol = ?", (pos["symbol"],)).fetchone():
                continue
            conn.execute(
                "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
                "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, "
                "target_order_id, target_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pos["symbol"], pos["kotak_trading_symbol"], pos["qty"], pos["entry_price"],
                 pos.get("entry_order_id"), pos["opened_at"], pos["day"],
                 pos.get("sl_order_id"), pos.get("sl_trigger_price"),
                 pos.get("target_order_id"), pos.get("target_price")),
            )
            restored += 1
        conn.commit()
        if restored:
            _sync_real_positions_external(conn)
    if restored:
        print(f"[reconcile] restored {restored} REAL open position(s) from journal")


def reconcile_real_trades_today_from_journal():
    """Restores TODAY's already-confirmed real spend so a mid-day restart
    can never let _real_today_spent_inr reset to 0 and re-open budget that
    was already spent. Only applies if the journal's saved day is still
    today (IST) - a stale prior day's snapshot must never carry over."""
    if not os.path.exists(STATE_REAL_TRADES_TODAY_PATH):
        return
    try:
        with open(STATE_REAL_TRADES_TODAY_PATH) as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_REAL_TRADES_TODAY_PATH}: {e}")
        return
    today = ist_now().strftime("%Y-%m-%d")
    if saved.get("day") != today:
        return  # journal is from a previous day - today's spend genuinely starts at 0
    saved_spent = float(saved.get("spent_inr") or 0)
    if saved_spent <= 0:
        return
    with closing(get_db()) as conn:
        if _real_today_spent_inr(conn) >= saved_spent - 0.01:
            return  # already reflected (e.g. DB wasn't actually wiped this restart)
        _log_real_attempt(
            conn, "__reconciled__", "B", "confirmed", notional_inr=saved_spent,
            detail=f"restored today's already-spent Rs{saved_spent:.2f} from journal after a restart",
        )
    print(f"[reconcile] restored today's real spend (Rs{saved_spent:.2f}) from journal")


SCHEDULER_INTERVAL_SECONDS = 30
SCHEDULER_DAILY_RISK_PCT = 2.0  # DEFAULT (fallback) - account-wide daily loss cap, live-editable below
SCHEDULER_RR = 3.0  # DEFAULT (fallback) - 1:3 minimum reward:risk, live-editable below

# --- Live-editable thresholds (2026-09-07) ----------------------------------
# Explicit user instruction: "i want all of your constraints on the render
# web page so that i directly make changes for thresholds ... to make it go
# live immediately" - a value written to runtime_settings (see the CREATE
# TABLE above) takes effect on the VERY NEXT scheduler tick, no code push/
# redeploy at all. The module constants above (SCHEDULER_DAILY_RISK_PCT etc.)
# stay as DEFAULTS - what a fresh DB (first deploy, or a redeploy before
# anyone's ever changed a setting) starts with - and as the fallback if the
# runtime_settings row is ever missing/corrupt.
#
# Scope, deliberately limited: this covers the SCHEDULE-WIDE risk/pacing
# knobs (daily loss cap %, minimum reward:risk, entry-scan batch size), not
# WATCHLIST's ~2,600 per-symbol params (orb_minutes/sma_fast/slow/strategy
# per symbol) - that's a much bigger surface (thousands of values, one set
# per symbol) and "thresholds" most naturally reads as the account-wide
# risk knobs, not a per-symbol strategy editor. Flagged explicitly rather
# than silently narrowed.
RUNTIME_SETTINGS_META = {
    # key: (default, min, max, requires_real_money_token, description)
    "min_entry_confidence_pct": (
        TREND_WEAKENED_MIN_CONFIDENCE * 100, 50.0, 99.9, False,
        "Minimum statistical confidence (one-tailed normal-CDF read on the "
        "SMA(fast) vs SMA(slow) gap - see _trend_confidence) that the trend "
        "is real, required for a NEW orb_breakout entry (in addition to the "
        "breakout clearing ENTRY_BREAKOUT_MARGIN_PCT above the opening-range "
        "high). Lower = more entries taken on weaker/less-certain trend "
        "evidence; higher = fewer, more selective entries. Default 95% "
        "matches the same bar the early-exit 'trend weakened' check already "
        "trusts (TREND_WEAKENED_MIN_CONFIDENCE), but that exit-side constant "
        "is NOT changed by this setting - this only gates new entries.",
    ),
    "daily_risk_pct": (
        SCHEDULER_DAILY_RISK_PCT, 0.1, 10.0, False,
        "Account-wide daily loss cap, as % of capital. Once today's realized loss "
        "reaches this, all new entries halt for the rest of the day (open positions "
        "still get managed normally).",
    ),
    "rr": (
        SCHEDULER_RR, 1.0, 10.0, False,
        "Minimum reward:risk ratio (target distance / stop distance) required for "
        "a new entry to be taken at all. Also the step size the leading target "
        "extends by each time it re-qualifies (see _leading_target_extend).",
    ),
    "max_hold_minutes": (
        120.0, 15.0, 400.0, False,
        "Explicit user instruction 2026-09-08: a position that has hit neither "
        "its target nor its stop after this many minutes is exited anyway "
        "('stale_timeout') - capital stuck in a sideways-moving trade is capital "
        "unavailable for a better signal elsewhere. Only fires if target/stop/"
        "trend-weakened haven't already exited the trade first. Default 120 min "
        "(2h); NSE's own EOD square-off (~15:20 IST) still applies as the "
        "absolute last-resort cap regardless of this setting.",
    ),
    "entry_scan_batch_size": (
        # Literal, not a reference to SCHEDULER_ENTRY_SCAN_BATCH_SIZE below -
        # that constant is defined LATER in this file (module-level forward
        # references fail at import time in Python), so this default is kept
        # in sync by hand. Mirror any future change to that constant here too.
        35.0, 1.0, 500.0, False,
        "How many flat (no open position) symbols get scanned for a NEW entry per "
        "30s tick, round-robin. Higher = faster coverage of the full watchlist but "
        "more Yahoo Finance calls and longer tick time - see main.py's own comment "
        "above SCHEDULER_ENTRY_SCAN_BATCH_SIZE for the tradeoff math. Open positions "
        "are ALWAYS checked every tick regardless of this value.",
    ),
    "real_daily_cap_inr": (
        REAL_TRADING_DAILY_CAP_INR, 0.0, 1000000.0, True,
        "Maximum total REAL buy notional per IST calendar day, across all real "
        "orders. Real money - changing this requires the same Kotak API token as "
        "every other real-trading endpoint.",
    ),
    "real_fo_daily_cap_inr": (
        2000.0, 0.0, 1000000.0, True,
        "Maximum total REAL F&O premium spend (buy side only) per IST calendar "
        "day, across the single-leg call mirror and the Long Straddle - separate "
        "pool from real_daily_cap_inr (equity). Real money - requires the Kotak "
        "API token. Raise this (and fund the account) to actually enable F&O "
        "orders to place - check_margin_affordable's own live check is what "
        "ultimately decides affordability at the moment of each attempt.",
    ),
    "real_straddle_enabled": (
        0.0, 0.0, 1.0, True,
        "0/1 - whether the Long Straddle strategy (docs/STRATEGY_LOG.md, NOT YET "
        "BACKTESTED) is allowed to place REAL orders when its volatility-"
        "contraction signal fires. Paper-tracks regardless of this setting - "
        "turn this on only after reviewing paper results. Real money - requires "
        "the Kotak API token. Also requires REAL_FO_TRADING_ENABLED (Render env "
        "var) and real_fo_daily_cap_inr/margin affordability, same as every "
        "other real F&O order.",
    ),
    "daily_loss_reset_epoch": (
        0.0, 0.0, 4102444800.0, False,
        "Manual 'resume trading' override (2026-09-07 button, extended "
        "2026-09-07 second pass to the now-account-wide loss figure): a unix "
        "timestamp. Any trade - paper OR real - that closed BEFORE this "
        "moment no longer counts toward today's shared loss cap, so a click "
        "sets this to right now and immediately frees up the full budget "
        "again for the account-wide halt (today_realized_pnl/daily_summary), "
        "resuming on the very next scheduler tick. Deliberately does NOT "
        "touch _maybe_place_real_entry's OWN dedicated real-money loss gate "
        "(always checks the FULL day's real P&L, since_ts=None, ignoring this "
        "setting entirely) - a real loss already happened and can't be "
        "wished away; that specific gate has no reset button, on purpose, "
        "even though the shared display/halt figure now does. Self-limiting: "
        "since this is always compared against TODAY's own IST midnight via "
        "max(), a stale reset from a past day has zero effect once the day "
        "rolls over - no expiry logic needed.",
    ),
}

# runtime_settings external persistence (Upstash Redis) - 2026-09-09,
# explicit user finding: "When I updated batch per ticker to be from 35
# to 100, why it is getting reset to 35 again. Have u not made this
# overwrite previous value by taking input from front end?" They were
# right - the runtime_settings SQLite table (below) is exactly as
# ephemeral as every other table on this Render service (wiped on every
# restart, independent of any push), and unlike real_positions/rr_cursor/
# check_counts above, it had NO external mirror at all - EVERY value a
# user sets via POST /runtime-settings (batch size, daily_risk_pct, rr,
# min_entry_confidence_pct, max_hold_minutes, the real-money caps, etc.)
# silently reverted to RUNTIME_SETTINGS_META's hardcoded default on the
# next restart, no matter how recently it was changed. Same Upstash-
# mirror pattern as the others, applied here as one JSON snapshot of the
# WHOLE table (not per-key) - simpler, and means a stale single-key
# Upstash entry from a much older snapshot can never linger once any one
# setting gets written again.
_RUNTIME_SETTINGS_REDIS_KEY = "tv_paper_bot:runtime_settings:v1"


def _sync_runtime_settings_external(conn) -> None:
    """Call right after any runtime_settings write commits (see
    set_runtime_setting below). Best-effort and silent, same pattern as
    every other _sync_*_external above - a failure here must never break
    the settings write that's calling it."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return
    try:
        rows = conn.execute("SELECT key, value FROM runtime_settings").fetchall()
        snapshot = {r["key"]: r["value"] for r in rows}
        requests.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{_RUNTIME_SETTINGS_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            data=json.dumps(snapshot).encode("utf-8"),
            timeout=5,
        )
    except Exception as e:
        print(f"[runtime_settings_external] sync failed (non-fatal): {e}")


def hydrate_runtime_settings_from_external(conn) -> int:
    """Startup-time restore, sourced from Upstash - real-time, so any
    user-set override survives a restart at ANY cadence, not just ones
    the user happens to re-apply by hand afterward. Writes each restored
    key straight into the runtime_settings table via the same UPSERT
    set_runtime_setting itself uses, so get_runtime_setting's normal
    SQLite read path picks it up completely unchanged - no other code
    needs to know this restore happened. Silently skips any key no
    longer in RUNTIME_SETTINGS_META (a removed/renamed setting) rather
    than erroring. Returns how many keys were restored (0 if Upstash is
    unset/unreachable/empty/malformed)."""
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return 0
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{_RUNTIME_SETTINGS_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("result")
        if not raw:
            return 0
        snapshot = json.loads(raw)
        if not isinstance(snapshot, dict):
            return 0
    except Exception as e:
        print(f"[runtime_settings_external] hydrate failed (non-fatal): {e}")
        return 0

    restored = 0
    now = time.time()
    for key, value in snapshot.items():
        if key not in RUNTIME_SETTINGS_META:
            continue
        try:
            conn.execute(
                "INSERT INTO runtime_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, 'restored') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
                "updated_by=excluded.updated_by",
                (key, float(value), now),
            )
            restored += 1
        except (TypeError, ValueError):
            continue
    if restored:
        conn.commit()
    return restored


def _live_entry_scan_batch_size_for_display() -> int:
    """Small convenience wrapper for read-only status endpoints that don't
    already have a conn open (e.g. /scheduler-pipeline) - opens one just
    for this single lookup. Not used on the scheduler's own hot path (see
    _scheduler_loop, which reads live_batch_size once per tick already)."""
    with closing(get_db()) as conn:
        return int(get_runtime_setting(conn, "entry_scan_batch_size"))


def get_runtime_setting(conn, key: str) -> float:
    """Live value for one setting, falling back to RUNTIME_SETTINGS_META's
    default if no row exists yet (fresh DB) or the row is somehow missing.
    Cheap (one indexed lookup on a tiny table) - called once per scheduler
    tick, not per symbol, so this is not a hot-path concern."""
    default = RUNTIME_SETTINGS_META[key][0]
    row = conn.execute("SELECT value FROM runtime_settings WHERE key = ?", (key,)).fetchone()
    return float(row["value"]) if row else default


@app.get("/sentiment-signals")
def get_sentiment_signals():
    """What the sentiment gate (see sentiment_signals.py, wired into
    _auto_signal_core's entry check) currently sees - the parsed
    symbol->sentiment map, which day's file it came from (as_of_date can
    lag today if the external scan routine hasn't written today's first
    table yet), and the WATCHLIST->proxy mapping this app applies. No
    token gate - read-only, no account/order data, same precedent as
    /runtime-settings."""
    today_str = ist_now().strftime("%Y-%m-%d")
    data = sentiment_signals.get_latest_sentiment(today_str)
    proxies = {cfg["symbol"]: sentiment_signals.sentiment_proxy_for(cfg["symbol"]) for cfg in WATCHLIST}
    return {
        "today_ist_date": today_str,
        "as_of_date": data["as_of_date"],
        "source": data["source"],
        "signals": data["signals"],
        "watchlist_proxy_map": proxies,
    }


@app.get("/runtime-settings")
def get_runtime_settings():
    """Current effective value of every live-editable threshold, plus its
    default/min/max/description - what the trade-view constraints panel
    reads to render itself. No token gate (matches /trading-control's own
    precedent - this page's URL is the trust boundary for paper/scheduling
    controls); real_daily_cap_inr is readable here too but its WRITE path
    (see POST below) does require the token, same as every other real-
    money endpoint."""
    with closing(get_db()) as conn:
        return {
            key: {
                "value": get_runtime_setting(conn, key),
                "default": default, "min": lo, "max": hi,
                "requires_token": requires_token, "description": desc,
            }
            for key, (default, lo, hi, requires_token, desc) in RUNTIME_SETTINGS_META.items()
        }


@app.post("/runtime-settings")
def set_runtime_setting(request: Request, key: str, value: float):
    """Writes ONE setting, live - the very next scheduler tick reads it
    (see get_runtime_setting's call sites in _scheduler_loop). Bounds-
    checked against RUNTIME_SETTINGS_META so a typo (e.g. daily_risk_pct=
    200 meant as 2.00) can't silently arm a wildly wrong risk parameter.
    real_daily_cap_inr requires the same Kotak token as every other real-
    money endpoint (_require_kotak_token) - every other key does not,
    matching /trading-control's own no-gate precedent."""
    if key not in RUNTIME_SETTINGS_META:
        raise HTTPException(status_code=400, detail=f"unknown setting key: {key!r}")
    default, lo, hi, requires_token, desc = RUNTIME_SETTINGS_META[key]
    if requires_token:
        _require_kotak_token(request)
    if not (lo <= value <= hi):
        raise HTTPException(status_code=400, detail=f"{key} must be between {lo} and {hi} (got {value})")
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO runtime_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, 'user') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by",
            (key, value, time.time()),
        )
        conn.commit()
        # Real-time Upstash mirror (2026-09-09) - see
        # _sync_runtime_settings_external's own docstring for the exact
        # user-reported bug this closes ("batch per ticker... getting
        # reset to 35 again"). Without this, a value only ever lived in
        # this ephemeral SQLite table and reverted to its hardcoded
        # default on the next restart, no matter how recently it was set.
        _sync_runtime_settings_external(conn)
    return {"key": key, "value": value, "status": "saved", "effective": "next scheduler tick"}

# Real capital sourced from Kotak Neo (2026-09-04) - explicit user
# instruction: "fetch the actual capital it has and apply % limit on the
# trade." Replaces the old fixed SCHEDULER_CAPITAL = 400000 (a paper
# number) - live sizing now scales off the real account's actual
# available margin, via kotak_neo.limits()'s "Net" field (confirmed
# against a real account call 2026-09-04 - Kotak's own field name, not a
# guess).
#
# Cached with a TTL rather than fetched on every tick: the scheduler can
# call this up to SCHEDULER_ENTRY_SCAN_BATCH_SIZE times per 30s tick, and
# kotak_neo.login() is a REAL TOTP login against the live account each
# time - hammering that on every tick risks Kotak's own 429 rate limit
# (documented in its API) or looking like abuse on a real broker account.
# Capital doesn't move fast enough to need fresher than this anyway.
REAL_CAPITAL_CACHE_TTL_SECONDS = 600  # 10 min
_real_capital_cache = {"value": None, "fetched_at": 0.0, "error": None}


def _refresh_real_capital_cache():
    """Fetches real available capital from Kotak Neo and updates the
    module-level cache. Never raises - stores the error string instead, so
    a transient Kotak failure (network blip, session hiccup) doesn't crash
    a scheduler tick; get_scheduler_capital_inr() falls back to the last
    known good value."""
    try:
        import kotak_neo
        limits = kotak_neo.limits()
        net = float(limits["Net"])
        _real_capital_cache["value"] = net
        _real_capital_cache["fetched_at"] = time.time()
        _real_capital_cache["error"] = None
    except Exception as e:
        _real_capital_cache["error"] = str(e)


def get_scheduler_capital_inr() -> float:
    """Real capital for live position sizing, refreshed at most every
    REAL_CAPITAL_CACHE_TTL_SECONDS (see comment above for why not on every
    tick). Falls back to the last known cached value on a fresh-fetch
    failure. If there has never been a successful fetch at all (e.g.
    Kotak Neo not configured, or the very first tick after startup hasn't
    resolved yet), falls back to 0.0 - deliberately NOT the old fake
    Rs 4,00,000 paper number, since sizing real-shaped trades off a number
    that isn't real would defeat the entire point of this change. 0.0
    correctly sizes every trade to zero (no capital to risk) rather than
    silently trading on a fabricated balance."""
    age = time.time() - _real_capital_cache["fetched_at"]
    if _real_capital_cache["value"] is None or age > REAL_CAPITAL_CACHE_TTL_SECONDS:
        _refresh_real_capital_cache()
    return _real_capital_cache["value"] if _real_capital_cache["value"] is not None else 0.0


# --- Real daily-loss cap: fixed day-open capital basis, joint across
# equity + F&O (2026-09-08, explicit user instruction: "keep it as a % of
# total money available at the beginning of day. kotak balance") ------------
# Before this, real_loss_cap_inr (the account-wide daily-loss circuit
# breaker) was daily_risk_pct% of get_scheduler_capital_inr()'s LIVE,
# continuously-refreshing figure - so the cap itself drifted throughout
# the day as the account's own available balance moved (deployed capital,
# realized P&L, deposits), a moving target rather than a fixed risk
# ceiling set once against what was actually available this morning.
# Explicit user finding, same message: it must be a % of capital AS OF
# THE START OF THE DAY, captured once and held fixed - not the same as
# resetting the loss-COUNTING clock (daily_loss_reset_epoch, unchanged,
# still does that separately). Also, get_real_pnl_today_inr() was already
# account-wide (every Kotak position, any segment) - the cap-CHECK itself
# just hadn't been added to the F&O entry paths (_maybe_place_real_fo_call_entry,
# _straddle_signal_core), so "joint" wasn't actually enforced anywhere
# but equity. _real_loss_budget below is the one shared computation every
# real entry path (equity, F&O single-leg, F&O straddle) and both status
# endpoints now call, so the number a human sees is exactly the number
# gating trades.
_day_open_capital_cache: dict = {"day": None, "value": None}
_DAY_OPEN_CAPITAL_REDIS_KEY = "tv_paper_bot:day_open_capital:v1"


def _day_open_capital_inr(conn) -> float:
    """The real Kotak capital figure captured ONCE at the start of today
    (IST calendar day) and held fixed for every real-loss-cap check that
    day, across both equity and F&O - see the module comment above for
    the full reasoning. In-memory cache first (cheapest, correct for the
    common case of one long-running process); falls back to Upstash (a
    restart-surviving mirror, same family as real_positions/rr_cursor
    above) before ever re-capturing a fresh value, so a restart mid-day
    can never silently reset the day's own risk ceiling to whatever the
    live balance happens to be at that moment - the whole point of fixing
    it in the first place. Only captures fresh (and only then persists to
    Upstash) when neither cache has today's value yet."""
    today = ist_now().strftime("%Y-%m-%d")
    if _day_open_capital_cache["day"] == today and _day_open_capital_cache["value"] is not None:
        return _day_open_capital_cache["value"]

    if UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_REST_URL}/get/{_DAY_OPEN_CAPITAL_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
                timeout=10,
            )
            resp.raise_for_status()
            raw = resp.json().get("result")
            if raw:
                saved = json.loads(raw)
                if saved.get("day") == today and saved.get("value") is not None:
                    _day_open_capital_cache["day"] = today
                    _day_open_capital_cache["value"] = float(saved["value"])
                    return _day_open_capital_cache["value"]
        except Exception as e:
            print(f"[day_open_capital] hydrate failed (non-fatal): {e}")

    value = get_scheduler_capital_inr()
    _day_open_capital_cache["day"] = today
    _day_open_capital_cache["value"] = value
    if UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN:
        try:
            requests.post(
                f"{UPSTASH_REDIS_REST_URL}/set/{_DAY_OPEN_CAPITAL_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
                data=json.dumps({"day": today, "value": value}).encode("utf-8"),
                timeout=5,
            )
        except Exception as e:
            print(f"[day_open_capital] sync failed (non-fatal): {e}")
    print(f"[day_open_capital] captured Rs{value:.2f} for {today}")
    return value


def _real_loss_budget(conn) -> dict:
    """Single source of truth for the joint (equity + F&O together) real
    daily-loss cap - see the module comment above _day_open_capital_cache.
    Every real entry path (equity, F&O single-leg, F&O straddle) and both
    status endpoints (/real-trading-control, /kotak-neo/real-fo-control)
    call this, so the number a human sees is exactly the number gating
    trades. Returns {'ok', 'real_pnl_today', 'cap_inr',
    'day_open_capital_inr', 'detail'} - 'ok' is False on either an
    unknown P&L (fails closed, matches get_real_pnl_today_inr's own
    "can't verify, don't trade" contract - real_pnl_today is None in that
    case) or the cap being breached."""
    real_pnl_today = get_real_pnl_today_inr()
    day_open_capital = _day_open_capital_inr(conn)
    cap_inr = day_open_capital * get_runtime_setting(conn, "daily_risk_pct") / 100
    if real_pnl_today is None:
        return {
            "ok": False, "real_pnl_today": None, "cap_inr": cap_inr,
            "day_open_capital_inr": day_open_capital,
            "detail": f"could not fetch real P&L from Kotak: {_real_trades_cache['error']}",
        }
    if -real_pnl_today >= cap_inr:
        return {
            "ok": False, "real_pnl_today": real_pnl_today, "cap_inr": cap_inr,
            "day_open_capital_inr": day_open_capital,
            "detail": f"real P&L today Rs{real_pnl_today:.2f} vs joint cap Rs{cap_inr:.2f} "
                      f"({get_runtime_setting(conn, 'daily_risk_pct')}% of Rs{day_open_capital:.2f} "
                      f"day-open capital)",
        }
    return {
        "ok": True, "real_pnl_today": real_pnl_today, "cap_inr": cap_inr,
        "day_open_capital_inr": day_open_capital, "detail": None,
    }


# REAL account P&L, sourced from Kotak's own positions() call - added
# 2026-09-07. Explicit user finding: "when ur data had been in sync with
# kotak then it would have seen the live trades and taken the wise step
# for the 2% calculations" - today_realized_pnl/daily_summary (further up
# this file) only ever tracked PAPER P&L, even though the daily loss cap
# is sized off REAL capital; this account had zero awareness of real P&L
# from ANY source (this bot's own real orders, or - as happened today -
# ~25 trades placed directly on Kotak, net -Rs41.60, invisible to this
# app's real_trades table since that only logs orders THIS code places).
#
# Ground truth instead of our own bookkeeping: sums (sellAmt - buyAmt)
# across every FULLY SQUARED-OFF position (flBuyQty == flSellQty, i.e.
# net-flat/realized, not an open one) Kotak's positions() returns -
# confirmed live 2026-09-07 to return only the CURRENT day's activity
# (every row's hsUpTm was today's date); hsUpTm is defensively re-checked
# against today's IST date anyway in case that assumption is ever wrong.
# Manually verified against this exact account 2026-09-07: this formula's
# total matched the user's own reported real loss (-Rs41.60) exactly.
REAL_PNL_CACHE_TTL_SECONDS = 300  # 5 min - same reasoning as REAL_CAPITAL_CACHE_TTL_SECONDS
# (avoid hammering Kotak's login/positions call every tick), just shorter
# since P&L changes faster than available capital and this gates every
# new real entry, not just position sizing.
#
# 2026-09-07 (second pass): refactored from a single cached total into a
# cached LIST of individual closed-trade dicts - explicit user instruction
# ("all data remains in sync with kotak transaction details... these two
# must match") needs the account-wide daily-loss figure (today_realized_pnl/
# daily_summary) to read REAL P&L too, but respecting the PAPER-only
# manual reset point (daily_loss_reset_epoch - see that key's own
# RUNTIME_SETTINGS_META entry) for THAT figure specifically, while
# _maybe_place_real_entry's own real-money gate must NOT be resettable
# (a real loss can't be wished away). Caching the raw trade list lets both
# read paths filter by their own since_ts without hitting Kotak twice, and
# /real-trades-today can reuse the exact same cache instead of its own
# separate positions() call.
_real_trades_cache = {"value": None, "fetched_at": 0.0, "error": None, "day": None}


def _refresh_real_trades_cache():
    """Never raises - stores the error string instead, same pattern as
    _refresh_real_capital_cache, so a transient Kotak failure can't crash
    a scheduler tick. See the module comment above _real_trades_cache for
    the full reasoning; this formula was manually verified against the
    live account 2026-09-07 - its total matched the user's own reported
    real loss (-Rs41.60) exactly."""
    try:
        import kotak_neo
        positions = kotak_neo.positions()
        rows = positions.get("data") or [] if isinstance(positions, dict) else []
        today_str = ist_now().strftime("%Y/%m/%d")  # Kotak's own hsUpTm format
        trades = []
        for row in rows:
            try:
                if row.get("exSeg") != "nse_cm":
                    continue
                fl_buy = float(row.get("flBuyQty", 0) or 0)
                fl_sell = float(row.get("flSellQty", 0) or 0)
                if fl_buy == 0 or fl_buy != fl_sell:
                    continue  # not fully squared off - open/unrealized, not today's realized P&L
                hs_up_tm = str(row.get("hsUpTm", ""))
                if not hs_up_tm.startswith(today_str):
                    continue
                buy_amt = float(row.get("buyAmt", 0) or 0)
                sell_amt = float(row.get("sellAmt", 0) or 0)
                qty = fl_buy
                # hsUpTm is Kotak's own IST wall-clock string - convert to
                # a UTC epoch so since_ts filtering (IST-midnight-based,
                # like every other "today" cutoff in this file) compares
                # correctly.
                exit_dt_ist = dt.datetime.strptime(hs_up_tm, "%Y/%m/%d %H:%M:%S")
                exit_time_utc = (exit_dt_ist - dt.timedelta(minutes=IST_OFFSET_MIN)).replace(
                    tzinfo=dt.timezone.utc).timestamp()
                trades.append({
                    "symbol": row.get("trdSym") or row.get("sym"), "exit_time_utc": exit_time_utc,
                    "entry_price_native": round(buy_amt / qty, 2) if qty else None,
                    "exit_price_native": round(sell_amt / qty, 2) if qty else None,
                    "qty": qty, "pnl_inr": round(sell_amt - buy_amt, 2),
                })
            except (TypeError, ValueError):
                continue
        _real_trades_cache["value"] = trades
        _real_trades_cache["fetched_at"] = time.time()
        _real_trades_cache["error"] = None
        _real_trades_cache["day"] = ist_now().strftime("%Y-%m-%d")
    except Exception as e:
        _real_trades_cache["error"] = str(e)


def get_real_trades_today_list():
    """Every closed real trade today, Kotak's own ground truth (list of
    dicts - symbol/exit_time_utc/entry_price_native/exit_price_native/
    qty/pnl_inr). None if never successfully fetched. Force-refreshes on
    an IST day rollover so yesterday's list is never carried into today
    by an unlucky cache hit, same discipline as every other "today"
    figure in this file."""
    today_str = ist_now().strftime("%Y-%m-%d")
    age = time.time() - _real_trades_cache["fetched_at"]
    if _real_trades_cache["value"] is None or age > REAL_PNL_CACHE_TTL_SECONDS or _real_trades_cache["day"] != today_str:
        _refresh_real_trades_cache()
    return _real_trades_cache["value"]


def get_real_pnl_today_inr(since_ts: float | None = None):
    """TODAY's real realized P&L across the WHOLE Kotak account - bot-
    placed and manually-placed trades alike, not just what this app's own
    real_trades table happens to know about. Returns None if never
    successfully fetched - callers gating a new REAL entry (see
    _maybe_place_real_entry) MUST call this with since_ts=None (the
    default) and treat None as "can't verify, don't trade" - that gate is
    deliberately never resettable, a real loss can't be wished away.

    since_ts, if given, filters to trades at/after that UTC epoch - used
    ONLY by the account-wide daily-loss display/halt (today_realized_pnl/
    daily_summary), which DOES respect the PAPER-only manual reset button
    (daily_loss_reset_epoch) now that it reads real P&L too."""
    trades = get_real_trades_today_list()
    if trades is None:
        return None
    if since_ts is not None:
        trades = [t for t in trades if t["exit_time_utc"] >= since_ts]
    return sum(t["pnl_inr"] for t in trades)


def get_real_capital_deployed_inr() -> float | None:
    """Real notional currently tied up in OPEN (not fully squared-off)
    Kotak positions - added 2026-09-08 to explain a real user confusion:
    "REAL LOSS BUDGET LEFT (KOTAK) Rs4.06 - this info is wrong... how can
    this budget be decreased for today" when real_pnl_today_inr was
    correctly 0 (no trade had closed). The cap wasn't decreased by a
    loss - it's 2% of get_scheduler_capital_inr()'s AVAILABLE (post-
    deployment) capital, which was small because most of the account's
    money was already sitting in open positions, not lost. This figure
    is that "already deployed, not lost" piece, so the UI can show both
    together instead of a single number that reads as a loss either way.
    Reuses the same positions() call/shape already verified in
    _refresh_real_trades_cache (buyAmt/flBuyQty/flSellQty), just the
    OPPOSITE filter: NOT fully squared off = still open. Returns None on
    a fetch failure (matches get_real_pnl_today_inr's None-on-failure
    convention) rather than fabricating 0."""
    try:
        import kotak_neo
        positions = kotak_neo.positions()
        rows = positions.get("data") or [] if isinstance(positions, dict) else []
    except Exception:
        return None
    total = 0.0
    for row in rows:
        try:
            if row.get("exSeg") != "nse_cm":
                continue
            fl_buy = float(row.get("flBuyQty", 0) or 0)
            fl_sell = float(row.get("flSellQty", 0) or 0)
            if fl_buy == 0 or fl_buy == fl_sell:
                continue  # 0 qty, or fully squared off - not an open position
            total += float(row.get("buyAmt", 0) or 0) - float(row.get("sellAmt", 0) or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


_scheduler_last_tick_ts = 0.0
_scheduler_last_error = None
# Latest _auto_signal_core result per symbol, from the real scheduler tick
# (not a synthetic re-check) - exposed via /scheduler-attempts so there's
# real visibility into what the engine actually decided and why, not just
# closed trades. journal-sync.yml snapshots this into a durable, growing
# attempt log each sync.
_scheduler_last_results: dict = {}

# Round-robin cursor into WATCHLIST for entry-scanning "flat" symbols (no
# open position) - persists across ticks. 2026-09-03: the watchlist grew
# from 9 to 21 symbols (+ 15 options underlyings) in one session; scanning
# every single one, every 30s tick, on Yahoo Finance's free/unofficial
# endpoint risks tripping rate limits and can make one tick's real wall-
# clock time exceed SCHEDULER_INTERVAL_SECONDS, silently degrading the
# actual check cadence for everyone as the roster grows. Round-robin fixes
# this without losing coverage: an open position is ALWAYS checked every
# tick (time-critical - stop/target/eod), and flat symbols rotate through
# a bounded batch per tick instead of all being scanned every time.
_scheduler_rr_cursor = 0
SCHEDULER_ENTRY_SCAN_BATCH_SIZE = 35  # flat symbols freshly entry-scanned per tick, round-robin -
# bumped from 12 -> 35 on 2026-09-04, explicit user instruction, after the
# watchlist grew from 103 to ~2,644 symbols (Kotak-sourced full NSE EQ
# universe - see NSE_FULL_UNIVERSE above). Full rotation at 35:
# ~2644/35 ~= 76 ticks ~= ~38 min (was ~110 min at the old batch=12 before
# this bump, and would be ~4.3 min if the watchlist were still 103 names -
# rotation speed depends on BOTH the batch size and watchlist size, always
# recompute together). Each symbol in the batch is one sequential
# (not parallel - see _scheduler_loop's for loop) Yahoo Finance fetch +
# pandas compute, so this also raises worst-case tick wall-clock time -
# watch /scheduler-status's last_tick_ago_seconds (should stay near
# SCHEDULER_INTERVAL_SECONDS=30) and last_error after this change; if
# ticks start backing up or Yahoo starts erroring, that's this constant's
# fault first.

# Live pipeline visibility for /scheduler-pipeline (trade-view's scanner
# panel) - what's actively in flight right now, not just the last completed
# result. _scheduler_currently_checking is set right before the blocking
# call and cleared right after, so a poll mid-tick shows the real in-flight
# symbol; None means the loop is between ticks (sleeping).
_scheduler_currently_checking: dict | None = None

# How many times each symbol/underlying has actually been checked TODAY
# (IST calendar day, same "day" boundary as the rest of the account -
# ist_midnight_epoch) - for /trade-view's per-asset check-count table.
# In-memory during the process's own life (cheap - bumped up to
# entry_scan_batch_size times per 30s tick, no DB/file write on that hot
# path), but RESTORED from a durable journal snapshot on startup (see
# reconcile_scheduler_check_counts_from_journal below) - 2026-09-07,
# explicit user finding: "'checks today' is not showing all the count of
# checks done today. so it should not be depending on the memory of the
# render account. but keep it fetched at the start of the render
# session." Before this fix, a redeploy (this session alone triggered
# several today) reset the displayed count to zero even though the
# checks genuinely happened earlier the same day - same class of bug as
# the daily P&L reset fixed earlier today, same fix shape: durable
# journal on write, restored on startup, never trusted to survive purely
# in the process's own memory.
_scheduler_check_counts: dict = {}
_scheduler_check_counts_day: str = ""

STATE_SCHEDULER_CHECK_COUNTS_PATH = os.path.join(os.path.dirname(__file__), "state", "scheduler_check_counts.json")


def reconcile_scheduler_check_counts_from_journal():
    """Restores today's per-symbol check counts from the durable journal
    on startup - see the module comment above _scheduler_check_counts for
    why. journal-sync.yml writes state/scheduler_check_counts.json from
    the live /scheduler-pipeline check_counts_today every sync. Only
    restores if the saved day matches today's IST date - a stale prior-
    day snapshot must never carry over, counts genuinely reset each day
    (same rollover rule _record_scheduler_check itself already applies).

    Also restores the round-robin scan CURSOR (2026-09-08) - explicit
    user finding: "still stuck 358 distinct... how to ensure it can scan
    all 2661 every 15 minutes." Root cause: _scheduler_rr_cursor (below)
    was a plain in-memory global, same class of bug as check-counts used
    to be before the 2026-09-07 fix above - every restart reset it to 0,
    so the round-robin ALWAYS restarted from the very beginning of
    WATCHLIST's flat-symbol ordering. On a day with many restarts (this
    session alone triggered several today, on top of Render's own memory-
    limit restart), the cursor kept getting reset before a single full
    lap (2661/35 ~= 76 ticks ~= ~38 min at the current batch size) could
    ever complete - it was never actually stuck, it just kept re-scanning
    the same first ~358 symbols in WATCHLIST's order every time. UNLIKE
    the day-scoped counts above, the cursor is restored regardless of the
    saved day - a scan position is a rotation-through-the-list concept,
    not a per-day counter, so there's no reason to reset it at midnight."""
    global _scheduler_check_counts_day, _scheduler_rr_cursor
    if not os.path.exists(STATE_SCHEDULER_CHECK_COUNTS_PATH):
        return
    try:
        with open(STATE_SCHEDULER_CHECK_COUNTS_PATH) as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[reconcile] could not read {STATE_SCHEDULER_CHECK_COUNTS_PATH}: {e}")
        return

    # Only fires when the cursor is still at its just-started default (0) -
    # i.e. Upstash (see hydrate_rr_cursor_from_external, called first in
    # the startup sequence) was unset, unreachable, or genuinely had
    # nothing yet. A fresher Upstash-restored value must never be
    # clobbered by this slower, up-to-~15-min-stale git journal.
    rr_cursor = saved.get("rr_cursor")
    if _scheduler_rr_cursor == 0 and isinstance(rr_cursor, int) and rr_cursor > 0:
        _scheduler_rr_cursor = rr_cursor
        print(f"[reconcile] restored round-robin cursor to {rr_cursor} from journal")

    today_str = ist_now().strftime("%Y-%m-%d")
    if saved.get("day") != today_str:
        return  # yesterday's (or older) snapshot - today's COUNTS start fresh, same as any other day-rollover
    counts = saved.get("counts") or {}
    # Only fires when Upstash (hydrate_check_counts_from_external, called
    # first in the startup sequence - see its own docstring, 2026-09-09)
    # left this dict still empty - i.e. was unset, unreachable, or
    # genuinely had nothing yet. A fresher Upstash-restored dict must
    # never be clobbered by this slower, up-to-~15-min-stale git journal -
    # same guard shape as the rr_cursor restore above.
    if counts and not _scheduler_check_counts:
        _scheduler_check_counts.update(counts)
        _scheduler_check_counts_day = today_str
        print(f"[reconcile] restored {len(counts)} symbol check-count(s) from journal")


def _record_scheduler_check(key: str):
    """Bumps key's today-count, resetting everyone's count first if the
    IST calendar day has rolled over since the last check."""
    global _scheduler_check_counts_day
    today_str = ist_now().strftime("%Y-%m-%d")
    if today_str != _scheduler_check_counts_day:
        _scheduler_check_counts.clear()
        _scheduler_check_counts_day = today_str
    _scheduler_check_counts[key] = _scheduler_check_counts.get(key, 0) + 1


def _scheduler_peek_next_batch(n: int = 5) -> list:
    """What the round-robin will scan on its NEXT turn through the flat
    (no open position) symbols, without mutating the real cursor - a pure
    peek, safe to call from an HTTP handler at any time. Mirrors the same
    selection _scheduler_loop itself uses, off the CURRENT (already-
    advanced-past-this-tick) cursor position."""
    with closing(get_db()) as conn:
        open_equity_symbols = {
            r["symbol"] for r in conn.execute(
                "SELECT symbol FROM signal_state WHERE status = 'long'"
            ).fetchall()
        }
    flat_symbols = [cfg["symbol"] for cfg in WATCHLIST if cfg["symbol"] not in open_equity_symbols]
    if not flat_symbols:
        return []
    m = len(flat_symbols)
    count = min(n, m)
    return [flat_symbols[(_scheduler_rr_cursor + i) % m] for i in range(count)]


def _market_open_for_cfg(cfg: dict) -> bool:
    """Cheap, no-network check: is THIS WATCHLIST symbol's own market open
    right now? Mirrors the exact same weekday/open_min/close_min gate
    _auto_signal_core/_options_signal_core already apply per-call (this
    does NOT replace those - they still make the real entry/exit
    decision).

    NOT called from _scheduler_tick's round-robin pool any more as of
    2026-09-08 (explicit user instruction: scan the full 2661-symbol
    watchlist around the clock whenever the trading toggle is ON, so the
    distinct-scanned coverage counter isn't capped by each symbol's own
    market hours) - kept here, unused, in case a future change wants a
    market-hours-aware pool again; _auto_signal_core/_options_signal_core
    still gate the actual entry/exit decision independently either way.

    Explicit user instruction (2026-09-07): "you also know the market
    timing of all the asset classes. accordingly iterate your search or
    monitoring and only on those market open asset classes... right now
    only commodity segment should be active and at 9:30am all assets
    should be tradable." Before this, the round-robin batch drew from
    the FULL watchlist regardless of hours - _auto_signal_core already
    short-circuits a closed symbol before any network fetch (so this
    wasn't burning Yahoo calls), but it DID mean scan slots were spent
    cycling through ~2,600 closed NSE symbols during NSE-closed hours
    instead of concentrating on the handful of assets (currently just
    the 3 near-24h MCX proxies) that are actually open - and conversely,
    NSE symbols left mid-rotation when the market closes don't jump the
    queue the moment it reopens; they wait their normal turn. Filtering
    the POOL by market hours fixes both: during closed hours the pool
    shrinks to what's genuinely tradeable (fast, relevant rotation);
    the moment a market opens, its symbols re-enter the pool and get
    picked up on the very next ticks rather than waiting out whatever
    position the cursor happened to be in."""
    now_local = dt.datetime.utcnow() + dt.timedelta(minutes=cfg.get("tz_offset_min", IST_OFFSET_MIN))
    mins_now = now_local.hour * 60 + now_local.minute
    if not cfg.get("trade_weekends", False) and now_local.weekday() >= 5:
        return False
    return cfg.get("open_min", 0) <= mins_now <= cfg.get("close_min", 1439)


async def _scheduler_loop():
    """Resilient wrapper (2026-09-08, found live - see _scheduler_tick's
    own docstring for the real incident this fixes) - the ENTIRE tick used
    to run directly inside this function's `while True:`, with no top-
    level exception handling. Every individual symbol's own check was
    already isolated in its own try/except, but the DB/threshold setup at
    the START of a tick (before any per-symbol block) was NOT - a single
    unhandled exception there (a bad runtime_setting value, a transient
    DB error, anything) would propagate out of this fire-and-forget
    asyncio.create_task, silently killing the ENTIRE scheduler forever -
    no more ticks, ever, until Render's next restart. Exactly matches a
    real incident: "checks today is even less than 1 after 75 min of
    market open" - the loop had died and nothing was left to notice or
    restart it. Now the whole tick body lives in _scheduler_tick() and
    THIS function is the only thing that can never die - any exception
    from a tick, wherever it originates, is caught, recorded, and the
    loop resumes on the very next iteration instead of stopping."""
    global _scheduler_last_error
    while True:
        try:
            await _scheduler_tick()
        except Exception as e:
            _scheduler_last_error = f"TICK CRASHED (recovered): {e}"
            print(f"[scheduler] tick crashed, would have killed the whole loop before this fix: {e}")
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


async def _scheduler_tick():
    global _scheduler_last_tick_ts, _scheduler_rr_cursor, _scheduler_currently_checking
    watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in WATCHLIST}

    with closing(get_db()) as conn:
        open_equity_symbols = {
            r["symbol"] for r in conn.execute(
                "SELECT symbol FROM signal_state WHERE status = 'long'"
            ).fetchall()
        }
        open_option_underlyings = {
            r["underlying"] for r in conn.execute(
                "SELECT underlying FROM option_state"
            ).fetchall()
        }
        trading_paused = not is_trading_enabled(conn)
        # Live thresholds (see RUNTIME_SETTINGS_META/get_runtime_setting
        # above) - read once per tick here, not per symbol, same reasoning
        # as scheduler_capital_inr below. A value saved via POST
        # /runtime-settings is picked up on the VERY NEXT tick.
        live_daily_risk_pct = get_runtime_setting(conn, "daily_risk_pct")
        live_rr = get_runtime_setting(conn, "rr")
        live_batch_size = int(get_runtime_setting(conn, "entry_scan_batch_size"))
        live_min_entry_confidence_pct = get_runtime_setting(conn, "min_entry_confidence_pct")
        live_max_hold_minutes = get_runtime_setting(conn, "max_hold_minutes")

    # When paused, don't waste a Yahoo Finance call scanning flat
    # symbols for a NEW entry nobody wants right now - _auto_signal_core/
    # _options_signal_core would reject it anyway (trading_paused), this
    # just skips the round-robin batch itself. Open positions are NEVER
    # gated by this - they still get checked every tick regardless
    # (see symbols_this_tick below), same as always.
    all_symbols = [cfg["symbol"] for cfg in WATCHLIST]
    # Full-universe pool, NOT market-hours-filtered (explicit user
    # instruction, 2026-09-08: "make this [361/2661 distinct scanned]
    # running for whole 24 hour if the trading toggle is ON" - i.e. the
    # round-robin must cycle through all 2661 watchlist symbols around
    # the clock whenever the global trading toggle is on, so the
    # distinct-scanned coverage counter can reach the full watchlist in
    # a day rather than being capped by each symbol's own market hours.
    # This reverses the 2026-09-07 market-hours pool filter (see the now
    # UNUSED _market_open_for_cfg's own docstring for that reasoning) -
    # confirmed via AskUserQuestion the tradeoff (scan slots spent on
    # symbols whose market is currently shut, where _auto_signal_core/
    # _options_signal_core will just no-op past the same market-hours
    # gate before any entry decision) is accepted. An open position is
    # NEVER gated by this (open_equity_symbols/open_option_underlyings
    # below are unconditional) - only the round-robin's flat-symbol scan
    # pool composition changed.
    flat_symbols = [] if trading_paused else [
        s for s in all_symbols if s not in open_equity_symbols
    ]
    if flat_symbols:
        n = len(flat_symbols)
        batch_size = min(live_batch_size, n)
        rr_batch = [flat_symbols[(_scheduler_rr_cursor + i) % n] for i in range(batch_size)]
        _scheduler_rr_cursor = (_scheduler_rr_cursor + batch_size) % n
        _sync_rr_cursor_external(_scheduler_rr_cursor)
    else:
        rr_batch = []

    # Always: every symbol with an open equity position (time-critical
    # stop/target/eod check) + every underlying with an open option
    # position (same reason, for the overlay below) + this tick's
    # round-robin entry-scan batch of otherwise-flat symbols.
    symbols_this_tick = open_equity_symbols | open_option_underlyings | set(rr_batch)

    # Hoisted once per tick, not per symbol - get_scheduler_capital_inr()
    # is TTL-cached internally anyway, but this avoids re-checking cache
    # freshness once per symbol in the loop below for no benefit.
    scheduler_capital_inr = get_scheduler_capital_inr()

    for symbol in symbols_this_tick:
        cfg = watchlist_by_symbol.get(symbol)
        if not cfg:
            continue
        _scheduler_currently_checking = {
            "symbol": symbol, "kind": "equity", "started_at_utc": time.time(),
        }
        _record_scheduler_check(symbol)
        try:
            result = await asyncio.to_thread(
                _auto_signal_core,
                symbol=cfg["symbol"], capital=scheduler_capital_inr,
                daily_risk_pct=live_daily_risk_pct,
                risk_per_trade_pct=cfg["risk_pct"],
                stop_pct=cfg["stop_pct"], rr=live_rr,
                orb_minutes=cfg["orb_minutes"], sma_fast=cfg["sma_fast"], sma_slow=cfg["sma_slow"],
                interval="5m", tz_offset_min=cfg["tz_offset_min"], open_min=cfg["open_min"],
                close_min=cfg["close_min"], squareoff_min=cfg["squareoff_min"],
                trade_weekends=cfg["trade_weekends"], currency=cfg["currency"],
                strategy=cfg.get("strategy", "orb_breakout"),
                trend_sma=cfg.get("trend_sma", 0), volume_confirm=cfg.get("volume_confirm", False),
                min_entry_confidence_pct=live_min_entry_confidence_pct,
                max_hold_minutes=live_max_hold_minutes,
                # 2026-09-09, explicit user instruction: "stop using SMA
                # and replace it with EMA with immediate effect
                # everywhere" - THIS is the live scheduler's own call
                # site, the one that actually decides every real WATCHLIST
                # symbol's trend read; a per-symbol "ma_type" WATCHLIST
                # field still overrides this fallback if ever set.
                ma_type=cfg.get("ma_type", "ema"),
            )
            _scheduler_last_results[cfg["symbol"]] = {"checked_at_utc": time.time(), **result}

            # Stage 3: mirror this SAME decision as a real order, only
            # for the equity path (options/MCX are out of stage 3 v1 -
            # explicit user instruction). Deliberately AFTER the paper
            # result is already recorded, in its own try/except that
            # can never propagate - a real-order hiccup must never look
            # like a paper-trading scheduler failure or block the next
            # symbol's tick.
            try:
                action_taken = result.get("action_taken", "")
                if action_taken == "entered_long":
                    with closing(get_db()) as real_conn:
                        _maybe_place_real_entry(real_conn, cfg["symbol"])
                elif action_taken.startswith("exited_"):
                    with closing(get_db()) as real_conn:
                        _maybe_place_real_exit(real_conn, cfg["symbol"])
                else:
                    # Position still open (or never was one) - sync any
                    # real resting stop-loss to the paper trail's latest
                    # level. A no-op unless a real position is actually
                    # open for this symbol (see _maybe_sync_real_stop_loss).
                    with closing(get_db()) as real_conn:
                        _maybe_sync_real_stop_loss(real_conn, cfg["symbol"])
            except Exception as e:
                print(f"[real_orders] unexpected error for {cfg['symbol']}: {e}")

            # Real F&O (2026-09-07, extended to MCX same day per
            # explicit user instruction "also mcx") - NIFTY/BANKNIFTY/
            # GC=F/SI=F/CL=F only (see _INDEX_TO_FO_UNDERLYING). Same
            # isolation principle: its
            # own try/except, never able to break the equity mirror
            # above or the next symbol's tick.
            try:
                if cfg["symbol"] in _INDEX_TO_FO_UNDERLYING:
                    fo_underlying = _INDEX_TO_FO_UNDERLYING[cfg["symbol"]]
                    if action_taken == "entered_long":
                        with closing(get_db()) as fo_conn:
                            _maybe_place_real_fo_call_entry(fo_conn, cfg["symbol"], result.get("last_close"))
                    elif action_taken.startswith("exited_"):
                        with closing(get_db()) as fo_conn:
                            _maybe_place_real_fo_call_exit(fo_conn, cfg["symbol"])
                    with closing(get_db()) as fo_conn:
                        _straddle_signal_core(
                            fo_conn, fo_underlying, result.get("vol_contraction_signal"),
                            result.get("halted_for_day", False), result.get("is_squareoff_time", False),
                            result.get("last_close"),
                        )
            except Exception as e:
                print(f"[real_fo_orders] unexpected error for {cfg['symbol']}: {e}")
        except Exception as e:
            _scheduler_last_error = f"{cfg['symbol']}: {e}"
            _scheduler_last_results[cfg["symbol"]] = {
                "checked_at_utc": time.time(), "symbol": cfg["symbol"],
                "status": "error", "detail": str(e),
            }
        finally:
            _scheduler_currently_checking = None

    # Options overlay - real calls/puts on the symbols with a live
    # yfinance chain (OPTIONS_ELIGIBLE_SYMBOLS), using that same
    # symbol's own WATCHLIST session config (hours/tz/currency) so it
    # follows the same market clock as the equity engine on that ticker.
    # Covers the SAME symbols_this_tick set as the equity loop above
    # (open positions + this tick's round-robin batch) - not a
    # separate schedule - so a symbol's OHLC fetch (fetch_ohlc, cached
    # 180s) is shared between the two checks instead of doubling the
    # network calls for symbols that are both an equity WATCHLIST entry
    # and options-eligible.
    for underlying in OPTIONS_ELIGIBLE_SYMBOLS:
        if underlying not in symbols_this_tick:
            continue
        cfg = watchlist_by_symbol.get(underlying)
        if not cfg:
            continue
        key = f"{underlying}:OPT"
        _scheduler_currently_checking = {
            "symbol": key, "kind": "options", "started_at_utc": time.time(),
        }
        _record_scheduler_check(key)
        try:
            result = await asyncio.to_thread(
                _options_signal_core,
                underlying=underlying, capital=scheduler_capital_inr,
                daily_risk_pct=live_daily_risk_pct,
                risk_per_trade_pct=cfg["risk_pct"], rr=live_rr,
                trend_sma=cfg.get("trend_sma", 20),
                tz_offset_min=cfg["tz_offset_min"], open_min=cfg["open_min"],
                close_min=cfg["close_min"], squareoff_min=cfg["squareoff_min"],
                trade_weekends=cfg["trade_weekends"], currency=cfg["currency"],
            )
            _scheduler_last_results[key] = {"checked_at_utc": time.time(), **result}
        except Exception as e:
            _scheduler_last_results[key] = {
                "checked_at_utc": time.time(), "underlying": underlying,
                "status": "error", "detail": str(e),
            }
        finally:
            _scheduler_currently_checking = None

    # Once per tick (not per symbol - see _CHECK_COUNTS_REDIS_KEY's own
    # module comment for why), after every check this tick has made -
    # keeps the "distinct scanned" dict surviving a restart at ANY
    # cadence, not just ones slower than journal-sync's 15-min interval.
    _sync_check_counts_external(_scheduler_check_counts_day, _scheduler_check_counts)

    _scheduler_last_tick_ts = time.time()
    await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_scheduler():
    # runtime_settings: Upstash-restore FIRST, before anything else reads
    # a live setting (the scheduler tick below, any endpoint) - see
    # hydrate_runtime_settings_from_external's own docstring for the
    # 2026-09-09 bug this closes.
    with closing(get_db()) as _settings_conn:
        _restored_settings = hydrate_runtime_settings_from_external(_settings_conn)
        if _restored_settings:
            print(f"[runtime_settings_external] restored {_restored_settings} setting(s) from Upstash")
    # real_t1_restricted: same Upstash-first restore, before any real
    # entry gate could otherwise re-attempt a symbol already confirmed
    # T1/T2T-restricted on a prior restart - see hydrate_t1_restricted_
    # from_external's own docstring for the 2026-09-09 bug this closes.
    with closing(get_db()) as _t1_conn:
        _restored_t1 = hydrate_t1_restricted_from_external(_t1_conn)
        if _restored_t1:
            print(f"[t1_restricted_external] restored {_restored_t1} restriction(s) from Upstash")
    reconcile_open_positions_from_journal()
    reconcile_trading_control_from_journal()
    reconcile_real_trading_control_from_journal()
    # Upstash first - real-time and authoritative once configured, so its
    # read (even an EMPTY one) wins outright over the git journal below,
    # which only runs as a fallback when Upstash was unset or unreachable.
    # BUG found live 2026-09-08: running the journal fallback
    # unconditionally resurrected positions Upstash had already, correctly,
    # recorded as ghost-removed (AGL.NS/BHANDARI.NS) - see
    # hydrate_real_positions_from_external's own docstring for the full
    # root cause.
    if not hydrate_real_positions_from_external():
        reconcile_real_positions_from_journal()
    reconcile_real_trades_today_from_journal()
    # rr_cursor: Upstash first (real-time), same reasoning as
    # real_positions above - reconcile_scheduler_check_counts_from_journal's
    # own rr_cursor restore only fires when this leaves the cursor at its
    # just-started default (0), so a fresher Upstash value never gets
    # clobbered by the slower git journal.
    global _scheduler_rr_cursor
    _external_rr_cursor = hydrate_rr_cursor_from_external()
    if _external_rr_cursor is not None:
        _scheduler_rr_cursor = _external_rr_cursor
        print(f"[rr_cursor_external] restored cursor to {_external_rr_cursor} from Upstash")
    # check_counts (the "distinct scanned" dict itself): Upstash first,
    # same reasoning as rr_cursor above - only applied if today's day
    # matches (a stale prior-day snapshot must never carry over, same
    # rollover rule _record_scheduler_check itself applies). The journal
    # reconcile right below only fires when this left the dict still
    # empty, so a fresher Upstash-restored dict is never clobbered.
    global _scheduler_check_counts_day
    _external_check_counts = hydrate_check_counts_from_external()
    if _external_check_counts is not None:
        _ext_day, _ext_counts = _external_check_counts
        if _ext_day == ist_now().strftime("%Y-%m-%d"):
            _scheduler_check_counts.update(_ext_counts)
            _scheduler_check_counts_day = _ext_day
            print(f"[check_counts_external] restored {len(_ext_counts)} symbol check-count(s) from Upstash")
    reconcile_scheduler_check_counts_from_journal()
    asyncio.create_task(_scheduler_loop())
    # Kotak Neo live tick feed (2026-09-04) - display data only, isolated
    # in its own task so a failure here (missing/misconfigured creds, a
    # broken kotakneoapi install) can never affect the scheduler above.
    # See kotak_live_feed.py's module docstring for what this is and
    # isn't - real-time ticks for display, still no live-candle history
    # (Kotak has none), still no order placement.
    try:
        import kotak_live_feed
        asyncio.create_task(kotak_live_feed.run_feed([cfg["symbol"] for cfg in WATCHLIST]))
    except Exception as e:
        print(f"[kotak_live_feed] not started: {e}")


@app.get("/scheduler-status")
def scheduler_status():
    return {
        "watchlist_size": len(WATCHLIST),
        "interval_seconds": SCHEDULER_INTERVAL_SECONDS,
        "last_tick_ts": _scheduler_last_tick_ts,
        "last_tick_ago_seconds": round(time.time() - _scheduler_last_tick_ts, 1) if _scheduler_last_tick_ts else None,
        "last_error": _scheduler_last_error,
        "scheduler_capital_inr": _real_capital_cache["value"],
        "scheduler_capital_source": "kotak_neo_real_account" if _real_capital_cache["value"] is not None else "not_yet_fetched",
        "scheduler_capital_fetched_at_utc": _real_capital_cache["fetched_at"] or None,
        "scheduler_capital_fetch_error": _real_capital_cache["error"],
    }


@app.get("/kotak-neo/live-ticks")
def kotak_neo_live_ticks(request: Request):
    """Real-time ticks from Kotak Neo's SFeed WebSocket, as last received
    by the background feed task (kotak_live_feed.py).

    Gated behind KOTAK_NEO_API_TOKEN (2026-09-04, fixed after a real-money
    risk review flagged this) - unlike the Phase 2/2.5 REST endpoints, the
    WebSocket connect/subscribe code path here has never actually been
    exercised against a real connection failure, so its exception text
    isn't verified caller-safe the way kotak_neo.login()'s is. `last_error`
    could in principle echo something from that unverified path - this
    was briefly live unauthenticated before the same review caught it.
    Requires ?token=<KOTAK_NEO_API_TOKEN> (or an 'Authorization: Bearer
    <token>' header), same as the rest of the real-Kotak-data endpoints.

    `status.connected: false` with a `last_error` means the feed isn't
    currently streaming (see kotak_live_feed.py's module docstring for
    why - most commonly Render's free-tier process having just restarted
    from an inactivity spin-down, mid-reconnect)."""
    _require_kotak_token(request)
    try:
        import kotak_live_feed
        return {"ticks": kotak_live_feed.get_live_ticks(), "status": kotak_live_feed.get_feed_status()}
    except Exception as e:
        return {"ticks": {}, "status": {"connected": False, "last_error": str(e)}}


# Data source per monitored symbol (2026-09-03) - "MCX_PROXY" symbols run on
# an international futures contract as a stand-in for the real MCX contract
# (see the WATCHLIST comment block above), never MCX's own price directly.
_MCX_PROXY_FOR = {"GC=F": "MCX GOLD", "SI=F": "MCX SILVER (30kg, 999 purity)", "CL=F": "MCX CRUDEOIL"}
_INDEX_SYMBOLS = {"^NSEI", "^NSEBANK", "^BSESN"}


def _asset_class_and_source(symbol: str):
    """(asset_class, data_source, mcx_proxy_for) for any symbol the
    scheduler might check - WATCHLIST entries and options rows
    ('{underlying}:OPT') alike. Reality as of 2026-09-03: every asset is
    priced via Yahoo Finance (yfinance) - Kotak Neo isn't used for any
    monitoring/price data yet, only account-level auth/holdings/positions/
    limits (see docs/TRADING_CONSTRAINTS.md 'Kotak Neo connection'). Shared
    by /watchlist and /scheduler-pipeline so both answer "checks today, per
    asset, from where" consistently."""
    if symbol in _INDEX_SYMBOLS:
        return "index", "yahoo_finance", None
    if symbol in _MCX_PROXY_FOR:
        return "mcx_commodity_proxy", "yahoo_finance", _MCX_PROXY_FOR[symbol]
    if symbol.endswith(":OPT"):
        return "options", "yahoo_finance", None
    return "nse_equity", "yahoo_finance", None


@app.get("/scheduler-attempts")
def scheduler_attempts():
    """The real-time scheduler's latest entry-condition check per symbol -
    what it actually saw and decided (checked/no_signal/entered_long/
    exited_.../pre_open/etc.), not a synthetic re-check. journal-sync.yml
    snapshots this into docs/attempt_log.json each sync so there's a
    persistent trail of what was attempted and why, not just closed
    trades."""
    return _scheduler_last_results


@app.get("/scheduler-pipeline")
def scheduler_pipeline(recent: int = 10, next_n: int = 5):
    """Live scanner view for /trade-view: what was just checked, what's
    being checked RIGHT NOW, and what's queued up next in the round-robin
    (see _scheduler_loop/SCHEDULER_ENTRY_SCAN_BATCH_SIZE). `recent` is the
    max number of most-recently-checked entries to return; `next_n` is how
    far to peek ahead into the round-robin queue."""
    last_checked = sorted(
        ({"symbol": k, "display": _display_name(k), **v} for k, v in _scheduler_last_results.items()),
        key=lambda r: r.get("checked_at_utc", 0),
        reverse=True,
    )[:recent]

    # Every symbol ever checked today (equity WATCHLIST entries and
    # "{underlying}:OPT" options rows alike), with its running today-count
    # and its latest known status - the full per-asset table for
    # /trade-view, not just the most-recent few. Includes a symbol that's
    # been checked 0 times today (pre-open all day, say) so the table
    # reflects the whole watchlist, not only what's fired so far.
    all_keys = set(_scheduler_check_counts) | set(_scheduler_last_results) | {
        cfg["symbol"] for cfg in WATCHLIST
    } | {f"{u}:OPT" for u in OPTIONS_ELIGIBLE_SYMBOLS}
    check_counts_today_rows = []
    for k in all_keys:
        asset_class, data_source, mcx_proxy_for = _asset_class_and_source(k)
        check_counts_today_rows.append({
            "symbol": k,
            "display": _display_name(k),
            "checks_today": _scheduler_check_counts.get(k, 0),
            "last_action": (
                _scheduler_last_results.get(k, {}).get("action_taken")
                or _scheduler_last_results.get(k, {}).get("status")
            ),
            "last_checked_at_utc": _scheduler_last_results.get(k, {}).get("checked_at_utc"),
            "asset_class": asset_class,
            "data_source": data_source,
            "mcx_proxy_for": mcx_proxy_for,
        })
    check_counts_today = sorted(
        check_counts_today_rows,
        # NSE indices pinned to the very top, in a fixed order - the user
        # specifically asked to be able to find NIFTY/BANKNIFTY/SENSEX
        # without hunting through a count-sorted, scrollable list of 36
        # rows; everything else still sorts by checks_today desc.
        key=lambda r: (
            {"^NSEI": 0, "^NSEBANK": 1, "^BSESN": 2}.get(r["symbol"], 99),
            -r["checks_today"],
            r["symbol"],
        ),
    )

    # Aggregate scanned-today counts for the banner at the top of /trade-view.
    # Computed straight from the same rows the per-asset table below is
    # built from - no separate/fabricated number.
    #   - scanned_today_count: DISTINCT symbols/assets checked >=1 time today.
    #   - scanned_today_total: size of the whole table (equities + indices +
    #     options-overlay rows) - the denominator for scanned_today_count.
    #   - total_checks_today: the WHOLE count (explicit user instruction,
    #     2026-09-08: "I want whole count. Not just distinct") - every
    #     individual check across every symbol today, so a symbol checked
    #     50 times counts 50, not 1. This is the number that actually
    #     answers "how much scanning has happened today."
    scanned_today_count = sum(1 for r in check_counts_today_rows if r["checks_today"] > 0)
    scanned_today_total = len(check_counts_today_rows)
    total_checks_today = sum(r["checks_today"] for r in check_counts_today_rows)

    return {
        "last_checked": last_checked,
        "currently_checking": _scheduler_currently_checking,
        "next_up": [
            {"symbol": s, "display": _display_name(s)} for s in _scheduler_peek_next_batch(next_n)
        ],
        "scanned_today_count": scanned_today_count,
        "scanned_today_total": scanned_today_total,
        "total_checks_today": total_checks_today,
        "check_counts_today": check_counts_today,
        "check_counts_day": _scheduler_check_counts_day,
        "rr_cursor": _scheduler_rr_cursor,
        "scheduler_interval_seconds": SCHEDULER_INTERVAL_SECONDS,
        "entry_scan_batch_size": _live_entry_scan_batch_size_for_display(),
        "last_tick_ts": _scheduler_last_tick_ts,
        "server_time_utc": time.time(),
    }


@app.get("/trade-history")
def trade_history(days: int = 1):
    """Every closed trade in the last `days` IST calendar days (default:
    today only), read from docs/trade_outcomes_log.json - the git-tracked,
    journal-synced, append-only record - NOT the live DB's `trades` table.

    This distinction matters: Render's free tier has no persistent disk, so
    every redeploy wipes the DB clean. A trade that closed BEFORE the most
    recent redeploy is gone from /daily-summary's closed_trades (that
    endpoint only ever sees what's in the current DB instance) even though
    it genuinely happened - on a day with several redeploys (common during
    active development), /daily-summary's realized_pnl/closed_trades badly
    undercounts the real day. This endpoint is the honest "what actually
    closed today" answer, immune to how many times the server has
    restarted since. See journal-sync.yml for how the file gets appended to."""
    try:
        with open(DOCS_TRADE_OUTCOMES_PATH) as f:
            all_trades = json.load(f)
    except Exception:
        all_trades = []

    now_ist = ist_now()
    cutoff_ts = ist_midnight_epoch(now_ist) - (days - 1) * 86400
    today_str = now_ist.strftime("%Y-%m-%d")

    trades = sorted(
        (t for t in all_trades if t.get("exit_time_utc", 0) >= cutoff_ts),
        key=lambda t: t.get("exit_time_utc", 0),
        reverse=True,
    )
    net_pnl_inr = round(sum(t.get("pnl_inr", 0) for t in trades), 2)
    wins = [t for t in trades if t.get("pnl_inr", 0) > 0]
    return {
        "date_ist": today_str,
        "days": days,
        "trades_count": len(trades),
        "net_pnl_inr": net_pnl_inr,
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "trades": trades,
    }


@app.get("/daily-summary")
def daily_summary(capital: float = 400000, daily_risk_pct: float = 2.0):
    """Aggregated view of today's auto-signal paper trading across all symbols:
    realized P&L (Rs and % of capital), win rate, risk-reward achieved per
    trade, remaining daily-loss budget, and any still-open positions.

    tax_on_realized_inr (2026-09-07, explicit user request - "fetch api
    data from kotak and understand it to reach to actual tax," "not an
    input like 30% or something"): an ESTIMATE of tax owed on today's
    account-wide realized profit, computed automatically from India's
    real progressive tax slabs - no manual rate. Same-day equity buy+sell
    (what this system's strategies do, and what a same-day CNC round trip
    on Kotak also is - the shares never actually reach the demat account
    either way) is speculative business income under the Income Tax Act's
    own s.43(5) text (confirmed via web search 2026-09-07 against the
    Act's definition of "speculative transaction" plus multiple CA
    guides), taxed at the trader's slab rate, NOT a flat capital-gains
    rate. See estimate_speculative_income_tax_inr's own docstring for the
    slab table and the "treats today's profit as your only income"
    simplification this project has no way around without knowing your
    other income. Tax applies ONLY to a net positive day - a speculative
    LOSS is never a negative tax; it can only be carried forward and set
    off against future speculative gains (up to 4 years), never against
    salary/other capital gains. This is an estimate for planning, not tax
    advice - confirm your actual liability with a CA."""
    now_ist = ist_now()
    today_str = now_ist.strftime("%Y-%m-%d")
    since_ts = ist_midnight_epoch(now_ist)

    with closing(get_db()) as conn:
        # PAPER-only manual reset ("resume trading" button next to the
        # paper daily loss budget on trade-view) - see today_realized_pnl's
        # own docstring and daily_loss_reset_epoch's entry in
        # RUNTIME_SETTINGS_META for the full reasoning. Applied here too so
        # this endpoint's own closed_trades/realized/budget_remaining stay
        # consistent with today_realized_pnl's (which the halt logic uses).
        since_ts = max(since_ts, get_runtime_setting(conn, "daily_loss_reset_epoch"))
        # Full history for correct cost-basis (see today_realized_pnl) - only
        # sells at/after since_ts are reported as "today's" closed trades.
        all_trades = conn.execute(
            "SELECT id, ts, symbol, action, qty, price, fx_to_inr, strategy, raw_payload FROM trades "
            "WHERE strategy LIKE ? ORDER BY id",
            (ORB_STRATEGY_PREFIX + "%",),
        ).fetchall()
        # No day filter - a genuinely open position should show regardless of
        # which local trading day it was opened on (relevant once a market
        # other than NSE, with its own local "day", is in the mix).
        open_state = conn.execute("SELECT * FROM signal_state WHERE status = 'long'").fetchall()
        open_option_state = conn.execute("SELECT * FROM option_state").fetchall()
        # The ACCOUNT-WIDE risk figure (2026-09-07, second pass) - reuses
        # today_realized_pnl directly (single source of truth, so this
        # endpoint's own budget/halt numbers can never drift from the
        # scheduler's own halt logic again) rather than re-deriving it.
        # closed_trades/win_rate_pct below stay PAPER-only (the strategy's
        # own evaluation log) - this separate figure is what actually
        # drives daily_loss_cap/budget_remaining/halted_for_day/tax.
        account_wide_realized = today_realized_pnl(conn, since_ts)

    book: dict[str, dict] = {}
    realized = 0.0
    closed_trades = []
    for t in all_trades:
        sym = t["symbol"]
        price_inr = t["price"] * t["fx_to_inr"]
        b = book.setdefault(sym, {"qty": 0.0, "avg": 0.0, "last_strategy": None})
        if t["action"] == "buy":
            new_qty = b["qty"] + t["qty"]
            b["avg"] = ((b["qty"] * b["avg"]) + (t["qty"] * price_inr)) / new_qty if new_qty else 0.0
            b["qty"] = new_qty
            # The strategy that ACTUALLY opened this position, not whatever
            # the exit's own (recomputed-from-current-params) trades row
            # happens to carry - kept on the book so a later sell/open-
            # position lookup can name it.
            b["last_strategy"] = t["strategy"]
        else:
            pnl = (price_inr - b["avg"]) * min(t["qty"], b["qty"])
            b["qty"] -= t["qty"]
            if t["ts"] < since_ts:
                continue
            realized += pnl
            try:
                extra = json.loads(t["raw_payload"])
            except Exception:
                extra = {}
            closed_trades.append({
                "symbol": sym, "exit_time_utc": t["ts"],
                "entry_price_native": extra.get("entry_price"), "exit_price_native": t["price"],
                "currency": extra.get("currency", "INR"), "qty": t["qty"],
                "pnl_inr": round(pnl, 2), "pnl_pct_of_capital": round(100 * pnl / capital, 3),
                "exit_reason": extra.get("exit_reason"), "rr_target": extra.get("rr_target"),
                "rr_achieved": extra.get("rr_achieved"), "strategy": b.get("last_strategy"),
            })

    # Merge in the durable journal (see _merge_closed_trades/
    # today_realized_pnl for the full 2026-09-07 root-cause writeup) - a
    # trade that closed before the most recent Render redeploy is invisible
    # to the loop above (it only ever sees this DB instance's own `trades`
    # table) but IS in docs/trade_outcomes_log.json. Without this merge,
    # this endpoint's realized_pnl/win_rate_pct/closed_trades could disagree
    # with today_realized_pnl's own (already-merged) figure - the exact
    # "win rate mismatched" symptom reported 2026-09-07.
    closed_trades = _merge_closed_trades(closed_trades, _durable_trade_outcomes_since(since_ts))
    closed_trades.sort(key=lambda t: t.get("exit_time_utc", 0), reverse=True)
    realized = sum(t.get("pnl_inr", 0.0) for t in closed_trades)

    open_positions = []
    capital_deployed_inr = 0.0
    # For the trade-view chart's entry-indicator overlay (sma_fast/sma_slow
    # lines) - signal_state has no sma_fast/sma_slow columns of its own, so
    # this reads each symbol's CURRENT WATCHLIST config. That's the config
    # actually in effect right now, not necessarily verbatim what fired at
    # entry if WATCHLIST changed mid-trade (rare - these are static per
    # deployment) - close enough for a live-only display, not claimed as
    # an exact historical record.
    watchlist_by_symbol = {cfg["symbol"]: cfg for cfg in WATCHLIST}
    for r in open_state:
        notional_inr = r["qty"] * r["entry_price"] * r["fx_to_inr"]
        capital_deployed_inr += notional_inr
        open_positions.append({
            "symbol": r["symbol"], "qty": r["qty"],
            "entry_price_native": r["entry_price"], "stop_loss_native": r["stop_loss"],
            # The live, possibly-already-trailed stop is stop_loss_native
            # above (what the chart/ladder shows and what stop_hit actually
            # compares against); initial_stop_loss_native is the ORIGINAL
            # stop at entry, frozen - carried through the journal so a
            # redeploy mid-trail doesn't lose the R-multiple yardstick the
            # trailing stop measures activation against (see
            # _trailing_stop_target). None for a trade opened before this
            # column existed.
            "initial_stop_loss_native": r["initial_stop_loss"],
            "target_native": r["target"], "fx_to_inr": r["fx_to_inr"],
            "notional_inr": round(notional_inr, 2),
            "orb_high_native": r["orb_high"], "orb_low_native": r["orb_low"],
            "entry_ts": r["entry_ts"], "interval": r["interval"],
            # signal_state itself has no strategy column - read the same
            # book the closed_trades loop above just built from the
            # trades table's own buy rows, so this and a later close of
            # the same position always agree on which strategy opened it.
            "strategy": book.get(r["symbol"], {}).get("last_strategy"),
            "sma_fast": watchlist_by_symbol.get(r["symbol"], {}).get("sma_fast"),
            "sma_slow": watchlist_by_symbol.get(r["symbol"], {}).get("sma_slow"),
        })
    for r in open_option_state:
        qty = r["contracts"] * 100
        notional_inr = qty * r["entry_premium"] * r["fx_to_inr"]
        capital_deployed_inr += notional_inr
        opt_symbol = r["opt_symbol"]
        open_positions.append({
            # symbol stays the unique bookkeeping key ("SPY:OPT-CALL") so it
            # never collides with that same underlying's own equity card;
            # "underlying" is the real fetchable ticker for anything (e.g.
            # trade-view's chart) that wants the underlying's own price
            # action instead - the option's own premium isn't a candle
            # series yfinance exposes historically.
            "symbol": opt_symbol, "underlying": r["underlying"], "instrument": "option",
            "right": r["right"], "strike": r["strike"], "expiry": r["expiry"],
            "contracts": r["contracts"], "qty": qty,
            "entry_price_native": r["entry_premium"], "stop_loss_native": r["stop_premium"],
            "target_native": r["target_premium"], "fx_to_inr": r["fx_to_inr"],
            "notional_inr": round(notional_inr, 2),
            "entry_iv": r["entry_iv"], "entry_delta": r["entry_delta"],
            "entry_ts": r["entry_ts"], "interval": "5m",
            "strategy": OPTIONS_STRATEGY_TAG,  # the only strategy tag the options overlay ever uses
        })

    daily_loss_cap = capital * daily_risk_pct / 100
    loss_so_far = max(0.0, -account_wide_realized)
    budget_remaining = max(0.0, daily_loss_cap - loss_so_far)
    wins = [c for c in closed_trades if c["pnl_inr"] > 0]

    return {
        "date_ist": today_str,
        "capital": capital,
        "capital_deployed_inr": round(capital_deployed_inr, 2),
        "capital_available_inr": round(capital - capital_deployed_inr, 2),
        "daily_loss_cap": daily_loss_cap,
        "daily_loss_cap_pct": daily_risk_pct,
        # Account-wide (real Kotak P&L for NSE equities when real trading
        # is active + paper P&L for whatever it doesn't cover - see
        # today_realized_pnl's own docstring), NOT the paper-only figure
        # closed_trades below sums to. paper_realized_pnl is kept alongside
        # for anyone who wants the pure-strategy number.
        "realized_pnl": round(account_wide_realized, 2),
        "realized_pnl_pct": round(100 * account_wide_realized / capital, 3),
        "paper_realized_pnl": round(realized, 2),
        "budget_remaining": round(budget_remaining, 2),
        "halted_for_day": budget_remaining <= 0,
        "closed_trades_count": len(closed_trades),
        "win_rate_pct": round(100 * len(wins) / len(closed_trades), 1) if closed_trades else None,
        # ESTIMATE only, on net positive account-wide profit for the day -
        # see estimate_speculative_income_tax_inr's own docstring for the
        # speculative-business-income reasoning and the "not tax advice"
        # caveat. Automatic (India's real progressive slabs), no manual
        # rate input - explicit user instruction 2026-09-07.
        "tax_on_realized_inr": estimate_speculative_income_tax_inr(account_wide_realized),
        "open_positions": open_positions,
        "closed_trades": closed_trades,
    }


DRY_RUN_DEFAULT_SYMBOLS = [
    {"symbol": "^NSEI", "orb_minutes": 30, "sma_fast": 5, "sma_slow": 50},
    {"symbol": "^NSEBANK", "orb_minutes": 5, "sma_fast": 9, "sma_slow": 50},
    {"symbol": "^BSESN", "orb_minutes": 30, "sma_fast": 20, "sma_slow": 50},
]


@app.get("/dry-run-day")
def dry_run_day(
    date: str,
    capital: float = 400000,
    daily_risk_pct: float = 2.0,
    risk_per_trade_pct: float = 2.0,
    stop_pct: float = 2.0,
    rr: float = 3.0,
    orb_minutes_override: int = 0,  # 0 = use each symbol's validated default
):
    """
    Sandboxed same-day replay: re-runs the exact ORB+trend rules the live
    /auto-signal uses, tick by tick across NIFTY/BANKNIFTY/SENSEX together
    (sharing one capital pool, exactly like the real workflows), against
    REAL historical 5-min data for `date` - but writes NOTHING to the real
    paper_trades.db. Pure simulation, safe to run anytime, for any past
    trading day still in yfinance's 5m window (~60 days).

    Uses each symbol's evidence-backed params from the 2026-09-02 research
    (see docs/daily_logs/2026-09-02-entry-trigger-research.md) unless
    orb_minutes_override is set (applies the same orb_minutes to all 3,
    sma_fast/slow unchanged).
    """
    symbols = DRY_RUN_DEFAULT_SYMBOLS
    open_min = 9 * 60 + 15
    squareoff_min = 15 * 60 + 20

    per_symbol_df = {}
    for cfg in symbols:
        sym = cfg["symbol"]
        try:
            raw = fetch_ohlc(sym, "5d", "5m")
        except HTTPException as e:
            return {"error": f"data fetch failed for {sym}: {e.detail}"}
        ts = pd.to_datetime(raw["Date"])
        ts_ist = ts.dt.tz_convert("Asia/Kolkata") if ts.dt.tz is not None else ts.dt.tz_localize(
            "UTC"
        ).dt.tz_convert("Asia/Kolkata")
        raw = raw.assign(ts_ist=ts_ist, date_ist=ts_ist.dt.strftime("%Y-%m-%d"))
        day_df = raw[raw["date_ist"] == date].reset_index(drop=True)
        if day_df.empty:
            return {"error": f"no 5m data for {sym} on {date} (outside yfinance's ~60d intraday window?)"}
        day_df["mins"] = day_df["ts_ist"].dt.hour * 60 + day_df["ts_ist"].dt.minute
        per_symbol_df[sym] = day_df

    # Precompute each symbol's ORB high/orb window/trend using the same
    # vectorized logic as add_strategy_signal's orb_breakout branch.
    precomputed = {}
    for cfg in symbols:
        sym = cfg["symbol"]
        om = orb_minutes_override or cfg["orb_minutes"]
        sf, ss = cfg["sma_fast"], cfg["sma_slow"]
        df = per_symbol_df[sym].copy()
        df["fast_ma"] = df["Close"].rolling(sf).mean()
        df["slow_ma"] = df["Close"].rolling(ss).mean()
        df["trend_up"] = df["fast_ma"] > df["slow_ma"]
        in_window = df["mins"] < open_min + om
        df["orb_high_running"] = df["High"].where(in_window).cummax().ffill()
        df["orb_low_running"] = df["Low"].where(in_window).cummin().ffill()
        precomputed[sym] = {"df": df, "orb_minutes": om, "cutoff": open_min + om}

    all_times = sorted(set(t for cfg in symbols for t in per_symbol_df[cfg["symbol"]]["mins"]))

    daily_loss_cap = capital * daily_risk_pct / 100
    state = {cfg["symbol"]: None for cfg in symbols}  # None or dict(entry,stop,target,qty)
    realized = 0.0
    events = []
    checkpoints = []
    orb_summary = {}

    def remaining_budget():
        loss_so_far = max(0.0, -realized)
        return max(0.0, daily_loss_cap - loss_so_far)

    def deployed_notional():
        return sum(s["qty"] * s["entry"] for s in state.values() if s)

    for t_idx, m in enumerate(all_times):
        for cfg in symbols:
            sym = cfg["symbol"]
            pc = precomputed[sym]
            df = pc["df"]
            rows = df[df["mins"] == m]
            if rows.empty:
                continue
            row = rows.iloc[-1]
            close = float(row["Close"])
            time_str = str(row["ts_ist"])[11:16]
            pos = state[sym]
            halted = remaining_budget() <= 0

            # record ORB formation once
            if sym not in orb_summary and m >= pc["cutoff"] - 1 and pd.notna(row["orb_high_running"]):
                orb_summary[sym] = {
                    "orb_high": round(float(row["orb_high_running"]), 2),
                    "orb_low": round(float(row["orb_low_running"]), 2),
                    "formed_by": time_str,
                }

            if pos:
                reason = None
                if halted:
                    reason = "daily_loss_cap_hit"
                elif close >= pos["target"]:
                    reason = "target_hit"
                elif close <= pos["stop"]:
                    reason = "stop_hit"
                elif m >= squareoff_min:
                    reason = "eod_squareoff"
                if reason:
                    pnl = (close - pos["entry"]) * pos["qty"]
                    realized += pnl
                    rr_ach = round((close - pos["entry"]) / (pos["entry"] - pos["stop"]), 2)
                    events.append({
                        "time": time_str, "symbol": sym, "event": f"exited_{reason}",
                        "price": round(close, 2), "pnl": round(pnl, 2),
                        "pnl_pct_of_capital": round(100 * pnl / capital, 3), "rr_achieved": rr_ach,
                    })
                    state[sym] = None
                continue

            if halted or m >= squareoff_min or m < pc["cutoff"]:
                continue

            orb_high = row["orb_high_running"]
            trend_up = bool(row["trend_up"]) if pd.notna(row["trend_up"]) else False
            if pd.notna(orb_high) and close > float(orb_high) and trend_up:
                orb_low = float(row["orb_low_running"])
                stop = max(orb_low, close * (1 - stop_pct / 100))
                stop_dist = close - stop
                if stop_dist <= 0:
                    continue
                target = close + rr * stop_dist
                risk_amount = min(capital * risk_per_trade_pct / 100, remaining_budget())
                avail_capital = max(0.0, capital - deployed_notional())
                qty = min(int(risk_amount // stop_dist), int(avail_capital // close))
                if qty < 1:
                    continue
                state[sym] = {"entry": close, "stop": stop, "target": target, "qty": qty}
                events.append({
                    "time": time_str, "symbol": sym, "event": "entered_long",
                    "price": round(close, 2), "stop": round(stop, 2), "target": round(target, 2),
                    "qty": qty, "notional": round(qty * close, 2),
                })

        if m % 30 == 0:
            snap = {"time_mins": m}
            for cfg in symbols:
                sym = cfg["symbol"]
                rows = precomputed[sym]["df"]
                rr_ = rows[rows["mins"] == m]
                if rr_.empty:
                    continue
                r = rr_.iloc[-1]
                snap[sym] = {
                    "close": round(float(r["Close"]), 2),
                    "position": "long" if state[sym] else "flat",
                }
            checkpoints.append(snap)

    wins = [e for e in events if e["event"].startswith("exited_") and e.get("pnl", 0) > 0]
    exits = [e for e in events if e["event"].startswith("exited_")]

    return {
        "date": date,
        "capital": capital,
        "daily_loss_cap": daily_loss_cap,
        "orb_formation": orb_summary,
        "events": events,
        "checkpoints_every_30min": checkpoints,
        "summary": {
            "realized_pnl": round(realized, 2),
            "realized_pnl_pct": round(100 * realized / capital, 3),
            "trades_closed": len(exits),
            "win_rate_pct": round(100 * len(wins) / len(exits), 1) if exits else None,
            "still_open_at_session_end": {k: v for k, v in state.items() if v},
            "budget_remaining": round(remaining_budget(), 2),
        },
    }


@app.get("/health")
def health():
    return {"status": "alive", "time": time.time()}


@app.get("/watchlist")
def watchlist():
    """Every symbol the scheduler actually scans, each with a data_source
    label - a distinct question from /trade-view, which shows only
    currently-open positions, not the full scan universe. Reality as of
    2026-09-03: 100% of monitored symbols are priced via Yahoo Finance
    (yfinance) - Kotak Neo is not used for any monitoring/price data yet,
    only for account-level auth/holdings/positions/limits (Phase 1/2, see
    docs/TRADING_CONSTRAINTS.md 'Kotak Neo connection'). This changes once
    real NSE options/futures data via Kotak is wired up."""
    entries = []
    for cfg in WATCHLIST:
        sym = cfg["symbol"]
        asset_class, data_source, mcx_proxy_for = _asset_class_and_source(sym)
        entries.append({
            "symbol": sym,
            "display_name": _display_name(sym),
            "asset_class": asset_class,
            "data_source": data_source,
            "mcx_proxy_for": mcx_proxy_for,
            "risk_pct": cfg.get("risk_pct"),
            "stop_pct": cfg.get("stop_pct"),
        })
    return {"count": len(entries), "symbols": entries}


def _env_presence(name: str) -> dict:
    """Reports whether an env var is SET, without ever exposing its value -
    just a length and a masked preview (first 4 chars, for the user to
    eyeball-match against what they pasted into Render, nothing more)."""
    val = os.environ.get(name)
    if not val:
        return {"set": False}
    return {"set": True, "length": len(val), "preview": val[:4] + "…" if len(val) > 4 else "…"}


@app.get("/kotak-neo/status")
def kotak_neo_status():
    """Diagnostic only - confirms whether Render actually picked up each
    Kotak Neo credential env var, without ever echoing the real value back
    (a masked preview only). No connection to Kotak is attempted here -
    see /kotak-neo/test-login for that. Field list matches kotak_neo.py's
    REQUIRED_ENV_VARS - confirmed against Kotak's own actively-maintained
    SDK that the current login flow needs consumer_key, NOT a separate
    consumer secret (see docs/TRADING_CONSTRAINTS.md 'Kotak Neo
    connection')."""
    try:
        import kotak_neo
        return {name: _env_presence(name) for name in kotak_neo.REQUIRED_ENV_VARS}
    except ImportError as e:
        return {"error": f"kotak_neo module not importable: {e}"}


@app.get("/kotak-neo/test-login")
def kotak_neo_test_login():
    """Attempts a REAL login to the live Kotak Neo account (environment=
    'prod') and reports success/failure ONLY - no account data (holdings,
    positions, balances) is ever returned by this endpoint. This app has
    no authentication of its own yet, so anything beyond a plain boolean
    here would be a real account-data exposure on a public URL - see
    docs/TRADING_CONSTRAINTS.md 'Kotak Neo connection' for why this stays
    deliberately minimal. Does not place, modify, or cancel any order -
    auth only."""
    try:
        import kotak_neo
    except ImportError as e:
        return {"logged_in": False, "error": f"kotak_neo module not importable: {e}"}
    try:
        kotak_neo.login()
        return {"logged_in": True}
    except Exception as e:
        return {"logged_in": False, "error": str(e)}


# Phase 2 (2026-09-03): read-only account data (holdings, positions, funds).
# Unlike /kotak-neo/status and /test-login, these return REAL account data -
# so unlike the rest of this app (which has no auth at all, fine for fake
# paper-trading data), these are gated behind a shared-secret token. Fails
# CLOSED: if KOTAK_NEO_API_TOKEN isn't set, the endpoint refuses rather than
# serving real data on an effectively-unprotected URL.
KOTAK_NEO_API_TOKEN = os.environ.get("KOTAK_NEO_API_TOKEN")


def _require_kotak_token(request: Request):
    if not KOTAK_NEO_API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="KOTAK_NEO_API_TOKEN not set on the server - this endpoint refuses to run "
                   "unauthenticated since it returns real account data.",
        )
    supplied = request.query_params.get("token")
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        supplied = supplied or auth_header[len("Bearer "):]
    if supplied != KOTAK_NEO_API_TOKEN:
        raise HTTPException(status_code=401, detail="Bad or missing token")


def _kotak_json_safe(result):
    """The SDK's own holdings()/positions()/limits() catch their internal
    errors and hand back {"Error": <Exception instance>} rather than a
    string - not JSON-serializable as-is, which would 500 the endpoint on
    exactly the failure case a caller most needs to see. Round-trip through
    json with default=str so any such object becomes its string form
    instead of crashing the response."""
    return json.loads(json.dumps(result, default=str))


@app.get("/kotak-neo/holdings")
def kotak_neo_holdings(request: Request):
    """Real portfolio holdings from the live Kotak Neo account. Read-only -
    places no order. Requires ?token=<KOTAK_NEO_API_TOKEN> (or an
    'Authorization: Bearer <token>' header) - see docs/TRADING_CONSTRAINTS.md
    'Kotak Neo connection' for why this is gated unlike the rest of this
    app's endpoints."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        return _kotak_json_safe(kotak_neo.holdings())
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/order-report")
def kotak_neo_order_report(request: Request, order_id: str | None = None):
    """The real account's order book (or a single order, if order_id is
    given) - the ONLY place a REJECTED real order's actual reason text
    lives (2026-09-08, added to diagnose repeated REJECTED SL-M sell
    orders on AGI/AGL that this app had never surfaced a reason for -
    place_real_stop_loss only ever checked for order ACCEPTANCE via
    nOrdNo, never final fill/reject status). Read-only - places no order.
    Requires ?token=<KOTAK_NEO_API_TOKEN> (or an 'Authorization: Bearer
    <token>' header)."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        return _kotak_json_safe(kotak_neo.order_report(order_id=order_id))
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/positions")
def kotak_neo_positions(request: Request):
    """Real open positions from the live Kotak Neo account. Read-only -
    places no order. Requires ?token=<KOTAK_NEO_API_TOKEN> (or an
    'Authorization: Bearer <token>' header)."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        return _kotak_json_safe(kotak_neo.positions())
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/limits")
def kotak_neo_limits(request: Request):
    """Real available margin/funds from the live Kotak Neo account.
    Read-only - places no order. Requires ?token=<KOTAK_NEO_API_TOKEN> (or
    an 'Authorization: Bearer <token>' header)."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        return _kotak_json_safe(kotak_neo.limits())
    except Exception as e:
        return {"error": str(e)}


@app.post("/kotak-neo/reconcile-real-positions")
def kotak_neo_reconcile_real_positions(request: Request, adopt: str | None = None):
    """Corrects this app's own real_positions tracking against Kotak's own
    live positions() data - a genuinely separate process from the 30s
    trading scheduler, run by kotak-reconcile.yml on its own cadence
    (2026-09-07, explicit user instruction: "a genuinely separate
    scheduled process"; also the direct fix for "QTY not in sync",
    "kotak balance left is not in sync", "portfolio positions should be
    in sync with kotak", and the qty half of "cancellation order[s] ...
    with right qty").

    Places NO order - this is pure bookkeeping. Three things it does:

    1. QTY CORRECTION: for each row this app already tracks in
       real_positions, if Kotak's own OPEN (not squared-off) position for
       that trading symbol shows a DIFFERENT qty, this app's row is
       corrected to match Kotak's truth - the exact fix for the "wrong
       qty" risk in _maybe_place_real_exit (which places a real sell for
       row["qty"] shares; if that qty had drifted from what Kotak
       actually holds, the exit would be wrong).
    2. GHOST CLEANUP: if this app tracks an open real_positions row but
       Kotak shows NO open position for that symbol at all (already
       closed at the broker - a real sell we lost track of, or a manual
       close), the stale row is removed. Never guesses a qty or price for
       this - just removes the row, since re-deriving what actually
       happened isn't possible from positions() alone.
    3. UNTRACKED POSITIONS (reported, NOT auto-adopted by default): if
       Kotak shows an open position this app has no record of at all
       (e.g. a manually-placed trade), it's surfaced in the response and
       logged, but NOT added to real_positions unless explicitly opted
       into via `adopt` - auto-adopting a position this app didn't open
       and doesn't know the intended stop/target for risks the kill
       switch or scheduler later acting on it with no real context. A
       human decision, not an automatic one.

       `adopt` (2026-09-08, explicit user finding: a restart landed
       between a bot-PLACED real entry+SL and the next journal-sync
       snapshot capturing them, permanently losing this app's own
       tracking of a position it itself opened moments earlier - the
       real order and its resting SL stayed completely safe at Kotak
       throughout, but real_positions no longer had a row for it, so
       nothing blocked a second real buy if the paper engine's own
       tracking, lost the same way, re-entered the same symbol) - a
       comma-separated list of Kotak trading symbols (e.g. "ATL-EQ") to
       adopt from `untracked_open_positions`, or "*" for all of them.
       Only ever adopts a symbol this call ITSELF found genuinely open
       and untracked - never guesses at one from a name alone. For each
       adopted symbol: qty and a weighted-average entry_price come from
       this SAME positions() data already fetched above (buyAmt/flBuyQty
       for that row); entry_order_id and any still-resting SL
       (sl_order_id/sl_trigger_price) are looked up from ONE
       order_report() call (fetched once, reused for every symbol being
       adopted this call) by matching trdSym - a genuinely still-open
       real position adopted with its real, confirmed order data, not a
       stub. Watchlist symbol is derived as "<bare trading symbol>.NS"
       (trdSym minus its "-EQ" suffix) - this app's own established
       nse_cm trading-symbol convention (kotak_live_feed's
       _bare_nse_symbol, inverted), which every real trading symbol
       observed on this account so far follows exactly.

       BUG fixed 2026-09-08 (second occurrence of this exact gap, this
       time AARTIIND - explicit user finding: "why so much u sync"): the
       first version matched ANY complete BUY order for the symbol as
       this app's own entry - a manually-placed buy would have been
       silently adopted as if the bot opened it. Now only ever matches a
       BUY carrying Kotak's own algo-order tag for this app (ordSrc
       "ADMINCPPAPI_NEOTRADEAPI", algId not "NA"/blank - confirmed live,
       distinct from a manual/mobile order's ordSrc "ADMINCPPAPI_MOB"/
       algId "NA", every single time this session); a symbol with no
       bot-tagged BUY in the order book is skipped (stays untracked, for
       a human to review) rather than adopted from a guess. This is what
       makes it now safe to run unattended - see kotak-reconcile.yml's
       scheduled (every 15 min, market hours) run, which passes
       adopt="*" for exactly this reason: self-heals this recurring gap
       automatically instead of requiring a human to notice a missing
       position in the Kotak app and report it each time.

    Also returns the real account balance (kotak_neo.limits()) alongside,
    for the same "sync balance, not just positions" ask.

    Requires the same Kotak API token as every other real-money endpoint -
    this both reads AND writes real-money tracking state."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        positions_resp = kotak_neo.positions()
        limits_resp = kotak_neo.limits()
    except Exception as e:
        return {"error": f"Kotak fetch failed: {e}"}

    rows = positions_resp.get("data") or [] if isinstance(positions_resp, dict) else []
    # Open = not fully squared off (flBuyQty != flSellQty) on the nse_cm
    # cash segment - the only segment/product this app's real trading
    # touches (stage 3 v1 scope, see kotak_real_orders.py).
    kotak_open_by_trdsym: dict[str, dict] = {}
    for row in rows:
        try:
            if row.get("exSeg") != "nse_cm":
                continue
            fl_buy = float(row.get("flBuyQty", 0) or 0)
            fl_sell = float(row.get("flSellQty", 0) or 0)
            net_qty = fl_buy - fl_sell
            if net_qty == 0:
                continue  # fully squared off - not an open position
            trd_sym = row.get("trdSym")
            if trd_sym:
                kotak_open_by_trdsym[trd_sym] = {"qty": abs(net_qty), "raw": row}
        except (TypeError, ValueError):
            continue

    qty_corrected, removed_ghosts, untracked = [], [], []
    with closing(get_db()) as conn:
        our_rows = conn.execute("SELECT * FROM real_positions").fetchall()
        our_trdsyms = set()
        for r in our_rows:
            our_trdsyms.add(r["kotak_trading_symbol"])
            kotak_match = kotak_open_by_trdsym.get(r["kotak_trading_symbol"])
            if kotak_match is None:
                conn.execute("DELETE FROM real_positions WHERE symbol = ?", (r["symbol"],))
                removed_ghosts.append({"symbol": r["symbol"], "kotak_trading_symbol": r["kotak_trading_symbol"],
                                        "was_tracked_qty": r["qty"]})
            elif int(kotak_match["qty"]) != r["qty"]:
                conn.execute("UPDATE real_positions SET qty = ? WHERE symbol = ?",
                             (int(kotak_match["qty"]), r["symbol"]))
                qty_corrected.append({"symbol": r["symbol"], "kotak_trading_symbol": r["kotak_trading_symbol"],
                                       "old_qty": r["qty"], "new_qty": int(kotak_match["qty"])})
        for trd_sym, info in kotak_open_by_trdsym.items():
            if trd_sym not in our_trdsyms:
                untracked.append({"kotak_trading_symbol": trd_sym, "qty": int(info["qty"])})

        adopted = []
        if adopt and untracked:
            wanted = None if adopt == "*" else {s.strip() for s in adopt.split(",") if s.strip()}
            to_adopt = [u for u in untracked if wanted is None or u["kotak_trading_symbol"] in wanted]
            if to_adopt:
                order_rows = []
                try:
                    order_report = kotak_neo.order_report()
                    order_rows = order_report.get("data") or [] if isinstance(order_report, dict) else []
                except Exception as e:
                    print(f"[reconcile] order_report fetch failed during adopt (proceeding without order-id/SL data): {e}")
                TERMINAL_STATUSES = {"complete", "rejected", "cancelled", "cancelled by user", "cancelledbyuser", "expired"}
                for u in to_adopt:
                    trd_sym = u["kotak_trading_symbol"]
                    raw = kotak_open_by_trdsym[trd_sym]["raw"]
                    qty = int(kotak_open_by_trdsym[trd_sym]["qty"])
                    try:
                        buy_amt = float(raw.get("buyAmt", 0) or 0)
                        fl_buy = float(raw.get("flBuyQty", 0) or 0)
                        entry_price = round(buy_amt / fl_buy, 2) if fl_buy else None
                    except (TypeError, ValueError):
                        entry_price = None
                    if entry_price is None:
                        continue  # can't adopt without a real entry price - skip, stays untracked
                    entry_order_id, sl_order_id, sl_trigger_price = None, None, None
                    target_order_id, target_price = None, None
                    fallback_entry_order_id = None
                    for row in order_rows:
                        if row.get("trdSym") != trd_sym:
                            continue
                        st = str(row.get("ordSt", "")).lower()
                        # Kotak tags every order THIS app places with its own
                        # algo id (algId "99999", ordSrc
                        # "ADMINCPPAPI_NEOTRADEAPI" - confirmed live,
                        # distinct from a manual/mobile order's algId "NA"/
                        # ordSrc "ADMINCPPAPI_MOB", every single time this
                        # session). Still used to gate the SL/target LEGS
                        # below (never touch/replace a resting order this
                        # app didn't itself place), but explicit user
                        # instruction 2026-09-08 ("pick the live entered
                        # trades from Kotak and then track them for their
                        # exit conditions, trailing SL and targets and
                        # everything") deliberately widened the ENTRY match
                        # itself to ANY completed buy, bot-placed or manual -
                        # a real position sitting open at Kotak gets tracked
                        # and governed either way now; is_bot_placed is kept
                        # only to prefer this app's own order id for the
                        # audit log when one exists.
                        is_bot_placed = (row.get("ordSrc") == "ADMINCPPAPI_NEOTRADEAPI"
                                          and row.get("algId") not in (None, "NA", ""))
                        if row.get("trnsTp") == "B" and st == "complete":
                            if is_bot_placed and not entry_order_id:
                                entry_order_id = row.get("nOrdNo")
                            elif not fallback_entry_order_id:
                                fallback_entry_order_id = row.get("nOrdNo")
                        elif (row.get("trnsTp") == "S" and str(row.get("prcTp", "")).upper() in ("SL", "SL-M")
                              and st not in TERMINAL_STATUSES and is_bot_placed):
                            sl_order_id = row.get("nOrdNo")
                            try:
                                sl_trigger_price = float(row.get("trgPrc"))
                            except (TypeError, ValueError):
                                sl_trigger_price = None
                        # Resting target/profit-booking leg (2026-09-08,
                        # alongside the SL leg above) - a bot-placed plain
                        # LIMIT sell ("L", not SL/SL-M) still resting for
                        # this symbol. Same is_bot_placed gate as the SL
                        # lookup: a manual limit sell the user placed
                        # directly at Kotak never carries this app's own
                        # algId/ordSrc tag, so it's never mistaken for
                        # this app's own target order.
                        elif (row.get("trnsTp") == "S" and str(row.get("prcTp", "")).upper() == "L"
                              and st not in TERMINAL_STATUSES and is_bot_placed):
                            target_order_id = row.get("nOrdNo")
                            try:
                                target_price = float(row.get("prc"))
                            except (TypeError, ValueError):
                                target_price = None
                    if not entry_order_id:
                        entry_order_id = fallback_entry_order_id  # a manual buy - still adopted (see above),
                        # just no bot-placed order id to attribute it to; None is fine here, entry_price
                        # (computed above from buyAmt/flBuyQty) is what governance actually needs.
                    watchlist_symbol = trd_sym[:-3] + ".NS" if trd_sym.endswith("-EQ") else trd_sym
                    conn.execute(
                        "INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, "
                        "entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, "
                        "target_order_id, target_price) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(symbol) DO NOTHING",
                        (watchlist_symbol, trd_sym, qty, entry_price, entry_order_id, time.time(),
                         ist_now().strftime("%Y-%m-%d"), sl_order_id, sl_trigger_price,
                         target_order_id, target_price),
                    )
                    adopted.append({
                        "symbol": watchlist_symbol, "kotak_trading_symbol": trd_sym, "qty": qty,
                        "entry_price": entry_price, "entry_order_id": entry_order_id,
                        "sl_order_id": sl_order_id, "sl_trigger_price": sl_trigger_price,
                        "target_order_id": target_order_id, "target_price": target_price,
                    })
                untracked = [u for u in untracked if u["kotak_trading_symbol"] not in
                             {a["kotak_trading_symbol"] for a in adopted}]

        # Governance backfill (2026-09-08, explicit user instruction:
        # "pick the live entered trades from Kotak and then track them
        # for their exit conditions, trailing SL and targets and
        # everything") - adopting into real_positions alone only
        # restores ORDER-ID tracking; it never fabricates a stop/target
        # this app itself never computed for a position it didn't (or
        # no longer remembers deciding to) open. Without a matching
        # signal_state row, _auto_signal_core's own position-management
        # block (trailing stop, leading target, trend-weakened, stale-
        # timeout, eod-squareoff - everything the paper engine already
        # does for its own entries) never runs for that symbol at all -
        # it only manages symbols it still has an open signal_state row
        # for. Runs UNCONDITIONALLY (not gated by `adopt`) so a symbol
        # already tracked in real_positions but missing its signal_state
        # counterpart (e.g. a restart wiped just the paper side) gets
        # fixed too, not only freshly-adopted ones. Reads the CURRENT
        # real_positions table and backfills any symbol with no open
        # signal_state row, sized off that symbol's own WATCHLIST risk
        # config (stop_pct, the live rr setting) applied to the REAL
        # entry price already on the real_positions row - the same math
        # a fresh entry would have used, computed after the fact.
        # entry_ts is set to NOW (backfill time), not a guessed real
        # fill time - pragmatic and safe: it only makes the trailing-
        # stop's "highest close since entry" window and the stale-
        # timeout's elapsed-time count start a little late, never early.
        watchlist_by_symbol_reconcile = {cfg["symbol"]: cfg for cfg in WATCHLIST}
        live_rr = get_runtime_setting(conn, "rr")
        governance_backfilled = []
        today_str_reconcile = ist_now().strftime("%Y-%m-%d")
        for r in conn.execute("SELECT * FROM real_positions").fetchall():
            already = conn.execute(
                "SELECT 1 FROM signal_state WHERE symbol = ? AND status = 'long'", (r["symbol"],)
            ).fetchone()
            if already:
                continue
            cfg = watchlist_by_symbol_reconcile.get(r["symbol"], {})
            stop_pct = cfg.get("stop_pct", 2.0)
            entry_price = r["entry_price"]
            stop_loss = round(entry_price * (1 - stop_pct / 100), 2)
            target = round(entry_price + live_rr * (entry_price - stop_loss), 2)
            conn.execute(
                "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, "
                "initial_stop_loss, target, qty, entry_ts, fx_to_inr, interval) "
                "VALUES (?, ?, 'long', ?, ?, ?, ?, ?, ?, 1.0, '5m') "
                "ON CONFLICT(symbol) DO NOTHING",
                (r["symbol"], today_str_reconcile, entry_price, stop_loss, stop_loss, target,
                 r["qty"], time.time()),
            )
            backfill_entry = {
                "symbol": r["symbol"], "entry_price": entry_price,
                "stop_loss": stop_loss, "target": target, "qty": r["qty"],
            }
            # Place the SL RIGHT HERE, in this same request - explicit
            # user finding 2026-09-08 (AARTIIND re-adopted with a
            # computed stop, still no resting SL minutes later): waiting
            # for "the next scheduler tick" to place it lost the race
            # almost every time, because this VERY endpoint's own
            # caller (kotak-reconcile.yml) commits + pushes an audit-log
            # file right after this call returns - and that push, like
            # every push this session, triggers a Render restart. The
            # restart routinely cut over and wiped the just-adopted
            # tracking again before a live scheduler tick ever got a
            # chance to run _maybe_sync_real_stop_loss for it. Placing
            # the SL synchronously inside THIS request closes that race
            # entirely - it happens before the wrapping workflow's own
            # git push, not after. Best-effort, same as every other SL
            # placement in this codebase (a failure here still leaves
            # the position tracked, logged, and picked up by the
            # scheduler's own normal retry-when-no-SL-is-resting path).
            if not r["sl_order_id"]:
                import kotak_real_orders
                sl_result = kotak_real_orders.place_real_stop_loss(
                    r["kotak_trading_symbol"], r["qty"], stop_loss
                )
                if sl_result.get("ok"):
                    conn.execute(
                        "UPDATE real_positions SET sl_order_id = ?, sl_trigger_price = ? WHERE symbol = ?",
                        (sl_result["order_id"], sl_result["trigger_price"], r["symbol"]),
                    )
                    _log_real_order_event(
                        conn, r["symbol"], "sl", "placed", kotak_trading_symbol=r["kotak_trading_symbol"],
                        order_id=sl_result["order_id"], prev_state="none",
                        new_state=f"resting SELL trigger Rs{sl_result['trigger_price']:.2f}",
                        detail="placed synchronously during governance backfill",
                    )
                    backfill_entry["sl_order_id"] = sl_result["order_id"]
                    backfill_entry["sl_placed"] = True
                else:
                    _log_real_order_event(
                        conn, r["symbol"], "sl", "failed", kotak_trading_symbol=r["kotak_trading_symbol"],
                        prev_state="none", new_state="none (placement failed)", detail=sl_result.get("detail"),
                    )
                    backfill_entry["sl_placed"] = False
                    backfill_entry["sl_failure_detail"] = sl_result.get("detail")
                    _flag_if_t1_restricted(conn, r["symbol"], sl_result.get("detail"))
            # Real resting target/profit-booking order - same gap as the
            # SL leg above, found live 2026-09-09 (explicit user finding:
            # "I can't see the order for profit booking order for each
            # trade" - MEDICAMEQ.NS was tracked in real_positions with a
            # real entry and (after this same backfill's SL leg) a real
            # SL, but target_order_id/target_price had been null the
            # whole time - the original entry flow's target placement
            # (see its own "paper_row and paper_row['target']" comment)
            # only fires when a matching signal_state row already exists
            # AT THE MOMENT OF ENTRY; a position adopted/backfilled here
            # never went through that path, so it was left with no
            # profit-booking mechanism at the broker at all. Mirrors the
            # SL backfill exactly - best-effort, never retried on a later
            # tick (matches the original entry-time placement's own
            # no-retry convention, see kotak_real_orders' "Real resting
            # target" docstring).
            if not r["target_order_id"]:
                import kotak_real_orders
                target_result = kotak_real_orders.place_real_target(r["kotak_trading_symbol"], r["qty"], target)
                if target_result.get("ok"):
                    conn.execute(
                        "UPDATE real_positions SET target_order_id = ?, target_price = ? WHERE symbol = ?",
                        (target_result["order_id"], target_result["target_price"], r["symbol"]),
                    )
                    _log_real_order_event(
                        conn, r["symbol"], "target", "placed", kotak_trading_symbol=r["kotak_trading_symbol"],
                        order_id=target_result["order_id"], prev_state="none",
                        new_state=f"resting SELL limit Rs{target_result['target_price']:.2f}",
                        detail="placed synchronously during governance backfill",
                    )
                    backfill_entry["target_order_id"] = target_result["order_id"]
                    backfill_entry["target_placed"] = True
                else:
                    # Still record the INTENDED target price - same
                    # reasoning as the entry-flow's own failure branch
                    # (2026-09-09, "Show me on render what is target for
                    # each entered trade").
                    conn.execute(
                        "UPDATE real_positions SET target_price = ? WHERE symbol = ?",
                        (target, r["symbol"]),
                    )
                    _log_real_order_event(
                        conn, r["symbol"], "target", "failed", kotak_trading_symbol=r["kotak_trading_symbol"],
                        prev_state="none", new_state="none (placement failed)", detail=target_result.get("detail"),
                    )
                    backfill_entry["target_placed"] = False
                    backfill_entry["target_failure_detail"] = target_result.get("detail")
                    # Found live 2026-09-09: MEDICAMEQ.NS's target attempt
                    # was rejected with Kotak's own T1-holdings RMS marker
                    # (same class the SL leg above already flags) - a plain
                    # limit SELL apparently gets checked against SETTLED
                    # holdings even though the SL leg (a contingent/trigger
                    # order, not immediately live) placed fine minutes
                    # earlier for the SAME same-day CNC position. Missing
                    # here before now - _flag_if_t1_restricted's own
                    # docstring says to call it at every real SL/exit
                    # rejection site, and this is one.
                    _flag_if_t1_restricted(conn, r["symbol"], target_result.get("detail"))
            governance_backfilled.append(backfill_entry)
        conn.commit()
        _sync_real_positions_external(conn)

    net_balance = None
    try:
        net_balance = float(limits_resp.get("Net")) if isinstance(limits_resp, dict) else None
    except (TypeError, ValueError):
        pass

    return {
        "reconciled_at_utc": time.time(), "real_balance_inr": net_balance,
        "qty_corrected_count": len(qty_corrected), "qty_corrected": qty_corrected,
        "removed_ghost_count": len(removed_ghosts), "removed_ghosts": removed_ghosts,
        "untracked_open_positions_count": len(untracked), "untracked_open_positions": untracked,
        "adopted_count": len(adopted), "adopted": adopted,
        "governance_backfilled_count": len(governance_backfilled), "governance_backfilled": governance_backfilled,
    }


@app.post("/kotak-neo/close-position")
def kotak_neo_close_position(request: Request, kotak_trading_symbol: str, qty: int, reason: str = "manual_close"):
    """Closes ONE real position by an EXPLICIT symbol + qty - a surgical
    tool for exactly the gap real_positions/signal_state can fall into
    (see this file's own history of untracked-position incidents): a
    real holding at Kotak this app's own tracking has no row for at all
    (so neither the kill switch - which only iterates real_positions -
    nor the paper engine's stop/target/stale-timeout logic - which only
    manages symbols in signal_state - can ever reach it), sitting with
    NO resting stop, NO target, and NO time-based exit, indefinitely.

    Built 2026-09-08, explicit user finding: 3 real positions (AARTIIND,
    ADANIPOWER, ABSLNN50ET) open 1.7-2.8 hours, all essentially flat
    (largest unrealized move +0.34%), none tracked in signal_state (a
    Render restart wiped that tracking, same restart-race as always) so
    none of them were ever going to hit this SAME session's own
    just-shipped stale-timeout exit - that logic only runs for symbols
    the paper engine still knows are open. "Take some action to avoid
    opportunity cost" - this endpoint is that action, applied by hand to
    a gap the automated system structurally cannot self-heal (adopting
    into real_positions only restores tracking + a resting SL where one
    already exists; it was never going to also fabricate a signal_state
    row with a stop/target this app never itself computed for these).

    Requires an EXPLICIT symbol + qty (never "figure out what's open and
    close it") - real money, no guessing. Cancels any resting SL/target
    order_id this app happens to have tracked for the symbol first (best-
    effort), places the real sell, deletes the real_positions row if one
    existed, and logs the event to both real_trades (_log_real_attempt)
    and the order-state log (_log_real_order_event) - the SAME audit
    trail every other real exit in this codebase writes to, so this
    shows up in /real-order-log and /order-log like any other exit, not
    as an invisible side-channel action.

    Requires ?token=<KOTAK_NEO_API_TOKEN>."""
    _require_kotak_token(request)
    import kotak_real_orders

    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM real_positions WHERE kotak_trading_symbol = ?", (kotak_trading_symbol,)
        ).fetchone()
        symbol_for_log = row["symbol"] if row else kotak_trading_symbol

        if row and row["sl_order_id"]:
            kotak_real_orders.cancel_real_order(row["sl_order_id"])
        if row and row["target_order_id"]:
            kotak_real_orders.cancel_real_order(row["target_order_id"])

        result = kotak_real_orders.place_real_exit(kotak_trading_symbol, qty)
        if result.get("ok"):
            if row:
                conn.execute("DELETE FROM real_positions WHERE kotak_trading_symbol = ?", (kotak_trading_symbol,))
            exit_qty = int(result["qty"])
            _log_real_attempt(
                conn, symbol_for_log, "S", "confirmed", kotak_trading_symbol=kotak_trading_symbol,
                qty=exit_qty, price_est=result.get("fill_price"),
                notional_inr=exit_qty * result["fill_price"] if result.get("fill_price") else None,
                order_id=result["order_id"], raw_response=result.get("raw_response"), detail=reason,
            )
            _log_real_order_event(
                conn, symbol_for_log, "exit", "confirmed", kotak_trading_symbol=kotak_trading_symbol,
                order_id=result["order_id"],
                prev_state=f"long {qty}" + (f" @ Rs{row['entry_price']:.2f}" if row else ""),
                new_state=f"closed, {exit_qty} @ Rs{result.get('fill_price') or 0:.2f}", detail=reason,
            )
            conn.commit()
            _sync_real_positions_external(conn)
            return {"ok": True, "kotak_trading_symbol": kotak_trading_symbol, "qty": exit_qty,
                    "fill_price": result.get("fill_price"), "fill_price_confirmed": result["fill_price_confirmed"],
                    "order_id": result["order_id"], "reason": reason}
        else:
            _log_real_attempt(
                conn, symbol_for_log, "S", "failed", kotak_trading_symbol=kotak_trading_symbol,
                qty=qty, detail=result.get("detail"), raw_response=result.get("raw_response"),
            )
            _flag_if_t1_restricted(conn, symbol_for_log, result.get("detail"))
            conn.commit()
            return {"ok": False, "kotak_trading_symbol": kotak_trading_symbol, "detail": result.get("detail")}


@app.get("/kotak-neo/search-scrip")
def kotak_neo_search_scrip(
    request: Request,
    exchange_segment: str = "nse_fo",
    symbol: str = "nifty",
    expiry: str | None = None,
    option_type: str | None = None,
    strike_price: str | None = None,
    limit: int = 20,
):
    """DIAGNOSTIC step toward a NIFTY option chain (2026-09-03) - returns
    RAW records from Kotak's live scrip master, unmodified except for
    truncation to `limit` rows. Deliberately not turned into a polished
    ATM-strike-chain-with-quotes endpoint yet: see kotak_neo.search_scrip's
    docstring for why (the instrument-token column name isn't documented
    anywhere in the SDK's source, so this is here to show it on real data
    before anything is built on top of it - guessing a field name on
    financial data risks silently matching the wrong contract). Real
    login required - places no order. Requires
    ?token=<KOTAK_NEO_API_TOKEN> (or an 'Authorization: Bearer <token>'
    header).

    `option_type` defaults to None, not "ce,pe" (bug fixed 2026-09-04) -
    a real call against exchange_segment=nse_cm (pure equity, no options)
    with the old "ce,pe" default crashed inside the SDK itself
    ("Can only use .str accessor with string values!") because nse_cm's
    scrip master has no meaningful pOptionType column to filter on. Only
    pass option_type for an actual options segment (nse_fo/bse_fo)."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        result = kotak_neo.search_scrip(
            exchange_segment=exchange_segment, symbol=symbol, expiry=expiry,
            option_type=option_type, strike_price=strike_price,
        )
        if isinstance(result, list):
            return {"total_matched": len(result), "showing": result[:limit]}
        return _kotak_json_safe(result)
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/margin-required")
def kotak_neo_margin_required(
    request: Request, exchange_segment: str, instrument_token: str, transaction_type: str,
    quantity: str = "1", order_type: str = "MKT", product: str = "NRML",
    price: str = "0", trigger_price: str | None = None,
):
    """DIAGNOSTIC - computes margin for a HYPOTHETICAL order, places
    NOTHING (see kotak_neo.margin_required's own docstring - it's a
    dedicated margin-calculation endpoint, not place_order). Built
    2026-09-07 as the real, non-destructive way to verify whether a
    segment (F&O, currency, commodity) is actually tradeable on this
    account, after an earlier guess from a scrip-master field
    (iPermittedToTrade) turned out unreliable - the account's own Kotak
    Neo "Segment activation" page is the authoritative source for that,
    but this gives a real API-level signal to cross-check against.
    Requires ?token=<KOTAK_NEO_API_TOKEN>, same as every other real-
    Kotak-data endpoint."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        return _kotak_json_safe(kotak_neo.margin_required(
            exchange_segment=exchange_segment, instrument_token=instrument_token,
            transaction_type=transaction_type, quantity=quantity, order_type=order_type,
            product=product, price=price, trigger_price=trigger_price,
        ))
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/scrip-master")
def kotak_neo_scrip_master(request: Request, exchange_segment: str = "nse_cm", raw_bytes: int = 4000):
    """DIAGNOSTIC step toward sourcing the equity WATCHLIST universe from
    Kotak instead of NSE's own website (2026-09-05, explicit user
    instruction: "can't you source it from kotak neo" - NSE's own official
    list is unreachable both from GitHub Actions, per KNOWN_ISSUES.md-style
    Akamai bot-protection, and from this project's own sandbox, per its
    network egress policy). Real login required - places no order.
    Requires ?token=<KOTAK_NEO_API_TOKEN> (or an 'Authorization: Bearer
    <token>' header).

    Deliberately does NOT use pandas here (2026-09-05: an earlier version
    did - pd.read_csv(csv_url) then df.to_dict() - and crashed live with a
    bare, detail-free "Internal Server Error" even after fixing the
    obvious numpy/NaN JSON-serialization issue. That signature (no
    Python-level error at all, not even from this function's own
    try/except) points at the worker process itself dying - most likely
    an OOM kill from loading + parsing a full scrip-master CSV into a
    DataFrame on Render's free-tier memory limit, not a code bug this
    function can catch. Fixed by reading only the first `raw_bytes` of
    the real file directly (urllib, streaming, capped) instead of loading
    the whole thing - same "see the real shape on real data" goal, just
    without the memory risk. Once real column names are confirmed this
    way, the actual filtering step can stream+filter row-by-row rather
    than holding the whole file in memory, avoiding this class of crash
    for good."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        csv_url = kotak_neo.scrip_master(exchange_segment=exchange_segment)
        if not isinstance(csv_url, str):
            return {"error": "scrip_master did not return a CSV URL", "raw": _kotak_json_safe(csv_url)}
    except Exception as e:
        return {"error": f"scrip_master() call failed: {e}"}

    try:
        import urllib.request
        req = urllib.request.Request(csv_url, headers={"User-Agent": "tv-paper-bot/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_length = resp.headers.get("Content-Length")
            chunk = resp.read(raw_bytes)
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return {
            "csv_url": csv_url,
            "content_length_bytes": content_length,
            "bytes_actually_read": len(chunk),
            "header_row": lines[0] if lines else None,
            "first_rows": lines[1:4],
            # Search the whole fetched chunk for a known real equity
            # (RELIANCE) - confirms what the pGroup/pInstType columns
            # actually look like for a genuine EQ-series stock, vs. the
            # index/InvIT rows the first few lines happened to show.
            "reliance_rows": [ln for ln in lines if "RELIANCE" in ln][:5],
        }
    except Exception as e:
        return {"error": f"raw fetch of the CSV failed: {e}", "csv_url": csv_url}


@app.get("/nse-asm-probe")
def nse_asm_probe():
    """DIAGNOSTIC ONLY - one-shot reachability test for NSE's own ASM
    (Additional Surveillance Measure) list, a step toward proactively
    avoiding Trade-to-Trade (T2T) same-day-sell-restricted symbols BEFORE
    a real entry, not just reactively after a rejection (explicit user
    instruction 2026-09-09: "build a proactive filter... fetch NSE's
    actual T2T securities list").

    2026-09-09 finding that sent this here in the first place: Kotak's
    own scrip master pGroup field (the field /kotak-neo/nse-universe
    already trusts to build the whole WATCHLIST) does NOT catch this -
    verified live: MEDICAMEQ.NS/SILVERCASE.NS/DCMSIL.NS/DEEP.NS (all 4
    confirmed T2T-restricted via a real Kotak rejection today) are ALL
    present in docs/nse_universe.json's pGroup=="EQ" list. This makes
    sense once you know WHY: ASM/GSM (what actually caused today's
    rejections) is a TEMPORARY surveillance overlay NSE applies to
    otherwise-normal EQ-series stocks based on live volatility/
    concentration criteria - reviewed periodically, not baked into the
    static scrip master at all. The permanent BE/BZ series pGroup
    already excludes is a DIFFERENT, unrelated T2T mechanism.

    scrip_master()'s own docstring already found nseindia.com's domains
    Akamai-blocked from both GitHub Actions and this project's sandbox -
    but neither of those IS this app's own live egress path. This is the
    one untested environment: Render itself. No token required (read-
    only, no account data, same precedent as every other diagnostic
    endpoint here) - reports success/failure/raw content preview so the
    real proactive filter gets built on confirmed data, not a guess,
    same "verify real shape before parsing it" discipline scrip_master's
    own docstring already established."""
    import urllib.request
    url = "https://www.nseindia.com/reports/asm"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            chunk = resp.read(3000)
        return {
            "reachable": True, "url": url, "status": resp.status,
            "content_preview": chunk.decode("utf-8", errors="replace"),
        }
    except Exception as e:
        return {"reachable": False, "url": url, "error": str(e)}


@app.get("/kotak-neo/nse-universe")
def kotak_neo_nse_universe(request: Request):
    """Builds the real, current NSE cash-equity universe from Kotak's own
    live scrip master (2026-09-05, explicit user instruction: "can't you
    source it from kotak neo. all the tickers which it can provide" -
    after NSE's own official Nifty 500 list turned out unreachable from
    both GitHub Actions and this project's own sandbox). Filter confirmed
    on real data via /kotak-neo/scrip-master before writing this: pGroup
    == "EQ" is exactly NSE's own main-board equity series (excludes BE/BZ/
    other restricted series - verified against real RELIANCE/RELINFRA/RHFL
    rows), same semantic as the original NSE-direct refresh workflow's
    SERIES=EQ filter, just sourced from Kotak's CDN instead of NSE's
    Akamai-blocked one.

    Uses csv.DictReader on the full response text, NOT pandas - the
    scrip-master CSV is ~3.2MB with 70+ columns; an earlier version used
    pd.read_csv() and crashed the whole worker (OOM on Render's free
    tier), confirmed by isolating the raw fetch (safe) from the pandas
    parse (not) via /kotak-neo/scrip-master. Reading the full text as a
    plain string is confirmed safe at this file size; csv.DictReader has
    none of a DataFrame's per-column dtype/numpy overhead.

    Returns the same shape docs/nse_universe.json uses (source, series,
    count, symbols) so a caller can write it directly. Real login
    required - places no order. Requires ?token=<KOTAK_NEO_API_TOKEN> (or
    an 'Authorization: Bearer <token>' header)."""
    _require_kotak_token(request)
    try:
        import csv
        import io
        import kotak_neo
        csv_url = kotak_neo.scrip_master(exchange_segment="nse_cm")
        if not isinstance(csv_url, str):
            return {"error": "scrip_master did not return a CSV URL", "raw": _kotak_json_safe(csv_url)}

        import urllib.request
        req = urllib.request.Request(csv_url, headers={"User-Agent": "tv-paper-bot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        symbols = set()
        for row in reader:
            if row.get("pGroup") == "EQ" and row.get("pExchSeg") == "nse_cm":
                name = (row.get("pSymbolName") or "").strip()
                if name:
                    symbols.add(f"{name}.NS")

        symbols = sorted(symbols)
        if len(symbols) < 500:
            # Sanity floor, same discipline as the original NSE-direct
            # refresh workflow - refuse to look "successful" on a
            # truncated/malformed fetch.
            return {"error": f"Only {len(symbols)} EQ symbols parsed from Kotak's scrip master - "
                              f"refusing to treat this as a real universe, looks wrong", "csv_url": csv_url}

        return {"source": "Kotak Neo scrip master (nse_cm)", "series": "EQ",
                "count": len(symbols), "symbols": symbols}
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/quotes")
def kotak_neo_quotes(request: Request, exchange_segment: str = "nse_cm", instrument_token: str = "Nifty 50", quote_type: str = "ltp"):
    """Real live quote for ONE instrument. Read-only - places no order.
    Requires ?token=<KOTAK_NEO_API_TOKEN>.

    Built 2026-09-04 specifically to verify index instrument-token names
    (e.g. is "Nifty Bank" real) before hardcoding them into
    kotak_live_feed.py - search_scrip can't confirm these since indices
    aren't scrip-master rows; only an actual quotes() call can."""
    _require_kotak_token(request)
    try:
        import kotak_neo
        result = kotak_neo.quotes(
            instrument_tokens=[{"instrument_token": instrument_token, "exchange_segment": exchange_segment}],
            quote_type=quote_type,
        )
        return _kotak_json_safe(result)
    except Exception as e:
        return {"error": str(e)}


@app.get("/kotak-neo/comprehensive")
def kotak_neo_comprehensive(request: Request):
    """Eligible stocks + the full NSE F&O universe, per explicit user
    instruction (2026-09-04): "fetch eligible stocks for me and also the
    futures and options data too in the comprehensive list" - "full raw
    dump, no filtering" was the user's explicit choice after being warned
    this would be large (a 'nifty' substring search alone matched 11,822
    contracts the same day; this is the FULL nse_fo segment, markedly
    bigger still - tens of thousands of rows, likely a multi-MB response.
    Real login required - places no order. Requires
    ?token=<KOTAK_NEO_API_TOKEN> (or an 'Authorization: Bearer <token>'
    header).

    Shape:
      - eligible_equities: same rows as GET /watchlist (today's paper-
        tradeable universe - indices + Nifty 100 + MCX commodity proxies,
        see that endpoint's docstring for what "eligible" means here).
      - fo_universe: EVERY contract in Kotak's live nse_fo scrip master -
        every index/stock option and future, every strike, every expiry,
        completely unfiltered (search_scrip's symbol="" skips Kotak's own
        symbol filter entirely). Raw records, unmodified."""
    _require_kotak_token(request)
    eligible_equities = watchlist()["symbols"]
    try:
        import kotak_neo
        fo_universe = kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="")
    except Exception as e:
        return {
            "eligible_equities_count": len(eligible_equities),
            "eligible_equities": eligible_equities,
            "fo_universe_error": str(e),
        }
    if not isinstance(fo_universe, list):
        # A real Kotak-side error shape (e.g. {"error": [...]}), not a
        # Python exception - _kotak_json_safe handles any non-serializable
        # bits the same way the Phase 2 endpoints do.
        return {
            "eligible_equities_count": len(eligible_equities),
            "eligible_equities": eligible_equities,
            "fo_universe_error": _kotak_json_safe(fo_universe),
        }
    return {
        "eligible_equities_count": len(eligible_equities),
        "eligible_equities": eligible_equities,
        "fo_universe_count": len(fo_universe),
        "fo_universe": fo_universe,
    }


@app.get("/live")
def live():
    """Self-refreshing NIFTY/BANKNIFTY/SENSEX/India VIX dashboard."""
    return FileResponse("static/live.html")


@app.get("/trade-view")
def trade_view():
    """Self-refreshing candlestick chart for whatever position(s) are
    currently open, with entry/stop/target/opening-range lines overlaid -
    pulls live from /daily-summary + /history client-side, same pattern
    as /live."""
    return FileResponse("static/trade-view.html")
