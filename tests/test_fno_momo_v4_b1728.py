"""B-1728: the trend-day 5-min pullback paper plan (12% and 5% trail twins, 12% target, 15-min hold).
PAPER ONLY: the shared fixture fails the test on any Kotak/real-order call."""
import datetime as dt

import pytest

import main
import strategy_registry as sr
from tests.test_fno_momo_paper_b1676 import DET_UP, MON, T0, _open, _orow, _ssnap, db  # noqa: F401 (db autouse)

ACTIVE = main.FNO_MOMO_VARIANTS  # captured before the shared fixture narrows it
V12, V5 = ACTIVE[2], ACTIVE[3]
STRONG = {"NIFTY": 0.4, "INDIAVIX": 1.0}
EXP = "30-Nov-2026"


@pytest.fixture(autouse=True)
def _idx(monkeypatch):
    monkeypatch.setattr(main, "_FNO_IDX_HIST", {"NIFTY": [(T0 - 330, 25720.0)]})  # last 25700: -0.08% in 5 min
    monkeypatch.setattr(main, "_FNO_PX_HIST_1H", {})


def _hist(contract, p5):
    main._FNO_PX_HIST[contract] = [(T0 - 330, p5)]


def _run(db, rows, v=V12, now=MON, pct=STRONG):
    main._FNO_MOMO_STATES[v["tag"]]["last_scan_ts"] = 0.0
    main._fno_momo_step(db, now=now, snapshot=_ssnap(rows, pct, DET_UP), now_ts=T0, variant=v)
    return main._FNO_MOMO_STATES[v["tag"]]["last_scan"]


def _step(db, rows, mins, v=V12):
    return main._fno_momo_step(db, now=MON + dt.timedelta(minutes=mins), snapshot=_ssnap(rows, STRONG, DET_UP),
                               now_ts=T0 + mins * 60, variant=v)


def test_variants_tags_and_registry():
    assert V12["gate"] == V5["gate"] == "pullback_v4"
    assert (V12["trail"], V5["trail"]) == (0.12, 0.05) and V12["target"] == V5["target"] == 0.12
    assert "trail12_tgt12_hold15" in V12["tag"] and "trail5_tgt12_hold15" in V5["tag"]
    assert ACTIVE[0]["tag"] == main.FNO_MOMO_V3B_TAG  # the fast_v3 twins are unchanged
    names = {d.name for d in sr.REGISTRY}
    assert V12["tag"] in names and V5["tag"] in names


def test_enters_on_pullback_with_12pct_stop(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 152.0)  # premium dipped with the index: pullback entries do not need a premium rise
    scan = _run(db, [r])
    assert scan["entered"] is True, scan.get("skip")
    row = _open(db)
    assert row["tag"] == V12["tag"] and row["stop_price"] == pytest.approx(150.0 * 0.88)


def test_skips_named(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 152.0)
    main._FNO_IDX_HIST["NIFTY"] = [(T0 - 330, 25680.0)]  # index UP 0.08%: momentum, not a pullback
    assert _run(db, [r])["skip"] == "skipped_no_pullback"
    main._FNO_IDX_HIST["NIFTY"] = [(T0 - 330, 25720.0)]
    assert _run(db, [r], now=dt.datetime(2026, 11, 23, 12, 0))["skip"] == "skipped_midday_reversal_window"
    assert _run(db, [r], pct={"NIFTY": 0.1, "INDIAVIX": 1.0})["skip"] == "skipped_sentiment_disagrees"
    cheap = _orow(exp=EXP, k=25700, px=12.0)
    _hist(cheap["contract"], 12.5)
    assert _run(db, [cheap])["skip"] == "skipped_premium_too_small"
    assert _open(db) is None


def test_expiry_day_skipped_b1732(db):
    r = _orow(exp="23-Nov-2026")  # MON is 23-Nov: this contract expires today
    _hist(r["contract"], 152.0)
    for v in main.FNO_MOMO_VARIANTS[2:]:
        assert v["allow_expiry"] is False and "_noexp" in v["tag"]
        assert _run(db, [r], v=v)["skip"] == "skipped_expiry_day"
    assert _open(db) is None
    retired = {v["tag"] for v in main.FNO_MOMO_ALL_VARIANTS if v.get("retired")}
    assert {main.FNO_MOMO_V4_T12_TAG, main.FNO_MOMO_V4_T5_TAG, main.FNO_MOMO_V4NB_TAG, main.FNO_MOMO_V4NBW_TAG} <= retired


def test_target_hit_fills_at_target(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 152.0)
    _run(db, [r])
    acts = _step(db, [dict(r, lastPrice=170.0)], 3)
    assert [a.get("reason") for a in acts] == ["target_hit"] and _open(db) is None
    row = db.execute("SELECT close_price FROM fno_momo_paper_trades WHERE tag = ?", (V12["tag"],)).fetchone()
    assert row["close_price"] == pytest.approx(168.0)


def test_twins_differ_only_by_trail_and_time_stop(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 152.0)
    for v in (V12, V5):
        _run(db, [r], v=v)
    down = dict(r, lastPrice=140.0)  # -6.7%: under the 5% stop, above the 12% stop
    for v in (V12, V5):
        _step(db, [down], 2, v=v)
    st = {x["tag"]: x["status"] for x in db.execute("SELECT tag, status FROM fno_momo_paper_trades").fetchall()}
    assert st[V5["tag"]] != "open" and st[V12["tag"]] == "open"
    acts = _step(db, [down], 16, v=V12)
    assert [a.get("reason") for a in acts] == ["time_exit_15min"]


def test_fast_v3_has_no_target(db):
    assert ACTIVE[0].get("target") is None and ACTIVE[1].get("target") is None


def test_route_lists_target(db):
    out = main.fno_momo_paper(tag=V12["tag"])
    assert out["variants"][V12["tag"]]["target_pct"] == 12.0
    assert out["variants"][main.FNO_MOMO_V3B_TAG]["target_pct"] is None
