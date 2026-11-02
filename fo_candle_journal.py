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
# B-1447: per-day (db file, row count, max id) seen at the last full build of that day's payload. The table is
# append-only (INSERT OR IGNORE, AUTOINCREMENT id), so an unchanged fingerprint means the day's rows, and hence its
# payload, are unchanged. Before this, every 5-min sync re-materialised EVERY local day (~2,300 option tokens x ~75
# bars = ~170k rows -> lists + JSON + sha per day, ~150 MB transient each) only to find the hash unchanged, and the
# work grew with every day of uptime / restored history: the multi-day native-heap ratchet behind B-1447.
_last_fp: dict = {}


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
    return sorted(local_day_fingerprints(conn))


_IST_OFFSET_S = 5 * 3600 + 30 * 60


def local_day_fingerprints(conn) -> dict:
    """B-1447: {IST day: (row count, max id)} in ONE grouped scan, no rows materialised in Python."""
    out = {}
    for d, n, mx in conn.execute(
            "SELECT CAST((bucket_start_ts + ?) / 86400 AS INTEGER) AS d, COUNT(*), MAX(id) "
            "FROM fo_option_candles GROUP BY d", (_IST_OFFSET_S,)).fetchall():
        day = (datetime(1970, 1, 1) + timedelta(days=int(d))).strftime("%Y-%m-%d")
        prev = out.get(day)
        out[day] = (int(n), int(mx)) if prev is None else (prev[0] + int(n), max(prev[1], int(mx)))
    return out


def _db_file(conn) -> str:
    try:
        for row in conn.execute("PRAGMA database_list").fetchall():
            if row[1] == "main":
                return str(row[2] or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _prune_day_state(keep_days) -> None:
    """B-1447: drop per-day bookkeeping for days no longer in the local table (bounded by local history)."""
    keep = set(keep_days)
    for d in (_last_hash, _last_push_ts, _last_fp):
        for k in [k for k in d if k not in keep]:
            d.pop(k, None)


def sync_to_remote(conn, get, set_, now: float | None = None) -> int:
    """Push every local day whose content changed. Returns days pushed."""
    now = time.time() if now is None else now
    today = ist_day(now)
    pushed = 0
    known = None
    fps = local_day_fingerprints(conn)
    db = _db_file(conn)
    _prune_day_state(fps)
    for day in sorted(fps):
        if day == today and now - _last_push_ts.get(day, 0) < CURRENT_DAY_MIN_PUSH_SECONDS:
            continue
        fp = (db,) + fps[day]
        if _last_fp.get(day) == fp:
            continue  # B-1447: rows unchanged since the last build -> same payload, nothing to push
        if known is None:
            known = set(_get_days(get))
        lo, hi = _day_bounds(day)
        rows = [list(r) for r in conn.execute(
            f"SELECT {','.join(COLUMNS)} FROM fo_option_candles "
            "WHERE bucket_start_ts >= ? AND bucket_start_ts < ? "
            "ORDER BY bucket_start_ts, instrument_token", (lo, hi)).fetchall()]
        payload = json.dumps(rows, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if _last_hash.get(day) == digest:
            _last_fp[day] = fp
            continue
        meta_raw = get(_key(day, "meta"))
        if meta_raw and int(json.loads(meta_raw).get("rows", 0)) > len(rows):
            _last_fp[day] = fp  # re-checked only once local rows change (remote meta only grows from this process)
            continue  # remote holds more (e.g. after a wipe): restore first, never shrink
        chunks = [payload[i:i + CHUNK_CHARS] for i in range(0, len(payload), CHUNK_CHARS)]
        for i, chunk in enumerate(chunks):
            set_(_key(day, f"c{i}"), chunk)
        set_(_key(day, "meta"), json.dumps({"chunks": len(chunks), "rows": len(rows), "synced_at": now}))
        known.add(day)
        set_(f"{PREFIX}:days", json.dumps(sorted(known)))
        _last_hash[day] = digest
        _last_push_ts[day] = now
        _last_fp[day] = fp
        del rows, payload, chunks
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
