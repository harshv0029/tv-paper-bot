"""B-1715: the fast 5-15 min View 6 paper plan (index 5-min confirmation, premium 5-min momentum, delta, IV, 15-min
time stop). PAPER ONLY: the shared fixture fails the test on any Kotak/real-order call."""
import datetime as dt

import pytest

import main
from tests.test_fno_momo_paper_b1676 import DET_UP, MON, T0, _open, _orow, _ssnap, db  # noqa: F401 (db autouse)

V3 = main.FNO_MOMO_VARIANTS[0]
V5 = main.FNO_MOMO_VARIANTS[1]  # B-1718: the 5% trail twin
STRONG = {"NIFTY": 0.4, "INDIAVIX": 1.0}
EXP = "30-Nov-2026"


@pytest.fixture(autouse=True)
def _idx(monkeypatch):
    monkeypatch.setattr(main, "_FNO_IDX_HIST", {"NIFTY": [(T0 - 330, 25680.0)]})  # NIFTY last 25700: +0.08% in 5 min
    monkeypatch.setattr(main, "_FNO_PX_HIST_1H", {})


def _hist(contract, p5, p15=None):
    main._FNO_PX_HIST[contract] = ([(T0 - 930, p15)] if p15 else []) + [(T0 - 330, p5)]


def _run(db, rows, now=MON, pct=STRONG, det=DET_UP):
    main._FNO_MOMO_STATES[V3["tag"]]["last_scan_ts"] = 0.0
    main._fno_momo_step(db, now=now, snapshot=_ssnap(rows, pct, det), now_ts=T0, variant=V3)
    return main._FNO_MOMO_STATES[V3["tag"]]["last_scan"]


def test_v3_is_the_only_active_variant():
    assert V3["gate"] == "fast_v3" and V3["tag"] == main.FNO_MOMO_V3B_TAG  # B-1717
    assert "hold15" in V3["tag"] and "1h" not in V3["tag"] and V3.get("allow_expiry") is True
    assert main.FNO_MOMO_V3_VARIANT in main.FNO_MOMO_RETIRED_VARIANTS


def test_b1717_expiry_day_contract_is_included(db):
    r = _orow(exp="23-Nov-2026")  # expires today (MON = 2026-11-23)
    _hist(r["contract"], 146.0)
    scan = _run(db, [r])
    assert scan["skip"] != "skipped_expiry_day"
    assert scan["entered"] is True, scan.get("skip")
    m = {"chg5_pct": 2.0, "delta": 0.5}
    old = main._fno_momo_v3_skip(r, "CE", "NIFTY", m, None, STRONG, DET_UP, "2026-11-23", T0, 600)
    assert old == "skipped_expiry_day"  # the retired B-1715 rule, unchanged


def test_enters_without_waiting_for_15m_or_1h(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 146.0)  # only a 5-min base: 15m unknown, 1h unknown
    scan = _run(db, [r])
    assert scan["entered"] is True, scan.get("skip")
    assert _open(db)["tag"] == V3["tag"]


def test_skips_named(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 146.0)
    assert _run(db, [r], now=dt.datetime(2026, 11, 23, 12, 0))["skip"] == "skipped_midday_reversal_window"
    main._FNO_IDX_HIST["NIFTY"] = [(T0 - 330, 25699.0)]  # index flat over 5 min
    assert _run(db, [r])["skip"] == "skipped_index_not_moving"
    main._FNO_IDX_HIST["NIFTY"] = [(T0 - 330, 25680.0)]
    _hist(r["contract"], 146.0, 100.0)  # +50% over 15 min: exhausted
    assert _run(db, [r])["skip"] == "skipped_15m_exhausted"
    cheap = _orow(exp=EXP, k=25700, px=12.0)
    _hist(cheap["contract"], 11.5)
    assert _run(db, [cheap])["skip"] == "skipped_premium_too_small"
    _hist(r["contract"], 146.0)
    assert _run(db, [r], pct={"NIFTY": 0.1, "INDIAVIX": 1.0})["skip"] == "skipped_sentiment_disagrees"
    assert _open(db) is None


def test_oi_is_not_a_gate(db):
    r = _orow(exp=EXP, oi_chg=-500)  # short covering: v2 skipped it, v3 records it only
    _hist(r["contract"], 146.0)
    assert _run(db, [r])["entered"] is True


def test_ranks_by_5m_rise(db):
    a, b = _orow(exp=EXP, k=25000, px=150.0), _orow(exp=EXP, k=25050, px=125.0)
    _hist(a["contract"], 147.0)  # +2%
    _hist(b["contract"], 118.0)  # +5.9%
    assert _run(db, [a, b])["entered"] is True and _open(db)["contract"] == b["contract"]


def test_time_stop_15_min(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 146.0)
    _run(db, [r])
    assert _open(db) is not None
    acts = main._fno_momo_step(db, now=MON + dt.timedelta(minutes=16), snapshot=_ssnap([r], STRONG, DET_UP),
                               now_ts=T0 + 16 * 60, variant=V3)
    assert [a.get("reason") for a in acts] == ["time_exit_15min"] and _open(db) is None


# ---- B-1718 (user 2026-11-25: "Do that along with 2%. I need to see both results") ------------------------------
def test_b1718_two_trails_same_entry_compared(db):
    v2, v5 = V3, V5
    assert (v2["trail"], v5["trail"]) == (0.02, 0.05) and v2["gate"] == v5["gate"] == "fast_v3"
    assert "trail2" in v2["tag"] and "trail5" in v5["tag"]
    r = _orow(exp=EXP)
    _hist(r["contract"], 146.0)
    for v in (v2, v5):
        main._FNO_MOMO_STATES[v["tag"]]["last_scan_ts"] = 0.0
        main._fno_momo_step(db, now=MON, snapshot=_ssnap([r], STRONG, DET_UP), now_ts=T0, variant=v)
    rows = {x["tag"]: x for x in db.execute("SELECT * FROM fno_momo_paper_trades").fetchall()}
    assert rows[v2["tag"]]["contract"] == rows[v5["tag"]]["contract"]  # the same entry
    assert rows[v2["tag"]]["stop_price"] == pytest.approx(150.0 * 0.98)
    assert rows[v5["tag"]]["stop_price"] == pytest.approx(150.0 * 0.95)
    down = dict(r, lastPrice=145.5)  # -3%: under the 2% stop, above the 5% stop
    for v in (v2, v5):
        main._fno_momo_step(db, now=MON + dt.timedelta(minutes=1), snapshot=_ssnap([down], STRONG, DET_UP),
                            now_ts=T0 + 60, variant=v)
    st = {x["tag"]: x["status"] for x in db.execute("SELECT tag, status FROM fno_momo_paper_trades").fetchall()}
    assert st[v2["tag"]] != "open" and st[v5["tag"]] == "open"


def test_b1718_route_shows_both_trails(db):
    out = main.fno_momo_paper(tag=main.FNO_MOMO_V3B_T5_TAG)
    assert out["tag"] == main.FNO_MOMO_V3B_T5_TAG and out["trail_pct"] == 5.0
    assert out["variants"][main.FNO_MOMO_V3B_TAG]["trail_pct"] == 2.0
