"""B-1640: a target rejected under Kotak's T1-holdings rule is logged as skipped and not resent that day."""
import main


def test_t1_rejection_is_skipped_and_marked_for_today():
    main._target_backfill_t1_rejected.clear()
    ev = main._target_fail_event("ATGL.NS", {"ok": False, "detail": "RMS:Rule: Check T1 holdings including TT/BE"})
    assert ev == "skipped_t1_holdings"
    assert ("ATGL.NS", main.ist_now().strftime("%Y-%m-%d")) in main._target_backfill_t1_rejected


def test_other_rejections_stay_failed():
    main._target_backfill_t1_rejected.clear()
    assert main._target_fail_event("X.NS", {"ok": False, "detail": "login failed"}) == "failed"
    assert main._target_fail_event("X.NS", None) == "failed"
    assert not main._target_backfill_t1_rejected
