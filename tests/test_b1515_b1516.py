"""B-1515 (ZYDUSLIFE 1-share sizing) and B-1516 (bot orders tagged UNLOGGED after a restart)."""
import base64
import json

import main


# ---------------------------------------------------------------- B-1515

def _sized(monkeypatch, net, ltp, stop):
    monkeypatch.setattr(main, "_refresh_real_capital_cache", lambda: None)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: net)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: False)
    return main._real_swing_qty_by_risk(None, "ZYDUSLIFE.NS", ltp, stop)


def test_zyduslife_one_share_within_fresh_net(monkeypatch):
    """Live 2026-11-09 IST: Net Rs9,239.93 at the decision -> limit Rs92.40 >= Rs83.80 at the resting stop -> 1."""
    assert _sized(monkeypatch, 9239.93, 1207.50, 1123.70) == 1


def test_zyduslife_refused_on_earlier_net(monkeypatch):
    """Same day 11:18-12:17 IST, Net Rs7,405.33 -> limit Rs74.05 < Rs83.80 -> 0 (logged skipped_insufficient_real_qty)."""
    assert _sized(monkeypatch, 7405.33, 1207.50, 1123.70) == 0
    assert _sized(monkeypatch, 5900.0, 1207.50, 1123.70) == 0


def test_intraday_path_same_floor(monkeypatch):
    monkeypatch.setattr(main, "_refresh_real_capital_cache", lambda: None)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 5900.0)
    assert main._real_qty_by_risk(1207.50, 1123.70, 1.0) == 0
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 9239.93)
    assert main._real_qty_by_risk(1207.50, 1123.70, 1.0) == 1


def test_resting_stop_never_wider_than_sizing_stop(monkeypatch):
    """Every stop adjustment after sizing only raises a long stop, so the sized risk bounds the resting risk."""
    import kotak_real_orders as kro
    monkeypatch.setattr(kro, "_entry_day_floor", lambda s, side: 1100.0)  # a lower floor never loosens
    monkeypatch.setattr(kro, "_band_reference", lambda s: (1245.0, 1207.5))
    trg, _ = kro.apply_entry_day_floor("ZYDUSLIFE-EQ", 1123.70, "long")
    assert trg >= 1123.70
    assert main._swing_stop_below_price(1123.70, 1207.50) == 1123.70


def test_sizing_basis_note_names_net_and_limit():
    note = main._real_sizing_basis_note(1207.50, 1123.70, 9239.93, 1)
    assert "Rs83.80/share" in note and "Rs9,239.93" in note and "Rs92.40" in note


def test_post_fill_risk_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "r.db"))
    main.init_db()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda **k: None)
    with main.closing(main.get_db()) as c:
        assert main._flag_real_risk_after_fill(c, "ZYDUSLIFE.NS", "ZYDUSLIFE-EQ", 1, 1207.50, 1123.70, 9239.93) is False
        assert main._flag_real_risk_after_fill(c, "ZYDUSLIFE.NS", "ZYDUSLIFE-EQ", 1, 1207.50, 1123.70, 5900.0) is True
        row = c.execute("SELECT event, detail FROM real_order_events WHERE event = 'risk_over_limit_after_fill'").fetchone()
    assert row and "Rs83.80 at risk > Rs59.00" in row[1]


# ---------------------------------------------------------------- B-1516

class _R:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _db(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "o.db"))
    main.init_db()
    monkeypatch.setattr(main, "_git_tier_hydrated", set(t for t in main._GENERIC_MIRROR_GIT_TIER if t != "real_order_events"))
    monkeypatch.setattr(main, "_git_tier_unhydrated_since", {})
    monkeypatch.setattr(main, "_git_tier_hydrate_last_retry", [0.0])


def test_failed_boot_restore_is_retried_and_merges(monkeypatch, tmp_path):
    """Live 2026-11-07..09: the one boot restore failed, nothing retried it, so the order log was never pushed and the
    09:15-10:56 IST rows died with the 10:57 restart. The push loop now retries; a late restore merges on content."""
    _db(monkeypatch, tmp_path)
    monkeypatch.setattr(main.requests, "get", lambda url, **k: (_ for _ in ()).throw(main.requests.exceptions.ConnectionError("down")))
    assert main._git_tier_hydrate_retry(now=1000.0) is False
    assert "real_order_events" not in main._git_tier_hydrated
    assert main._git_tier_unhydrated_since["real_order_events"] <= 1000.0
    with main.closing(main.get_db()) as c:  # the morning's orders arrive while the restore is still failing
        c.execute("INSERT INTO real_order_events (ts, symbol, leg, event, order_id) VALUES (5.0,'COLPAL.NS','entry','confirmed','261109000025550')")
        c.commit()
    old = [{"id": 1, "ts": 1.0, "symbol": "A.NS", "leg": "entry", "event": "confirmed", "order_id": "o1"}]
    monkeypatch.setattr(main.requests, "get", lambda url, **k: _R(200, {"rows": old}))
    assert main._git_tier_hydrate_retry(now=1010.0) is False  # throttled
    assert main._git_tier_hydrate_retry(now=1070.0) is True
    with main.closing(main.get_db()) as c:
        got = sorted(r[0] for r in c.execute("SELECT order_id FROM real_order_events").fetchall())
    assert got == ["261109000025550", "o1"]  # history restored AND the local row kept
    assert "real_order_events" not in main._git_tier_unhydrated_since


def test_order_log_pushed_even_if_restore_stays_down(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    with main.closing(main.get_db()) as c:
        c.execute("INSERT INTO real_order_events (ts, symbol, leg, event, order_id) VALUES (5.0,'COLPAL.NS','entry','confirmed','x1')")
        c.commit()
    monkeypatch.setenv("GITHUB_SYNC_TOKEN", "t")
    monkeypatch.setattr(main, "_git_tier_push_last_hash", {})
    put = {}
    remote = base64.b64encode(json.dumps({"rows": [{"ts": 1.0, "symbol": "A.NS", "leg": "sl", "event": "placed", "order_id": "o1"}]}).encode()).decode()
    monkeypatch.setattr(main.requests, "get", lambda url, **k: _R(200, {"sha": "s", "content": remote}))
    monkeypatch.setattr(main.requests, "put", lambda url, **k: put.update(k["json"]) or _R(200, {}))
    main._git_tier_unhydrated_since["real_order_events"] = main.time.time() - 60
    assert main._git_tier_push_side_branch("real_order_events") is False  # still inside the grace window
    main._git_tier_unhydrated_since["real_order_events"] = main.time.time() - main._GIT_TIER_UNHYDRATED_PUSH_AFTER_S - 1
    assert main._git_tier_push_side_branch("real_order_events") is True
    rows = json.loads(base64.b64decode(put["content"]))["rows"]
    assert [r["order_id"] for r in rows] == ["o1", "x1"]  # append-only: git history kept


def test_push_loop_retries_restore(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_GIT_TIER_RETRY_IN_LOOP", True)
    monkeypatch.setattr(main, "_git_tier_hydrate_retry", lambda: calls.append("retry"))
    monkeypatch.setattr(main, "_git_tier_push_side_branch", lambda n: False)
    main._git_tier_push_loop(sleep=lambda s: None, rounds=2)
    assert calls == ["retry", "retry"]


def test_health_reports_restore_state(monkeypatch):
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    assert main._git_tier_push_status()["order_log_git_restored"] is False


def test_unlogged_note_for_order_before_boot():
    boot = main.dt.datetime(2026, 11, 9, 5, 27, 16, tzinfo=main.dt.timezone.utc).timestamp()  # 10:57:16 IST
    note = main._unlogged_before_boot_note("09-Nov-2026 09:16:59", boot_ts=boot)
    assert "before this process booted (09-Nov 10:57 IST)" in note
    assert main._unlogged_before_boot_note("09-Nov-2026 12:19:43", boot_ts=boot) == ""
    assert main._unlogged_before_boot_note("garbage", boot_ts=boot) == ""
