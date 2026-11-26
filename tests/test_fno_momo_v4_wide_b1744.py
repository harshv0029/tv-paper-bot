"""B-1744: the pullback_v4 paper twins without the breadth check (a) and with one 09:30-14:30 window (b).
PAPER ONLY: the shared fixture fails the test on any Kotak/real-order call."""
import datetime as dt

import main
import strategy_registry as sr
from tests.test_fno_momo_v4_b1728 import EXP, _hist, _idx, _run, V12  # noqa: F401 (_idx autouse)
from tests.test_fno_momo_paper_b1676 import _open, _orow, db  # noqa: F401 (db autouse)

ACTIVE = main.FNO_MOMO_VARIANTS
VA = next(v for v in ACTIVE if v["tag"] == main.FNO_MOMO_V4NB_TAG)
VB = next(v for v in ACTIVE if v["tag"] == main.FNO_MOMO_V4NBW_TAG)
WEAK_BREADTH = {"NIFTY": {"last": 25700, "open": 25600, "advances": 20, "declines": 18}}


def _runb(db, rows, v, now=None, det=WEAK_BREADTH):
    main._FNO_MOMO_STATES[v["tag"]]["last_scan_ts"] = 0.0
    from tests.test_fno_momo_paper_b1676 import MON, T0, _ssnap
    main._fno_momo_step(db, now=now or MON, snapshot=_ssnap(rows, {"NIFTY": 0.4, "INDIAVIX": 1.0}, det), now_ts=T0,
                        variant=v)
    return main._FNO_MOMO_STATES[v["tag"]]["last_scan"]


def test_tags_registered_and_shape():
    names = {d.name for d in sr.REGISTRY}
    for v in (VA, VB):
        assert v["gate"] == "pullback_v4" and v["trail"] == 0.12 and v["target"] == main.FNO_V4_TARGET_PCT
        assert v["breadth"] is False and v["tag"] in names
    assert "windows" not in VA and VB["windows"] == ((570, 870),)
    assert [v["tag"] for v in ACTIVE[:4]] == [main.FNO_MOMO_V3B_TAG, main.FNO_MOMO_V3B_T5_TAG,
                                             main.FNO_MOMO_V4_T12_TAG, main.FNO_MOMO_V4_T5_TAG]  # old ones unchanged


def test_strict_breadth_flag():
    pct = {"NIFTY": 0.4, "INDIAVIX": 1.0}
    assert main._fno_momo_sentiment_strict("CE", "NIFTY", pct, WEAK_BREADTH) is False
    assert main._fno_momo_sentiment_strict("CE", "NIFTY", pct, WEAK_BREADTH, breadth=False) is True
    no_br = {"NIFTY": {"last": 25700, "open": 25600}}
    assert main._fno_momo_sentiment_strict("CE", "NIFTY", pct, no_br) is None
    assert main._fno_momo_sentiment_strict("CE", "NIFTY", pct, no_br, breadth=False) is True
    below_open = {"NIFTY": {"last": 25500, "open": 25600}}
    assert main._fno_momo_sentiment_strict("CE", "NIFTY", pct, below_open, breadth=False) is False


def test_weak_breadth_blocks_old_twin_but_enters_a(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 152.0)
    assert _runb(db, [r], V12)["skip"] == "skipped_sentiment_disagrees"
    scan = _runb(db, [r], VA)
    assert scan["entered"] is True, scan.get("skip")
    assert _open(db)["tag"] == VA["tag"]


def test_midday_only_b_enters(db):
    r = _orow(exp=EXP)
    _hist(r["contract"], 152.0)
    noon = dt.datetime(2026, 11, 23, 12, 0)
    assert _runb(db, [r], VA, now=noon)["skip"] == "skipped_midday_reversal_window"
    scan = _runb(db, [r], VB, now=noon)
    assert scan["entered"] is True, scan.get("skip")
    assert main._fno_momo_v4_skip(r, "CE", "NIFTY", {}, None, {}, {}, "", 0.0, 14 * 60 + 45, False,
                                  main.FNO_V4_WIDE_WINDOWS) == "skipped_midday_reversal_window"  # 14:45: past the window
