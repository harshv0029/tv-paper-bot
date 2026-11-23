"""B-1676 PAPER most-active index option momentum: pick, sentiment gate, trailing / confidence / 15:15 exits, cost math,
no Kotak or real-order path, Upstash mirror + restore on wipe, tick hook never raises. No network."""
import datetime as dt
import os
import tempfile
from contextlib import closing

import pytest

import kotak_real_fo_orders
import kotak_real_orders
import main
import strategy_registry as sr

REAL_SYNC = main.sync_generic_tables_external
REAL_SNAP = main._fno_by_index_snapshot
SYNCED = []
MON = dt.datetime(2026, 11, 23, 10, 0)
T0 = 1_800_000_000.0


def _r(u, k, ot, n, pc, px):
    r = {"underlying": u, "strikePrice": k, "optionType": "Call" if ot == "CE" else "Put", "expiryDate": "27-Nov-2026",
         "lastPrice": px, "pChange": pc, "numberOfContractsTraded": n}
    r["contract"] = main._fno_label(r)
    return r


def _snap(rows, pct):
    return {"ok": True, "groups": main._fno_group_by_index(rows, 50), "index_pct": pct}


BASE = [_r("NIFTY", 25500, "CE", 900, 12.0, 100.0), _r("NIFTY", 25400, "PE", 800, -5.0, 50.0),
        _r("NIFTY", 25600, "CE", 700, 3.0, 40.0), _r("NIFTY", 25700, "CE", 100, 80.0, 5.0),  # rank 4: ignored
        _r("BANKNIFTY", 52000, "PE", 500, 30.0, 200.0), _r("BANKNIFTY", 52500, "CE", 400, 8.0, 150.0)]
CE_NAME = "NIFTY 25500 CE 27-Nov-2026"


@pytest.fixture(autouse=True)
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    SYNCED.clear()
    monkeypatch.setattr(main, "sync_generic_tables_external", lambda only=None: SYNCED.append(only) or 0)
    monkeypatch.setitem(main._FNO_MOMO_STATE, "last_scan_ts", 0.0)
    monkeypatch.setitem(main._FNO_MOMO_STATE, "last_scan", None)
    for st in main._FNO_MOMO_STATES.values():
        monkeypatch.setitem(st, "last_scan_ts", 0.0)
        monkeypatch.setitem(st, "last_scan", None)
    # PAPER ONLY: any Kotak/real-order call fails the test
    for mod in (kotak_real_orders, kotak_real_fo_orders):
        for name in dir(mod):
            if name.startswith(("place_", "cancel_", "modify_")) and callable(getattr(mod, name)):
                monkeypatch.setattr(mod, name, lambda *a, **k: pytest.fail("real order path called"))
    monkeypatch.setattr(main, "_fno_most_active_fetch", lambda *a, **k: pytest.fail("network called"))
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: pytest.fail("network called"))
    monkeypatch.setattr(main, "_fno_by_index_snapshot", lambda: {"ok": False, "groups": {}})
    monkeypatch.setattr(main, "_FNO_CHAIN_CACHE", {})
    monkeypatch.setattr(main, "_FNO_PX_HIST", {})
    with closing(main.get_db()) as c:
        yield c


def _open(db):
    return db.execute("SELECT * FROM fno_momo_paper_trades WHERE status = 'open'").fetchone()


def test_tag_and_trail_constant_registered_paper_only():
    assert main.FNO_MOMO_TAG == "fno_mostactive_momo__top3_max_gain__long_opt__5m__trail2__v1"
    assert main.FNO_MOMO_TRAIL_PCT == 0.02
    d = [x for x in sr.REGISTRY if x.name == main.FNO_MOMO_TAG]
    assert len(d) == 1 and d[0].status == sr.StrategyStatus.RESEARCH and d[0].metrics is None
    assert d[0].categories == (sr.TradeCategory.OPTIONS,) and not d[0].is_wired()


def test_pick_largest_positive_change_among_top3_per_index():
    g = main._fno_group_by_index(BASE, 50)
    p = main._fno_momo_pick(g)
    assert p["contract"] == "BANKNIFTY 52000 PE 27-Nov-2026" and p["option_type"] == "PE" and p["rank"] == 1
    g["BANKNIFTY"] = []
    assert main._fno_momo_pick(g)["contract"] == CE_NAME  # NIFTY rank-4 +80% is outside the top 3
    assert main._fno_momo_pick({"NIFTY": [_r("NIFTY", 1, "CE", 1, -1.0, 5.0)]}) is None


@pytest.mark.parametrize("ot,idx,nifty,want", [
    ("CE", 0.5, 0.2, True), ("CE", 0.5, -0.1, False), ("CE", -0.5, 0.3, False),
    ("PE", -0.5, -0.2, True), ("PE", -0.5, 0.1, False), ("PE", 0.4, -0.2, False),
    ("CE", None, 0.2, None), ("PE", -0.1, None, None)])
def test_sentiment_gate(ot, idx, nifty, want):
    assert main._fno_momo_sentiment(ot, idx, nifty) is want


def test_entry_needs_agreeing_sentiment(db):
    rows = [r for r in BASE if r["underlying"] == "NIFTY"]
    assert main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": -0.3}), now_ts=T0) == []
    assert _open(db) is None and main._FNO_MOMO_STATE["last_scan"]["skip"] == "skipped_sentiment_disagrees"
    acts = main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0 + 300)
    o = _open(db)
    assert acts[0]["action"] == "entry" and o["contract"] == CE_NAME and o["entry_price"] == 100.0
    assert o["stop_price"] == 98.0 and o["tag"] == main.FNO_MOMO_TAG and SYNCED[-1] == ("fno_momo_paper_trades",)
    # one position at a time: no second entry while open
    main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0 + 600)
    assert db.execute("SELECT COUNT(*) FROM fno_momo_paper_trades").fetchone()[0] == 1


def test_scan_throttled_to_5_min_and_window(db):
    rows = [r for r in BASE if r["underlying"] == "NIFTY"]
    main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": -0.3}), now_ts=T0)
    main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0 + 60)
    assert _open(db) is None  # next scan only after 5 min
    late = MON.replace(hour=14, minute=31)
    main._fno_momo_step(db, now=late, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0 + 900)
    assert _open(db) is None
    hol = dt.datetime(2026, 11, 24, 10, 0)
    assert main._fno_momo_step(db, now=hol, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0 + 1200) == []


def _enter(db):
    rows = [r for r in BASE if r["underlying"] == "NIFTY"]
    main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0)
    assert _open(db) is not None
    return rows


def _with_price(rows, px):
    return [dict(r, lastPrice=px) if r["contract"] == CE_NAME else r for r in rows]


def test_trailing_sl_2pct_from_peak(db):
    rows = _enter(db)
    main._fno_momo_step(db, now=MON, snapshot=_snap(_with_price(rows, 120.0), {"NIFTY": 0.3}), now_ts=T0 + 30)
    o = _open(db)
    assert o["peak_price"] == 120.0 and o["stop_price"] == pytest.approx(117.6)
    main._fno_momo_step(db, now=MON, snapshot=_snap(_with_price(rows, 118.0), {"NIFTY": 0.3}), now_ts=T0 + 60)
    assert _open(db) is not None  # exits checked every call (every tick), not only every 5 min
    acts = main._fno_momo_step(db, now=MON, snapshot=_snap(_with_price(rows, 117.5), {"NIFTY": 0.3}), now_ts=T0 + 90)
    assert acts[0]["reason"] == "trailing_sl" and _open(db) is None
    t = db.execute("SELECT * FROM fno_momo_paper_trades").fetchone()
    # B-1679 (a): fill at the resting stop (117.6), the observed 117.5 recorded beside it
    assert t["close_price"] == pytest.approx(117.6) and t["net_pct"] == pytest.approx(17.6 - main.ROUND_TRIP_COST_PCT)
    assert t["observed_exit_price"] == 117.5 and t["stop_at_exit"] == pytest.approx(117.6)
    assert t["observed_net_pct"] == pytest.approx(17.5 - main.ROUND_TRIP_COST_PCT)


def test_confidence_loss_out_of_top3(db):
    rows = _enter(db)
    rows = [dict(r, numberOfContractsTraded=1) if r["contract"] == CE_NAME else r for r in rows]
    acts = main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0 + 30)
    assert acts[0]["reason"] == "confidence_lost_top3"


def test_confidence_loss_sentiment_flip(db):
    rows = _enter(db)
    acts = main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {"NIFTY": -0.05}), now_ts=T0 + 30)
    assert acts[0]["reason"] == "confidence_lost_sentiment"


def test_unknown_sentiment_does_not_exit(db):
    rows = _enter(db)
    assert main._fno_momo_step(db, now=MON, snapshot=_snap(rows, {}), now_ts=T0 + 30) == []
    assert _open(db) is not None


def test_forced_exit_1515(db):
    rows = _enter(db)
    acts = main._fno_momo_step(db, now=MON.replace(hour=15, minute=15), snapshot=_snap(rows, {"NIFTY": 0.3}),
                               now_ts=T0 + 30)
    assert acts[0]["reason"] == "forced_exit_1515"
    assert main._fno_momo_due(MON.replace(hour=15, minute=16)) and not main._fno_momo_due(MON.replace(hour=15, minute=25))


def test_stale_open_from_previous_day_is_closed(db):
    _enter(db)
    nxt = dt.datetime(2026, 11, 25, 9, 20)
    acts = main._fno_momo_step(db, now=nxt, snapshot={"ok": False}, now_ts=T0 + 90000)
    assert acts[0]["reason"] == "stale_prev_day_close" and _open(db) is None


def test_cost_math():
    assert main.ROUND_TRIP_COST_PCT == 0.8
    assert main._fno_momo_net_pct(100.0, 100.0) == -0.8
    assert main._fno_momo_net_pct(50.0, 55.0) == pytest.approx(9.2)


def test_route_reports_open_trades_and_totals(db, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "ist_now", lambda: MON)
    rows = _enter(db)
    main._fno_momo_step(db, now=MON, snapshot=_snap(_with_price(rows, 90.0), {"NIFTY": 0.3}), now_ts=T0 + 30)
    j = TestClient(main.app).get("/fno-momo-paper").json()
    assert j["mode"] == "paper" and j["open"] is None and j["trail_pct"] == 2.0
    assert j["category"] == "options" and j["category_label"] == "Single leg option"
    # B-1679: the stop sits 2% under the entry from the start, so a jump to 90 fills at 98 (-2.8% net); seen -10.8%
    assert j["today"]["n"] == 1 and j["today"]["net_pct_sum"] == pytest.approx(-2.8)
    assert j["trades"][0]["observed_net_pct"] == pytest.approx(-10.8)
    assert j["trades"][0]["opened_ist"].endswith("IST") and j["trades"][0]["close_reason"] == "trailing_sl"


def test_tick_hook_swallows_errors(monkeypatch):
    monkeypatch.setattr(main, "_fno_momo_step", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    main._fno_momo_tick_hook()  # must not raise
    monkeypatch.setattr(main, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    main._fno_momo_tick_hook()


def test_tick_wires_the_hook():
    import inspect
    src = inspect.getsource(main._scheduler_tick)
    assert "_fno_momo_tick_hook" in src and "_fno_momo_due()" in src


def test_mirrored_and_restored_after_wipe(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(main, "sync_generic_tables_external", REAL_SYNC)
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
    assert "fno_momo_paper_trades" in main._GENERIC_MIRROR_TABLES
    assert "fno_momo_paper_trades" in main._GENERIC_MIRROR_UPSTASH_TABLES
    for _ in range(2):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        monkeypatch.setattr(main, "DB_PATH", path)
        main.init_db()
        main._generic_mirror_hydrated.clear()
        main.hydrate_generic_tables_from_external(only=("fno_momo_paper_trades",))
        with closing(main.get_db()) as c:
            if not c.execute("SELECT 1 FROM fno_momo_paper_trades").fetchone():
                main._FNO_MOMO_STATE["last_scan_ts"] = 0.0
                rows = [r for r in BASE if r["underlying"] == "NIFTY"]
                main._fno_momo_step(c, now=MON, snapshot=_snap(rows, {"NIFTY": 0.3}), now_ts=T0)  # entry -> push
            else:
                r = c.execute("SELECT contract, status, tag FROM fno_momo_paper_trades").fetchone()
                assert tuple(r) == (CE_NAME, "open", main.FNO_MOMO_TAG)
                return
    pytest.fail("open paper position was not restored after the wipe")


# ---- B-1677 strict sentiment variant ----
STRICT = main.FNO_MOMO_VARIANTS[1]
DET_UP = {"NIFTY": {"last": 25700, "open": 25600, "advances": 35, "declines": 15}}


def _ssnap(rows, pct, detail):
    return dict(_snap(rows, pct), index_detail=detail)


@pytest.mark.parametrize("ot,pct,det,want", [
    ("CE", {"NIFTY": 0.4, "INDIAVIX": 1.0}, DET_UP, True),
    ("CE", {"NIFTY": 0.1, "INDIAVIX": 1.0}, DET_UP, False),        # too small a move
    ("CE", {"NIFTY": 0.4, "INDIAVIX": 6.0}, DET_UP, False),        # VIX spiking
    ("CE", {"NIFTY": 0.4, "INDIAVIX": 1.0}, {"NIFTY": dict(DET_UP["NIFTY"], advances=25, declines=25)}, False),
    ("CE", {"NIFTY": 0.4, "INDIAVIX": 1.0}, {"NIFTY": dict(DET_UP["NIFTY"], last=25500)}, False),  # below open
    ("PE", {"NIFTY": -0.4, "INDIAVIX": 7.0},
     {"NIFTY": {"last": 25500, "open": 25600, "advances": 10, "declines": 40}}, True),
    ("CE", {"NIFTY": 0.4}, DET_UP, None),                          # VIX missing -> unknown
    ("CE", {"NIFTY": 0.4, "INDIAVIX": 1.0}, {}, None),             # detail missing -> unknown
])
def test_strict_gate(ot, pct, det, want):
    assert main._fno_momo_sentiment_strict(ot, "NIFTY", pct, det) is want


def test_strict_variant_has_own_position_and_tag(db):
    rows = [r for r in BASE if r["underlying"] == "NIFTY"]  # pick = NIFTY 25500 CE
    weak = {"NIFTY": 0.1, "INDIAVIX": 1.0}
    main._fno_momo_step(db, now=MON, snapshot=_ssnap(rows, weak, DET_UP), now_ts=T0)                  # v1 enters
    main._fno_momo_step(db, now=MON, snapshot=_ssnap(rows, weak, DET_UP), now_ts=T0, variant=STRICT)  # strict skips
    tags = [r["tag"] for r in db.execute("SELECT tag FROM fno_momo_paper_trades WHERE status = 'open'")]
    assert tags == [main.FNO_MOMO_TAG]
    assert main._FNO_MOMO_STATES[main.FNO_MOMO_STRICT_TAG]["last_scan"]["skip"] == "skipped_sentiment_disagrees"
    strong = {"NIFTY": 0.4, "INDIAVIX": 1.0}
    main._fno_momo_step(db, now=MON, snapshot=_ssnap(rows, strong, DET_UP), now_ts=T0 + 300, variant=STRICT)
    tags = sorted(r["tag"] for r in db.execute("SELECT tag FROM fno_momo_paper_trades WHERE status = 'open'"))
    assert tags == sorted([main.FNO_MOMO_TAG, main.FNO_MOMO_STRICT_TAG])
    out = main.fno_momo_paper(tag=main.FNO_MOMO_STRICT_TAG)
    assert out["gate"] == "strict" and out["open"]["tag"] == main.FNO_MOMO_STRICT_TAG
    assert set(out["variants"]) == {main.FNO_MOMO_TAG, main.FNO_MOMO_STRICT_TAG}


def test_strict_registered_single_leg_option_never_wired():
    s = next(x for x in sr.REGISTRY if x.name == main.FNO_MOMO_STRICT_TAG)
    assert s.categories == (sr.TradeCategory.OPTIONS,) and s.metrics is None
    assert main._is_strategy_viable_for_real_money(main.FNO_MOMO_STRICT_TAG, check_switch=False) is False


def test_tick_hook_runs_every_variant(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "_fno_momo_step", lambda conn, variant=None, **k: seen.append(variant["gate"]))
    main._fno_momo_tick_hook()
    assert seen == ["basic", "strict"]


# ---- B-1678 / B-1679 (d) / B-1680 (user 2026-11-23) ------------------------------------------------------------------
def test_stop_is_2pct_below_entry_from_the_first_tick(db):
    _enter(db)
    o = _open(db)
    assert o["stop_price"] == pytest.approx(o["entry_price"] * 0.98)


def test_held_contract_uses_its_own_fresh_quote(db):
    rows = _enter(db)
    gone = [r for r in rows if r["contract"] != CE_NAME]  # dropped out of the most-active list
    rows_top = gone + [dict(r, numberOfContractsTraded=1) for r in rows if r["contract"] == CE_NAME]
    seen = []
    q = lambda c, u: seen.append((c, u)) or 97.0  # noqa: E731
    acts = main._fno_momo_step(db, now=MON, snapshot=_snap(rows_top, {"NIFTY": 0.3}), now_ts=T0 + 30, quote=q)
    assert seen == [(CE_NAME, "NIFTY")] and acts[0]["reason"] == "trailing_sl"
    t = db.execute("SELECT * FROM fno_momo_paper_trades").fetchone()
    assert t["close_price"] == pytest.approx(98.0) and t["observed_exit_price"] == 97.0


def test_quote_failure_falls_back_to_the_snapshot(db):
    rows = _enter(db)
    bad = lambda c, u: (_ for _ in ()).throw(RuntimeError("nse down"))  # noqa: E731
    main._fno_momo_step(db, now=MON, snapshot=_snap(_with_price(rows, 110.0), {"NIFTY": 0.3}), now_ts=T0 + 30, quote=bad)
    assert _open(db)["last_price"] == 110.0


def test_expiry_day_contract_never_picked():
    rows = [_r("NIFTY", 25500, "CE", 900, 12.0, 100.0)]
    exp = dict(rows[0], expiryDate="23-Nov-2026")
    exp["contract"] = main._fno_label(exp)
    g = main._fno_group_by_index([exp, _r("NIFTY", 25600, "CE", 800, 3.0, 40.0)], 50)
    assert main._fno_momo_pick(g, "2026-11-23")["contract"] == "NIFTY 25600 CE 27-Nov-2026"
    assert main._fno_momo_pick(g)["contract"] == exp["contract"]
    assert main._fno_momo_is_expiry_day("NIFTY 25500 CE 23-Nov-2026", "2026-11-23")
    assert not main._fno_momo_is_expiry_day("garbage", "2026-11-23")


def test_route_shows_running_pnl_on_the_open_row(db, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "ist_now", lambda: MON)
    rows = _enter(db)
    main._fno_momo_step(db, now=MON, snapshot=_snap(_with_price(rows, 110.0), {"NIFTY": 0.3}), now_ts=T0 + 30)
    j = TestClient(main.app).get("/fno-momo-paper").json()
    assert j["open"]["running_net_pct"] == pytest.approx(9.2) and j["open"]["last_ist"].endswith("IST")


V3 = {"records": {"underlyingValue": 23000, "data": [
    {"strikePrice": 23000, "expiryDates": "30-Dec-2026",
     "CE": {"strikePrice": 23000, "expiryDate": "30-Dec-2026", "lastPrice": 120.5, "pChange": 4.2,
            "totalTradedVolume": 5000, "openInterest": 100},
     "PE": {"strikePrice": 23000, "expiryDate": "30-Dec-2026", "lastPrice": 90.0, "change": -10.0,
            "totalTradedVolume": 7000, "openInterest": 80}},
    {"strikePrice": 23100, "CE": {"strikePrice": 23100, "expiryDate": "30-Dec-2026", "lastPrice": 0,
                                  "totalTradedVolume": 0}}]}}


def test_chain_rows_parse_v3_payload():
    rows = main._fno_chain_rows(V3, "FINNIFTY", "30-Dec-2026")
    assert [r["contract"] for r in rows] == ["FINNIFTY 23000 CE 30-Dec-2026", "FINNIFTY 23000 PE 30-Dec-2026"]
    assert rows[1]["pChange"] == pytest.approx(-10.0) and rows[1]["numberOfContractsTraded"] == 7000
    assert main._fno_chain_rows({}, "FINNIFTY") == [] and main._fno_chain_rows(None, "X") == []


def test_snapshot_fills_crowded_out_indices_from_their_chain(monkeypatch):
    monkeypatch.setattr(main, "_FNO_BY_INDEX_CACHE", {"ts": 0.0, "data": None})
    nifty = [_r("NIFTY", 25500 + 100 * i, "CE", 900 - i, 1.0, 50.0) for i in range(6)]
    monkeypatch.setattr(main, "_fno_most_active_fetch", lambda *a, **k: {"lists": {"index_calls": nifty}, "errors": {}})
    monkeypatch.setattr(main, "_fno_index_day_changes", lambda: {"NIFTY": 0.3})
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: ("op", {}))
    asked = []
    monkeypatch.setattr(main, "_fno_chain_fetch", lambda u, e=None, o=None: asked.append(u) or (
        main._fno_chain_rows(V3, u, "30-Dec-2026") if u == "FINNIFTY" else []))
    snap = REAL_SNAP()
    assert asked == ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]  # NIFTY already has 5+ rows
    assert snap["sources"]["FINNIFTY"] == "option_chain" and snap["sources"]["NIFTY"] == "most_active"
    assert snap["groups"]["FINNIFTY"][0]["contract"] == "FINNIFTY 23000 PE 30-Dec-2026"  # 7000 > 5000 traded
    assert len(snap["groups"]["NIFTY"]) == 6 and main._FNO_PX_HIST  # 15-min samples recorded


def test_chg15_needs_a_sample_at_least_15_min_old():
    main._fno_hist_record({"NIFTY": [{"contract": "A", "lastPrice": 100.0}]}, T0)
    assert main._fno_chg15("A", 110.0, T0 + 600) is None  # warming up
    main._fno_hist_record({"NIFTY": [{"contract": "A", "lastPrice": 105.0}]}, T0 + 600)
    assert main._fno_chg15("A", 110.0, T0 + 900) == pytest.approx(10.0)
    assert main._fno_chg15("A", 110.0, T0 + 1500) == pytest.approx(4.76)  # 100 sample aged out, 105 now 15 min old
    main._fno_hist_record({}, T0 + 3000)
    assert "A" not in main._FNO_PX_HIST  # pruned after 20 min


def test_view6_route_positive_only_with_chg15(monkeypatch):
    from fastapi.testclient import TestClient
    g = main._fno_group_by_index(BASE, 50)
    monkeypatch.setattr(main, "_fno_by_index_snapshot", lambda: {"ok": True, "groups": g, "index_pct": {"NIFTY": 0.3},
                                                                 "sources": {"FINNIFTY": "option_chain"}})
    j = TestClient(main.app).get("/fno-most-active-by-index?per_index=5").json()
    nifty = j["indices"]["NIFTY"]["rows"]
    assert j["positive_only"] and all(r["pChange"] > 0 for r in nifty) and len(nifty) == 3
    assert "chg15_pct" in nifty[0] and j["indices"]["FINNIFTY"]["source"] == "option_chain"
    j2 = TestClient(main.app).get("/fno-most-active-by-index?per_index=5&positive_only=0").json()
    assert len(j2["indices"]["NIFTY"]["rows"]) == 4


def test_tick_hook_passes_the_fresh_quote(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "_fno_momo_step", lambda conn, variant=None, quote=None, **k: seen.append(quote))
    main._fno_momo_tick_hook()
    assert seen == [main._fno_contract_ltp, main._fno_contract_ltp]


def test_contract_ltp_reads_its_own_expiry_chain(monkeypatch):
    monkeypatch.setattr(main, "_fno_chain_fetch", lambda u, e=None, o=None: main._fno_chain_rows(V3, u, e))
    assert main._fno_contract_ltp("FINNIFTY 23000 CE 30-Dec-2026", "FINNIFTY") == 120.5
    assert main._fno_contract_ltp("FINNIFTY 99999 CE 30-Dec-2026", "FINNIFTY") is None
    assert main._fno_contract_ltp("bad", "FINNIFTY") is None


def test_new_columns_mirror_and_restore(db):
    cols = {r[1] for r in db.execute("PRAGMA table_info(fno_momo_paper_trades)")}
    assert {"stop_at_exit", "observed_exit_price", "observed_net_pct"} <= cols
    main.init_db()  # migration is idempotent


def test_chain_failure_is_cached_and_reported(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: ("op", {}))
    monkeypatch.setattr(main, "_nse_get_json", lambda *a, **k: calls.append(a[2]) or (_ for _ in ()).throw(
        TimeoutError("timed out")))
    assert main._fno_chain_fetch("FINNIFTY") == []
    assert main._fno_chain_fetch("FINNIFTY") == [] and len(calls) == 1  # cached failure: no refetch inside 120 s
    assert "TimeoutError" in main._FNO_CHAIN_CACHE[("FINNIFTY", "")]["error"]
    monkeypatch.setattr(main, "_FNO_BY_INDEX_CACHE", {"ts": 0.0, "data": None})
    nifty = [_r("NIFTY", 25500 + 100 * i, "CE", 900 - i, 1.0, 50.0) for i in range(6)]
    monkeypatch.setattr(main, "_fno_most_active_fetch", lambda *a, **k: {"lists": {"index_calls": nifty}, "errors": {}})
    monkeypatch.setattr(main, "_fno_index_day_changes", lambda: {})
    snap = REAL_SNAP()
    assert "TimeoutError" in snap["errors"]["chain_FINNIFTY"] and "chain_BANKNIFTY" in snap["errors"]


def test_chain_v3_path_used_with_nearest_expiry(monkeypatch):
    paths = []
    monkeypatch.setattr(main, "_nse_opener", lambda *a, **k: ("op", {}))

    def fake(op, hdrs, path, *a, **k):
        paths.append(path)
        return {"expiryDates": ["30-Dec-2026", "27-Jan-2027"]} if "contract-info" in path else V3
    monkeypatch.setattr(main, "_nse_get_json", fake)
    rows = main._fno_chain_fetch("FINNIFTY")
    assert len(rows) == 2 and "option-chain-v3?type=Indices&symbol=FINNIFTY&expiry=30-Dec-2026" in paths[1]
    assert main._FNO_CHAIN_CACHE[("FINNIFTY", "")]["error"] is None
