"""B-1329: the 5-min governance backfill re-placed a resting target on every pass while the SL already held the full
qty, so Kotak T1-rejected it each time (ITC x4, 2026-10-21). After one T1 rejection the symbol is skipped for the day.
The full reconcile needs a live-account setup, so this checks the invariant in the source, like its neighbours."""
import inspect

import main


def test_backfill_target_skips_after_t1_rejection_today():
    src = inspect.getsource(main._reconcile_real_positions_core)
    assert "_tgt_day_key in _target_backfill_t1_rejected" in src
    place = src.index("place_real_target(r[\"kotak_trading_symbol\"], r[\"qty\"], target)")
    guard = src.index("_tgt_day_key in _target_backfill_t1_rejected")
    record = src.index("_target_backfill_t1_rejected.add(_tgt_day_key)")
    assert guard < place < record
    assert "_T1_HOLDINGS_MARKER in str(target_result.get(\"detail\")" in src[place:record]


def test_rejected_set_is_day_keyed():
    assert isinstance(main._target_backfill_t1_rejected, set)
    src = inspect.getsource(main._reconcile_real_positions_core)
    assert '_tgt_day_key = (r["symbol"], ist_now().strftime("%Y-%m-%d"))' in src
