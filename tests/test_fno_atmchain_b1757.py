"""B-1757: the ATM-chain single-leg option PAPER variant. Candidates = every index's ATM +-10 strike legs (CE + PE,
nearest expiry) from the tape's cached chain window; own score (5m + 15m premium momentum); index day direction
confirms the type; |delta| 0.35-0.65; IV not above the ATM leg's; minimum contracts traded; fresh quote (B-1750).
Exits as fast_v3 and never the most-active top-N rank exit. PAPER ONLY (shared fixture blocks any Kotak call)."""
import json

import pytest

import main
import strategy_registry as sr
from tests.test_fno_momo_paper_b1676 import MON, T0, _open, db  # noqa: F401 (db autouse)

ACTIVE = main.FNO_MOMO_VARIANTS  # captured before the shared db fixture narrows it
VA = next(v for v in ACTIVE if v["gate"] == main.FNO_ATMC_GATE)
V3 = ACTIVE[0]
UP = {"NIFTY": 0.4, "BANKNIFTY": 0.5, "INDIAVIX": 1.0}
DOWN = {"NIFTY": -0.4, "BANKNIFTY": -0.5, "INDIAVIX": 3.0}
EXP_NEAR, EXP_FAR = "30-Nov-2026", "07-Dec-2026"


def _leg(u, k, ot, px, spot, exp=EXP_NEAR, n=5000, delta=0.5, iv=12.0):
    r = {"underlying": u, "strikePrice": k, "optionType": ot, "expiryDate": exp, "lastPrice": px, "pChange": 5.0,
         "numberOfContractsTraded": n, "openInterest": 1000, "underlyingValue": spot, "_delta": delta, "_iv": iv}
    r["contract"] = main._fno_label(r)
    return r


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(main, "_FNO_ATMC_HIST", {})
    monkeypatch.setattr(main, "_FNO_ATMC_CACHE", {"ts": 0.0, "chains": {}})
    monkeypatch.setattr(main, "_FNO_PX_HIST", {})
    monkeypatch.setattr(main, "_fno_option_metrics",  # controlled Greeks: the pick logic is what is tested here
                        lambda r, now: {"delta": r.get("_delta", 0.5) * (1 if r["optionType"] == "CE" else -1),
                                        "iv_pct": r.get("_iv", 12.0), "oi_build": None, "theta_per_day": -1.0,
                                        "theta_frac": 0.01, "days_to_expiry": 3.0})


def _chains(rows_by_u):
    return {u: main._fno_atm_window(rows) for u, rows in rows_by_u.items()}


def _mom(r, p15, p5):
    main._FNO_ATMC_HIST[r["contract"]] = [(T0 - 930, p15), (T0 - 330, p5), (T0 - 60, r["lastPrice"])]


def _nifty(spot=25010.0):
    legs = []
    for k in range(24500, 25550, 50):
        legs.append(_leg("NIFTY", k, "CE", 100.0, spot))
        legs.append(_leg("NIFTY", k, "PE", 100.0, spot))
    legs.append(_leg("NIFTY", 25000, "CE", 100.0, spot, exp=EXP_FAR))  # far expiry: never in the window
    return legs


def _get(rows, k, ot, exp=EXP_NEAR):
    return next(r for r in rows if r["strikePrice"] == k and r["optionType"] == ot and r["expiryDate"] == exp)


def test_window_is_atm_pm10_nearest_expiry_ce_and_pe():
    w, atm = main._fno_atm_window(_nifty())
    assert atm == 25000 and len(w) == 42 and {r["expiryDate"] for r in w} == {EXP_NEAR}
    assert {r["optionType"] for r in w} == {"CE", "PE"}


def test_best_leg_by_score_across_indices():
    rows = _nifty()
    a, b = _get(rows, 25000, "CE"), _get(rows, 25050, "CE")
    _mom(a, 90.0, 98.0)   # 5m +2.04%, 15m +11.1%  -> score ~5.75
    _mom(b, 80.0, 95.0)   # 5m +5.26%, 15m +25%    -> score ~13.6 (best NIFTY)
    c = _get(rows, 25100, "CE")
    c["_delta"] = 0.20    # best momentum but out of the delta band
    _mom(c, 50.0, 80.0)
    d = _get(rows, 25150, "CE")
    d["_iv"] = 14.0       # IV above the ATM CE leg's 12%
    _mom(d, 50.0, 80.0)
    thin = _get(rows, 25200, "CE")
    thin["numberOfContractsTraded"] = 10
    _mom(thin, 50.0, 80.0)
    bn = [_leg("BANKNIFTY", k, ot, 200.0, 52020.0) for k in range(51500, 52600, 100) for ot in ("CE", "PE")]
    e = _get(bn, 52000, "CE")
    _mom(e, 185.0, 196.0)  # 5m +2.04%, 15m +8.1%
    cand, m, checked = main._fno_momo_pick_atmc(_chains({"NIFTY": rows, "BANKNIFTY": bn}), UP, MON, T0)
    assert cand["contract"] == b["contract"] and cand["underlying"] == "NIFTY" and cand["option_type"] == "CE"
    assert cand["rank"] == 1 and cand["atm_strike"] == 25000 and m["score"] > 13
    why = {x["contract"]: x["skip"] for x in checked}
    assert why[c["contract"]] == "skipped_delta_out_of_band"
    assert why[d["contract"]] == "skipped_iv_above_atm"
    assert why[thin["contract"]] == "skipped_low_contracts_traded"
    assert why[e["contract"]] is None
    assert why[_get(rows, 25000, "PE")["contract"]] == "skipped_sentiment_disagrees"  # up day: no PE
    assert why[_get(rows, 24600, "CE")["contract"]] == "skipped_momentum_warming_up"


def test_pe_on_a_down_day():
    rows = _nifty()
    pe, ce = _get(rows, 24950, "PE"), _get(rows, 25000, "CE")
    _mom(pe, 85.0, 96.0)
    _mom(ce, 85.0, 96.0)
    cand, _m, checked = main._fno_momo_pick_atmc(_chains({"NIFTY": rows}), DOWN, MON, T0)
    assert cand["contract"] == pe["contract"] and cand["option_type"] == "PE"
    assert {x["contract"]: x["skip"] for x in checked}[ce["contract"]] == "skipped_sentiment_disagrees"


def test_stale_and_falling_legs_skipped():
    rows = _nifty()
    st, fall = _get(rows, 25000, "CE"), _get(rows, 25050, "CE")
    main._FNO_ATMC_HIST[st["contract"]] = [(T0 - a, 100.0) for a in range(960, 0, -60)]  # frozen 16 min
    _mom(fall, 110.0, 105.0)
    cand, _m, checked = main._fno_momo_pick_atmc(_chains({"NIFTY": rows}), UP, MON, T0)
    why = {x["contract"]: x["skip"] for x in checked}
    assert cand is None and why[st["contract"]] == "skipped_stale_quote"
    assert why[fall["contract"]] == "skipped_momentum_not_rising"


def test_step_enters_from_the_cached_tape_window_without_a_fetch(db, monkeypatch):
    monkeypatch.setattr(main, "_fno_chain_fetch", lambda *a, **k: pytest.fail("no new chain fetch per tick"))
    rows = _nifty()
    b = _get(rows, 25050, "CE")
    _mom(b, 80.0, 95.0)
    main._fno_atmc_note(_chains({"NIFTY": rows}), T0)  # what _fno_tape_record does once a minute
    assert main._FNO_ATMC_CACHE["ts"] == T0 and len(main._FNO_ATMC_HIST[b["contract"]]) == 4
    snap = {"ok": True, "groups": {}, "index_pct": UP, "index_detail": {}}
    acts = main._fno_momo_step(db, now=MON, snapshot=snap, now_ts=T0 + 30, variant=VA)
    assert [a["action"] for a in acts] == ["entry"] and acts[0]["contract"] == b["contract"]
    t = _open(db)
    assert t["tag"] == main.FNO_MOMO_ATMC_TAG and t["stop_price"] == round(100.0 * 0.98, 4)
    assert "ATM+1" in t["open_reason"] and json.loads(t["entry_meta"])["gate"] == main.FNO_ATMC_GATE
    logged = db.execute("SELECT entered, tag FROM fno_momo_scan_log").fetchall()
    assert [tuple(x) for x in logged] == [(1, main.FNO_MOMO_ATMC_TAG)]


def test_old_chain_cache_is_not_traded(db):
    rows = _nifty()
    _mom(_get(rows, 25050, "CE"), 80.0, 95.0)
    main._FNO_ATMC_CACHE.update(ts=T0 - 600, chains=_chains({"NIFTY": rows}))
    snap = {"ok": True, "groups": {}, "index_pct": UP, "index_detail": {}}
    assert main._fno_momo_step(db, now=MON, snapshot=snap, now_ts=T0, variant=VA) == []
    assert main._FNO_MOMO_STATES[VA["tag"]]["last_scan"]["skip"] == "skipped_atm_chain_unavailable"


def _hold(db, tag, opened, path):
    db.execute("INSERT INTO fno_momo_paper_trades (tag, day, status, contract, underlying, option_type, opened_ts, "
               "entry_price, peak_price, stop_price, last_price, last_ts, price_path) VALUES (?, '2026-11-23', "
               "'open', ?, 'NIFTY', 'CE', ?, 100, 101, 98.98, 101, ?, ?)",
               (tag, _leg("NIFTY", 25050, "CE", 100.0, 25010.0)["contract"], opened, path[-1][0], json.dumps(path)))
    db.commit()


def test_no_top3_exit_for_the_atmchain_variant(db):
    path = [[T0 - 120, 100.0], [T0 - 60, 101.0]]
    snap = {"ok": True, "groups": {"NIFTY": []}, "index_pct": UP, "index_detail": {}}  # not most-active at all
    _hold(db, VA["tag"], T0 - 120, path)
    assert main._fno_momo_step(db, now=MON, snapshot=snap, now_ts=T0, variant=VA, quote=lambda c, u: 101.5) == []
    assert _open(db) is not None
    db.execute("DELETE FROM fno_momo_paper_trades")
    _hold(db, V3["tag"], T0 - 120, path)  # control: the most-active plan does exit on rank loss
    acts = main._fno_momo_step(db, now=MON, snapshot=snap, now_ts=T0, variant=V3, quote=lambda c, u: 101.5)
    assert [a["reason"] for a in acts] == ["confidence_lost_top3"]


@pytest.mark.parametrize("now_off,px,pct,want", [
    (900, 101.5, UP, "time_exit_15min"),          # 15-min max hold
    (120, 98.5, UP, "trailing_sl"),               # 2% under the 101 peak = 98.98
    (120, 101.5, DOWN, "confidence_lost_sentiment"),
])
def test_atmchain_exits_as_fast_v3(db, now_off, px, pct, want):
    _hold(db, VA["tag"], T0, [[T0, 100.0], [T0 + 60, 101.0]])
    snap = {"ok": True, "groups": {}, "index_pct": pct, "index_detail": {}}
    acts = main._fno_momo_step(db, now=MON, snapshot=snap, now_ts=T0 + now_off, variant=VA, quote=lambda c, u: px)
    assert [a["reason"] for a in acts] == [want]


def test_registered_paper_only_options_category():
    assert VA["tag"] == "fno_atmchain_momo__atm10_mom5m15m_idxconfirm_delta_ivrel__long_opt__5m__trail2_hold15__v1"
    assert VA["trail"] == 0.02 and not VA.get("retired") and ACTIVE[-1] is VA
    d = next(x for x in sr.REGISTRY if x.name == VA["tag"])
    assert d.metrics is None and d.categories == (sr.TradeCategory.OPTIONS,) and not d.is_wired()
    assert sr.CATEGORY_LABELS.get(main.FNO_MOMO_CATEGORY) == "Single leg option"
    assert main._is_strategy_viable_for_real_money(VA["tag"], check_switch=False) is False
    assert [v["tag"] for v in ACTIVE[:6]] == [main.FNO_MOMO_V3B_TAG, main.FNO_MOMO_V3B_T5_TAG,
                                             main.FNO_MOMO_V4X_T12_TAG, main.FNO_MOMO_V4X_T5_TAG,
                                             main.FNO_MOMO_V4XNB_TAG, main.FNO_MOMO_V4XNBW_TAG]  # unchanged
