"""B-1714: the researched View 6 paper entry plan (5m/15m/1h momentum + OI build-up + Greeks + relative IV).
PAPER ONLY: the shared fixture fails the test on any Kotak/real-order call."""
import time

import main
from tests.test_fno_momo_paper_b1676 import DET_UP, MON, T0, _open, _orow, _ssnap, db  # noqa: F401 (db autouse)

V2 = main.FNO_MOMO_VARIANTS[0]
STRONG = {"NIFTY": 0.4, "INDIAVIX": 1.0}
EXP = "30-Nov-2026"  # ~7 days out on MON: ATM theta well under the cap


def _hist(contract, p15, p5):
    main._FNO_PX_HIST[contract] = [(T0 - 930, p15), (T0 - 330, p5)]


def _run(db, rows, pct=STRONG):
    main._fno_momo_step(db, now=MON, snapshot=_ssnap(rows, pct, DET_UP), now_ts=T0, variant=V2)
    return main._FNO_MOMO_STATES[V2["tag"]]["last_scan"]


def test_v2_is_the_only_active_variant_and_v1_retired():
    assert V2["gate"] == "mtf_v2" and V2["tag"] == main.FNO_MOMO_V2_TAG
    assert main.FNO_MOMO_STRICT_OIG_VARIANT in main.FNO_MOMO_RETIRED_VARIANTS


def test_enters_when_every_check_passes(db, monkeypatch):
    monkeypatch.setattr(main, "_FNO_PX_HIST_1H", {})
    r = _orow(exp=EXP)
    _hist(r["contract"], 140.0, 146.0)
    scan = _run(db, [r])
    assert scan["entered"] is True, scan.get("skip")
    t = _open(db)
    assert t["tag"] == V2["tag"] and "15m" in t["open_reason"] and "delta" in t["open_reason"]
    assert scan["checked"] == [{"contract": r["contract"], "skip": None}]


def test_skips_named(db):
    r = _orow(exp=EXP)
    assert _run(db, [r])["skip"] == "skipped_momentum_warming_up"
    main._FNO_MOMO_STATES[V2["tag"]]["last_scan_ts"] = 0.0
    _hist(r["contract"], 140.0, 155.0)  # 5-min falling
    assert _run(db, [r])["skip"] == "skipped_momentum_not_rising"
    main._FNO_MOMO_STATES[V2["tag"]]["last_scan_ts"] = 0.0
    _hist(r["contract"], 100.0, 120.0)  # +25% in 5 min: chasing
    assert _run(db, [r])["skip"] == "skipped_chasing_spike"
    main._FNO_MOMO_STATES[V2["tag"]]["last_scan_ts"] = 0.0
    r2 = _orow(exp=EXP, oi_chg=-500)
    _hist(r2["contract"], 140.0, 146.0)
    assert _run(db, [r2])["skip"] == "skipped_oi_short_covering"
    main._FNO_MOMO_STATES[V2["tag"]]["last_scan_ts"] = 0.0
    assert _run(db, [r2], {"NIFTY": 0.1, "INDIAVIX": 1.0})["skip"] == "skipped_sentiment_disagrees"
    assert _open(db) is None


def test_a_failing_top_candidate_no_longer_blocks_the_rest(db):
    lotto = _orow(exp=EXP, k=26000, px=3.0, pc=400.0)  # largest day % but deep OTM
    good_a = _orow(exp=EXP, k=25000, px=150.0, pc=10.0)
    good_b = _orow(exp=EXP, k=25100, px=110.0, pc=8.0)
    _hist(lotto["contract"], 2.0, 2.9)
    _hist(good_a["contract"], 145.0, 148.0)  # 15m +3.4%
    _hist(good_b["contract"], 100.0, 108.0)  # 15m +10%: wins the rank
    scan = _run(db, [lotto, good_a, good_b])
    assert scan["entered"] is True and _open(db)["contract"] == good_b["contract"]
    assert {c["contract"]: c["skip"] for c in scan["checked"]}[lotto["contract"]] == "skipped_delta_out_of_band"


def test_skip_unit_checks_near_expiry_and_iv_rich():
    m = {"chg5_pct": 2.0, "chg15_pct": 4.0, "chg60_pct": None, "oi_build": "long_buildup", "delta": 0.5,
         "theta_frac": 0.05, "days_to_expiry": 1.5, "iv_pct": 20.0}
    r = _orow(exp=EXP)
    assert main._fno_momo_v2_skip(r, "CE", "NIFTY", m, None, STRONG, DET_UP, "") == "skipped_near_expiry"
    m["days_to_expiry"] = 5.0
    assert main._fno_momo_v2_skip(r, "CE", "NIFTY", dict(m, iv_pct=30.0), 20.0, STRONG, DET_UP, "") == "skipped_iv_rich"
    assert main._fno_momo_v2_skip(r, "CE", "NIFTY", m, 20.0, STRONG, DET_UP, "") is None
    assert main._fno_momo_v2_skip(r, "CE", "NIFTY", dict(m, chg60_pct=-1.0), None, STRONG, DET_UP, "") == \
        "skipped_1h_falling"


def test_intraday_oi_change_fills_kotak_rows(monkeypatch):
    monkeypatch.setattr(main, "_FNO_OI_DAY_FIRST", {})
    r = _orow(exp=EXP, oi_chg=None)
    main._fno_oi_first_note(r["contract"], 8000.0, time.time() - 600)
    m = main._fno_option_metrics(r, MON)  # openInterest 10000 now
    assert m["oi_change"] == 2000.0 and m["oi_build"] == "long_buildup" and m["oi_change_basis"].startswith("since ")
    assert main._fno_option_metrics(_orow(exp=EXP), MON)["oi_change_basis"] == "prev_close"


def test_sensex_spot_keeps_open_for_strict_sentiment(monkeypatch):
    import kotak_neo
    monkeypatch.setattr(main, "_FNO_KOTAK_SPOT_CACHE", {})
    monkeypatch.setattr(main, "_FNO_INDEX_DETAIL_CACHE", {"data": {}})
    monkeypatch.setattr(kotak_neo, "quotes", lambda toks, quote_type="all": [
        {"ltp": "84400", "per_change": "0.4", "ohlc": {"open": "84100", "close": "84060"}}])
    assert main._fno_kotak_spot("SENSEX") == (84400.0, 0.4)
    assert main._FNO_KOTAK_SPOT_CACHE["SENSEX"]["open"] == 84100.0
