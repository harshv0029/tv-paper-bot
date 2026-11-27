"""B-1750: stale-quote guard for the View 6 single-leg option paper engine (fno_momo). A premium unchanged for >= 5 min
of observed samples is never entered (skipped_stale_quote) and a held one is closed (stale_quote_exit), left out of the
View 6 stats. PAPER ONLY: the shared fixture fails the test on any Kotak/real-order call."""
import json

import pytest

import main
from tests.test_fno_momo_paper_b1676 import DET_UP, MON, T0, _open, _orow, _ssnap, db  # noqa: F401 (db autouse)

ACTIVE = main.FNO_MOMO_VARIANTS  # captured before the shared db fixture narrows it
V3 = ACTIVE[0]
STRONG = {"NIFTY": 0.4, "INDIAVIX": 1.0}
EXP = "30-Nov-2026"
C = _orow(exp=EXP)["contract"]


@pytest.fixture(autouse=True)
def _idx(monkeypatch):
    monkeypatch.setattr(main, "_FNO_IDX_HIST", {"NIFTY": [(T0 - 330, 25680.0)]})
    monkeypatch.setattr(main, "_FNO_PX_HIST", {})
    monkeypatch.setattr(main, "_FNO_PX_HIST_1H", {})


def _flat(px, span_s=360, step=60):
    return [(T0 - a, px) for a in range(span_s, 0, -step)]


def test_unchanged_run_needs_observations_not_a_gap():
    assert main._fno_quote_stale(_flat(150.0), 150.0, T0) is True  # 6 equal samples over 6 min
    assert main._fno_quote_stale([(T0 - 900, 150.0)], 150.0, T0) is False  # one old sample: a gap, not evidence
    moved = _flat(150.0)[:-2] + [(T0 - 120, 150.5), (T0 - 60, 150.0)]
    assert main._fno_quote_stale(moved, 150.0, T0) is False  # it moved 2 min ago
    assert main._fno_quote_stale(_flat(150.0, span_s=240), 150.0, T0) is False  # only 4 min frozen
    assert main._fno_quote_stale(_flat(150.0), 151.0, T0) is False  # the current price differs
    assert main._fno_quote_stale([], 0, T0) is False


def test_stale_candidate_is_never_entered_every_active_variant(db):
    r = _orow(exp=EXP)
    main._FNO_PX_HIST[r["contract"]] = _flat(r["lastPrice"])
    for v in ACTIVE:
        if v["gate"] == main.FNO_ATMC_GATE:
            continue  # its own universe: covered in test_fno_atmchain_b1757
        main._FNO_MOMO_STATES[v["tag"]]["last_scan_ts"] = 0.0
        main._fno_momo_step(db, now=MON, snapshot=_ssnap([r], STRONG, DET_UP), now_ts=T0, variant=v)
        scan = main._FNO_MOMO_STATES[v["tag"]]["last_scan"]
        assert scan["entered"] is False and scan["skip"] == "skipped_stale_quote", (v["tag"], scan["skip"])
        assert scan["checked"][0] == {"contract": r["contract"], "skip": "skipped_stale_quote"}
    assert _open(db) is None
    logged = db.execute("SELECT skip FROM fno_momo_scan_log").fetchall()
    assert logged and {x[0] for x in logged} == {"skipped_stale_quote"}


def test_fresh_candidate_still_enters(db):
    r = _orow(exp=EXP)
    main._FNO_PX_HIST[r["contract"]] = [(T0 - 330, 146.0), (T0 - 60, 149.0)]
    main._fno_momo_step(db, now=MON, snapshot=_ssnap([r], STRONG, DET_UP), now_ts=T0, variant=V3)
    assert main._FNO_MOMO_STATES[V3["tag"]]["last_scan"]["entered"] is True


def _hold(db, tag, path, entry=150.0, opened=None):
    opened = opened if opened is not None else path[0][0]
    db.execute("INSERT INTO fno_momo_paper_trades (tag, day, status, contract, underlying, option_type, opened_ts, "
               "entry_price, peak_price, stop_price, last_price, last_ts, price_path) "
               "VALUES (?, '2026-11-23', 'open', ?, 'NIFTY', 'CE', ?, ?, ?, ?, ?, ?, ?)",
               (tag, C, opened, entry, entry, round(entry * 0.98, 4), path[-1][1], path[-1][0],
                json.dumps([list(p) for p in path])))
    db.commit()


def test_held_contract_frozen_5min_is_closed_and_left_out_of_stats(db, monkeypatch):
    _hold(db, V3["tag"], _flat(150.0))
    acts = main._fno_momo_step(db, now=MON, snapshot=_ssnap([], STRONG, DET_UP), now_ts=T0, variant=V3,
                               quote=lambda c, u: 150.0)
    assert [a["reason"] for a in acts] == ["stale_quote_exit"]
    row = db.execute("SELECT * FROM fno_momo_paper_trades").fetchone()
    assert row["status"] == "closed" and row["close_reason"].startswith(main.FNO_STALE_EXIT_REASON)
    assert main._fno_momo_is_stale_close(row["close_reason"]) and not main._fno_momo_is_stale_close("trailing_sl")
    monkeypatch.setattr(main, "get_db", lambda: _NoClose(db))
    out = main.fno_momo_paper(tag=V3["tag"])
    assert out["variants"][V3["tag"]]["n"] == 0 and out["variants"][V3["tag"]]["stale_excluded"] == 1
    assert out["all"]["n"] == 0 and out["all"]["stale_excluded"] == 1


def test_held_contract_that_moves_is_not_stale_closed(db):
    path = _flat(150.0)[:-1] + [(T0 - 60, 150.6)]
    _hold(db, V3["tag"], path)
    snap = _ssnap([_orow(exp=EXP, px=150.6)], STRONG, DET_UP)
    acts = main._fno_momo_step(db, now=MON, snapshot=snap, now_ts=T0, variant=V3, quote=lambda c, u: 150.6)
    assert acts == [] and _open(db) is not None


class _NoClose:
    """get_db() wrapper so the route's closing() leaves the test DB open."""
    def __init__(self, c):
        self._c = c

    def __getattr__(self, k):
        return getattr(self._c, k)

    def close(self):
        pass
