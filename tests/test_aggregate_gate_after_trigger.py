"""B-1252: the aggregate open-risk gate must not return before the signal is evaluated;
it is applied after the trigger (blocked trigger counted, no order)."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.joinpath("main.py").read_text()


def _core():
    s = SRC.index("def _auto_signal_core(")
    return SRC[s:SRC.index("\ndef _chan_long_try_entry(", s)]


def test_gate_sets_flag_without_early_return():
    c = _core()
    i = c.index("agg_blocked = loss_so_far + open_reserved_risk_inr >= daily_loss_cap")
    assert "return result" not in c[i:i + 250]


def test_trigger_with_closed_gate_counts_blocked_and_places_nothing():
    c = _core()
    m = re.search(r"if entry_signal and agg_blocked:(.*?)return result", c, re.S)
    assert m and "_record_blocked_trigger" in m.group(1)
    assert "blocked_aggregate_open_risk" in m.group(1)
    # the block sits before the order-building branch
    assert m.start() < c.index("        if entry_signal:\n            # Stop is the strategy's own technical level")


def test_chan_entries_skipped_when_gate_closed():
    c = _core()
    assert "and not agg_blocked:\n            _chan_l = " in c
    assert "and not agg_blocked:\n            _gap_l = " in c
