"""B-1533: an identical real-entry skip (same day, symbol, side, status, strategy) is written to real_trades once."""
import main
from tests.test_viability_rejections_counter import _db


def _rows(c):
    return c.execute("SELECT symbol, side, status, strategy FROM real_trades ORDER BY rowid").fetchall()


def test_repeat_skip_written_once_distinct_kept():
    c = _db()
    for _ in range(5):
        main._log_real_attempt(c, "TCS.NS", "B", "skipped_sector_cap", strategy="t1")
    main._log_real_attempt(c, "TCS.NS", "B", "skipped_sector_cap", strategy="t2")      # other strategy
    main._log_real_attempt(c, "TCS.NS", "S", "skipped_sector_cap", strategy="t1")      # other side
    main._log_real_attempt(c, "TCS.NS", "B", "skipped_no_live_tick", strategy="t1")    # other status
    main._log_real_attempt(c, "INFY.NS", "B", "skipped_sector_cap", strategy="t1")     # other symbol
    main._log_real_attempt(c, "TCS.NS", "B", "skipped_sector_cap", strategy=None)
    main._log_real_attempt(c, "TCS.NS", "B", "skipped_sector_cap", strategy=None)
    assert len(_rows(c)) == 6


def test_placed_failed_and_exit_rows_never_deduped():
    c = _db()
    for _ in range(2):
        main._log_real_attempt(c, "TCS.NS", "B", "placed", strategy="t1")
        main._log_real_attempt(c, "TCS.NS", "B", "failed", strategy="t1")
        main._log_real_attempt(c, "TCS.NS", "S", "skipped_x", strategy="t1", leg="exit")
    assert len(_rows(c)) == 6


def test_funnel_still_counts_every_repeat(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "_record_funnel_event", lambda conn, kind, **kw: seen.append(kind))
    c = _db()
    for _ in range(3):
        main._log_real_attempt(c, "TCS.NS", "B", "skipped_sector_cap", strategy="t1")
    assert seen == ["reject"] * 3 and len(_rows(c)) == 1
