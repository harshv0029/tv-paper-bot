"""Durable accumulation of fo_option_candles (backlog B-860).

fo_option_candles lives in SQLite on Render's ephemeral disk and was
deliberately excluded from main._GENERIC_MIRROR_TABLES as a "re-fetchable
cache". It is not re-fetchable: Kotak serves no historical option candles, so
every restart wiped the only real option-premium history this bot ever
collects. This module keeps it durably in Upstash Redis, one entry set per IST
trading day, so the history accumulates across restarts and can be exported
later for a real-premium backtest.

Layout (all keys under tv_paper_bot:focandles:v1):
  <prefix>:days           JSON list of IST day strings that have data
  <prefix>:<day>:meta     {"chunks": n, "rows": n, "synced_at": ts}
  <prefix>:<day>:c<i>     chunk i of the JSON row-array for that day
Rows are compact arrays in COLUMNS order. The Upstash get/set callables are
injected so this module has no dependency on main and is unit-testable.

Rules kept: restore is INSERT OR IGNORE (never overwrites a local bar); a day
is never pushed with fewer rows than the remote copy already holds (a freshly
wiped local DB cannot shrink history); everything is best-effort and silent.
"""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

PREFIX = "tv_paper_bot:focandles:v1"
CHUNK_CHARS = 600_000
RESTORE_DAYS = 15            # bound startup work; older days stay in Upstash
CURRENT_DAY_MIN_PUSH_SECONDS = 600
COLUMNS = ("instrument_token", "kotak_trading_symbol", "underlying", "kind", "right",
           "strike", "expiry", "bucket_start_ts", "open", "high", "low", "close", "tick_count")
IST = timezone(timedelta(hours=5, minutes=30))

_last_hash: dict = {}
_last_push_ts: dict = {}


def ist_day(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), IST).strftime("%Y-%m-%d")


def _day_bounds(day: str):
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=IST)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _key(day: str, suffix: str) -> str:
    return f"{PREFIX}:{day}:{suffix}"


def _get_days(get) -> list:
    raw = get(f"{PREFIX}:days")
    return sorted(json.loads(raw)) if raw else []


def local_days(conn) -> list:
    rows = conn.execute("SELECT DISTINCT bucket_start_ts FROM fo_option_candles").fetchall()
    return sorted({ist_day(r[0]) for r in rows})


def sync_to_remote(conn, get, set_, now: float | None = None) -> int:
    """Push every local day whose content changed. Returns days pushed."""
    now = time.time() if now is None else now
    today = ist_day(now)
    pushed = 0
    known = set(_get_days(get))
    for day in local_days(conn):
        if day == today and now - _last_push_ts.get(day, 0) < CURRENT_DAY_MIN_PUSH_SECONDS:
            continue
        lo, hi = _day_bounds(day)
        rows = [list(r) for r in conn.execute(
            f"SELECT {','.join(COLUMNS)} FROM fo_option_candles "
            "WHERE bucket_start_ts >= ? AND bucket_start_ts < ? "
            "ORDER BY bucket_start_ts, instrument_token", (lo, hi)).fetchall()]
        payload = json.dumps(rows, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if _last_hash.get(day) == digest:
            continue
        meta_raw = get(_key(day, "meta"))
        if meta_raw and int(json.loads(meta_raw).get("rows", 0)) > len(rows):
            continue  # remote holds more (e.g. after a wipe): restore first, never shrink
        chunks = [payload[i:i + CHUNK_CHARS] for i in range(0, len(payload), CHUNK_CHARS)]
        for i, chunk in enumerate(chunks):
            set_(_key(day, f"c{i}"), chunk)
        set_(_key(day, "meta"), json.dumps({"chunks": len(chunks), "rows": len(rows), "synced_at": now}))
        known.add(day)
        set_(f"{PREFIX}:days", json.dumps(sorted(known)))
        _last_hash[day] = digest
        _last_push_ts[day] = now
        pushed += 1
    return pushed


def restore_from_remote(conn, get, max_days: int = RESTORE_DAYS) -> int:
    """Insert (OR IGNORE) every remote bar for the most recent days. Returns rows inserted.

    B-865: NEWEST day first and committed per day. Startup gives this only a
    few seconds (STARTUP_HYDRATION_TIMEOUT_SECONDS); the old oldest-first order
    with one final commit spent that budget on 14 old days and restored
    today's bars (the only ones the 30-candle scan needs) last or never."""
    inserted = 0
    for day in reversed(_get_days(get)[-max_days:]):
        meta_raw = get(_key(day, "meta"))
        if not meta_raw:
            continue
        parts = []
        for i in range(int(json.loads(meta_raw).get("chunks", 0))):
            part = get(_key(day, f"c{i}"))
            if part is None:
                parts = None
                break
            parts.append(part)
        if parts is None:
            continue  # incomplete remote copy: never half-restore
        marks = ",".join("?" for _ in COLUMNS)
        before = conn.total_changes
        for row in json.loads("".join(parts)):
            conn.execute(f"INSERT OR IGNORE INTO fo_option_candles ({','.join(COLUMNS)}) VALUES ({marks})", row)
        inserted += conn.total_changes - before
        conn.commit()
    return inserted


def export_day_rows(get, day: str) -> list:
    """Remote rows for one IST day as dicts (for a later research export)."""
    meta_raw = get(_key(day, "meta"))
    if not meta_raw:
        return []
    parts = [get(_key(day, f"c{i}")) for i in range(int(json.loads(meta_raw).get("chunks", 0)))]
    if any(p is None for p in parts):
        return []
    return [dict(zip(COLUMNS, r)) for r in json.loads("".join(parts))]
