"""B-1637: View 4 'Expected exit' for an adopted holding says why it is blank (no time stop; ATR SL is the exit)."""
import main


def test_adopted_holding_basis_explains_blank():
    r = main._expected_exit_for_position("swing", "holding_atr_stop", "2026-11-17")
    assert r["expected_exit"] and "immediate" in r["expected_exit_basis"]


def test_tagged_swing_still_dated():
    r = main._expected_exit_for_position("swing", "order_block_delta", "2026-10-08")
    assert r["expected_exit"]
