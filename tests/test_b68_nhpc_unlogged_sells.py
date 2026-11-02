"""B-68 follow-up (2026-11-02): NHPC's two unlogged Kotak MARKET SELLs on 28 Oct (12:08:16 and 12:32:59 IST).

1. An accepted app market SELL that is still queued in memory (B-1448 holds accepted sends up to 30 s) is written
   on a graceful shutdown, so a Render restart cannot turn the app's own fill into an 'UNLOGGED' row that looks
   like a manual Kotak order.
2. Engine ownership: the intraday partial-exit ladder never sells a symbol the swing engine owns (the full intraday
   exit already refused; the partial exit did not).

Run: pytest tests/test_b68_nhpc_unlogged_sells.py -v
"""
import json
import time
from contextlib import closing

import main


def _events():
    with closing(main.get_db()) as c:
        return [dict(r) for r in c.execute("SELECT leg, event, order_id, detail FROM real_order_events "
                                           "ORDER BY id").fetchall()]


def test_shutdown_flushes_accepted_market_sell(monkeypatch):
    main.init_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **kw: None)
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_order_events")
        c.commit()
    monkeypatch.setattr(main, "_PENDING_KOTAK_SENDS", [])
    main._kotak_send_sink({"symbol": "NHPC.NS", "kotak_trading_symbol": "NHPC-EQ", "leg": "exit",
                           "event": "kotak_placed", "order_id": "261028000366122", "new_state": "accepted",
                           "detail": None, "reason": "real market SELL exit; Kotak accepted it",
                           "immediate": False, "ts": time.time()})
    assert _events() == [], "an accepted send is held briefly, not written at once"
    main._flush_kotak_sends_on_shutdown()
    rows = _events()
    assert [(r["leg"], r["event"], r["order_id"]) for r in rows] == [("exit", "kotak_placed", "261028000366122")]
    assert rows[0]["detail"].startswith("reason: real market SELL exit")
    assert main._PENDING_KOTAK_SENDS == []


def _fill_required(c, table, given):
    vals = dict(given)
    for r in c.execute(f"PRAGMA table_info({table})").fetchall():  # every NOT NULL column without a default
        name, typ, notnull, dflt = r[1], (r[2] or "").upper(), r[3], r[4]
        if name not in vals and notnull and dflt is None and not r[5]:
            vals[name] = 0 if ("INT" in typ or "REAL" in typ) else "x"
    return vals


def test_partial_exit_refuses_swing_owned_symbol(monkeypatch):
    main.init_db()
    sym = "NHPCB68.NS"
    legs = [{"leg": "t1", "qty": 1, "status": "open"}]
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_positions WHERE symbol = ?", (sym,))
        c.execute("DELETE FROM signal_state_swing WHERE symbol = ?", (sym,))
        row = _fill_required(c, "real_positions", {"symbol": sym, "kotak_trading_symbol": "NHPCB68-EQ",
                                                   "qty": 2, "exit_legs_json": json.dumps(legs)})
        c.execute(f"INSERT INTO real_positions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                  tuple(row.values()))
        vals = _fill_required(c, "signal_state_swing", {"symbol": sym})
        c.execute(f"INSERT INTO signal_state_swing ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                  tuple(vals.values()))
        c.commit()

    import kotak_real_orders

    sent = []
    monkeypatch.setattr(kotak_real_orders, "place_real_exit", lambda *a, **k: sent.append(a) or {"ok": True})
    with closing(main.get_db()) as c:
        main._maybe_place_real_partial_exit(c, sym, {"leg": "t1"})
        c.execute("DELETE FROM real_positions WHERE symbol = ?", (sym,))
        c.execute("DELETE FROM signal_state_swing WHERE symbol = ?", (sym,))
        c.commit()
    assert sent == [], "the intraday partial exit must never sell a swing-owned symbol"
