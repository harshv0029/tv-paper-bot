"""B-1252 (1) /entry-why no-balance endpoint, (3) stale non-real rows excluded from reserve."""
import json
from contextlib import closing

import main
from tests.test_review_bugfixes import _fresh_db


def _ins(conn, sym, day):
    conn.execute(
        "INSERT INTO signal_state (symbol, day, status, entry_price, stop_loss, initial_stop_loss, "
        "target, qty, entry_ts, fx_to_inr, interval) VALUES (?, ?, 'long', 100.0, 98.0, 98.0, 106.0, 10, ?, 1.0, '5m')",
        (sym, day, main.time.time()))


def test_stale_non_real_row_excluded_when_today_given():
    _fresh_db()
    today = main.ist_now().strftime("%Y-%m-%d")
    with closing(main.get_db()) as conn:
        _ins(conn, "A.NS", today)
        _ins(conn, "OLD.NS", "2020-01-01")
        conn.commit()
        assert main._open_positions_reserved_risk_inr(conn) == 40.0
        assert main._open_positions_reserved_risk_inr(conn, today_str=today) == 20.0


def test_stale_row_with_real_position_kept():
    _fresh_db()
    today = main.ist_now().strftime("%Y-%m-%d")
    with closing(main.get_db()) as conn:
        _ins(conn, "OLD.NS", "2020-01-01")
        info = conn.execute("PRAGMA table_info(real_positions)").fetchall()
        vals = {r[1]: 0 for r in info if r[3] and r[4] is None}
        vals["symbol"] = "OLD.NS"
        conn.execute(f"INSERT INTO real_positions ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                     list(vals.values()))
        conn.commit()
        assert main._open_positions_reserved_risk_inr(conn, today_str=today) == 20.0


def test_entry_why_ratio_only_no_balances():
    main._scheduler_last_results["ZZ.NS"] = {
        "action_taken": "blocked_aggregate_open_risk", "daily_loss_cap_inr": 200.0,
        "open_reserved_risk_inr": 300.0, "realized_loss_today_inr": 0.0, "available_capital_inr": 5555.0}
    try:
        body = main.entry_why()
        row = body["symbols"]["ZZ.NS"]
        assert row["gate"] == "aggregate_open_risk" and row["ratio"]["reserved_vs_cap"] == 1.5
        txt = json.dumps(body)
        assert "5555" not in txt and "300" not in txt and "inr" not in txt.lower()
    finally:
        main._scheduler_last_results.pop("ZZ.NS", None)
