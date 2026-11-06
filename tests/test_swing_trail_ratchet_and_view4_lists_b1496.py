"""B-1496: the swing SL ratchet re-runs after every finished swing scan pass (IOC 2026-11-06: Kotak SL 136.38 stayed
behind trail 141.66 because the once-a-day ratchet ran at 09:15 before the pass raised the peak).
B-1497: View 4 footer lists the decision-tree symbols and the viable strategy names."""
import inspect
import pathlib

import main


class _T:
    def __init__(self, exc=None, cancelled=False):
        self._e, self._c = exc, cancelled

    def cancelled(self):
        return self._c

    def exception(self):
        return self._e


def test_finished_pass_bumps_the_seq_failed_pass_does_not():
    s0 = main._swing_scan_done_seq
    main._log_swing_scan_done(_T())
    assert main._swing_scan_done_seq == s0 + 1
    main._log_swing_scan_done(_T(exc=RuntimeError("x")))
    main._log_swing_scan_done(_T(cancelled=True))
    assert main._swing_scan_done_seq == s0 + 1


def test_tick_reruns_ratchet_after_a_pass_in_session_only():
    src = inspect.getsource(main._scheduler_tick)
    i = src.index("_swing_sl_trail_seq != _swing_scan_done_seq")
    blk = src[i:i + 600]
    assert "_nse_equity_market_open_now()" in blk and "_exchange_purge_window()" in blk
    assert "_sync_swing_resting_sl_to_strategy" in blk


def test_viable_names_endpoint_matches_stack_count():
    d = main.viable_strategy_names()
    assert set(d) >= {"count", "names", "label"} and d["count"] == len(d["names"])
    assert d["names"] == sorted(d["names"])


def test_view4_has_both_lists():
    h = pathlib.Path(main.__file__).with_name("static").joinpath("trade-view4.html").read_text()
    assert 'id="symList"' in h and 'id="viaList"' in h and "/viable-strategy-names" in h


def test_b1506_ratchet_seq_bumps_right_after_the_1d_long_walk():
    s0 = main._swing_scan_done_seq
    main._mark_swing_long_walk_done()
    assert main._swing_scan_done_seq == s0 + 1
    src = inspect.getsource(main._run_swing_scan_pass)
    i = src.index("_mark_swing_long_walk_done()")
    assert i < src.index("_stage_rss('swing_sector_rotation')") < src.index("_stage_rss('swing_long_1h')")
