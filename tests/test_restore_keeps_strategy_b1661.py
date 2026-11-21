"""B-1661 (ASHOKLEY 2026-11-18 IST): a Render restart between a buy-engine entry (09:39) and its exit (10:33)
restored real_positions without `strategy`, so _maybe_place_real_exit saw an untagged row next to a paper swing row,
refused the exit as swing-owned and the position was rerouted to swing. Both restore paths must keep `strategy`."""
import json
from contextlib import closing

import main

SYM = "B1661TEST.NS"
ROW = {"symbol": SYM, "kotak_trading_symbol": "B1661TEST-EQ", "qty": 1, "entry_price": 100.0, "opened_at": 1.0,
       "day": "2026-11-18", "product": "MIS",
       "strategy": "chan_kalman__band_srcmain__long__15m__atr4d0_hold40_ve10d0e4_z1d0__v1"}


def _clear():
    with closing(main.get_db()) as c:
        c.execute("DELETE FROM real_positions WHERE symbol = ?", (SYM,))
        c.execute("DELETE FROM signal_state_swing WHERE symbol = ?", (SYM,))
        c.commit()


def _strategy():
    with closing(main.get_db()) as c:
        r = c.execute("SELECT strategy FROM real_positions WHERE symbol = ?", (SYM,)).fetchone()
    return r["strategy"] if r else None


def test_upstash_restore_keeps_strategy(monkeypatch):
    _clear()
    payload = json.dumps({"rows": [ROW]})
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "https://x")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")

    class _R:
        status_code = 200

        def json(self):
            return {"result": payload}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: _R())
    monkeypatch.setattr(main, "_upstash_unmask", lambda key, v: v)
    assert main.hydrate_real_positions_from_external() is True
    try:
        assert _strategy() == ROW["strategy"]
    finally:
        _clear()


def test_journal_restore_keeps_strategy(monkeypatch, tmp_path):
    _clear()
    p = tmp_path / "real.json"
    p.write_text(json.dumps({"open_real_positions": [ROW]}))
    monkeypatch.setattr(main, "STATE_REAL_POSITIONS_PATH", str(p))
    main.reconcile_real_positions_from_journal()
    try:
        assert _strategy() == ROW["strategy"]
    finally:
        _clear()
