"""2026-10-06 (user: "Maintain each log with reason that why u executed any
order"): every real exit call site must state a reason, and the order-event
log must store it."""
import ast
import re
import sqlite3
from pathlib import Path

import main

EXIT_FNS = {"_maybe_place_real_exit", "_maybe_place_real_short_exit", "_maybe_place_real_swing_exit"}


def test_every_exit_call_site_passes_a_reason():
    tree = ast.parse(Path(main.__file__).read_text())
    missing = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in EXIT_FNS:
            if not any(k.arg == "reason" for k in n.keywords):
                missing.append(n.lineno)
    assert not missing, f"exit calls without reason= at lines {missing}"


def test_reason_is_prefixed_into_event_detail():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE real_order_events (id INTEGER PRIMARY KEY, ts REAL, symbol TEXT, "
                 "kotak_trading_symbol TEXT, leg TEXT, event TEXT, order_id TEXT, prev_state TEXT, "
                 "new_state TEXT, detail TEXT)")
    main._log_real_order_event(conn, "SAIL.NS", "exit", "confirmed", detail="fill ok", reason="stop_hit")
    main._log_real_order_event(conn, "SAIL.NS", "exit", "confirmed", reason=main._REASON_UNSTATED)
    d = [r["detail"] for r in conn.execute("SELECT detail FROM real_order_events ORDER BY id")]
    assert d[0] == "reason: stop_hit | fill ok"
    assert re.match(r"reason: UNSTATED", d[1])
