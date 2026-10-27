"""B-1252 part 2: in _auto_signal_core the aggregate open-risk gate is applied AFTER the entry signal
is evaluated. A fired signal blocked by the gate is counted as a blocked trigger; no order is placed;
the 2% cap formula is unchanged."""
import re
from pathlib import Path

import main

SRC = Path(__file__).resolve().parent.parent.joinpath("main.py").read_text()


def _core():
    s = SRC.index("def _auto_signal_core(")
    return SRC[s:SRC.index("\ndef _chan_long_try_entry(", s)]


def test_cap_formula_unchanged():
    c = _core()
    assert "daily_loss_cap = capital * daily_risk_pct / 100" in c
    assert "agg_blocked = loss_so_far + open_reserved_risk_inr >= daily_loss_cap" in c


def test_gate_flag_never_returns_early():
    c = _core()
    flag = c.index("agg_blocked = loss_so_far + open_reserved_risk_inr >= daily_loss_cap")
    act = c.index('result["action_taken"] = "blocked_aggregate_open_risk"')
    # exactly one place reports the block, and it is after the flag is computed
    assert c.count('"blocked_aggregate_open_risk"') == 1
    assert act > flag
    # no `if agg_blocked: ... return` short-circuit before the signal is evaluated
    m = re.search(r"\n( *)if agg_blocked:\n((?:\1    [^\n]*\n|\n)*)", c)
    assert m, "if agg_blocked: block not found"
    assert "return" not in m.group(2)


def test_block_sits_after_signal_and_sentiment_and_before_order_branch():
    c = _core()
    sentiment = c.index('result["sentiment_gate"] = {"allowed": sentiment_allowed')
    gate = c.index("if entry_signal and agg_blocked:")
    order = c.index("        if entry_signal:\n            # Stop is the strategy's own technical level")
    assert sentiment < gate < order
    block = c[gate:order]
    assert "_record_blocked_trigger(" in block and "return result" in block


def test_record_blocked_trigger_counts_per_tag_and_resets_daily(monkeypatch):
    import datetime as dt
    saved = dict(main._strategy_blocked_triggers)
    try:
        main._strategy_blocked_triggers.clear()
        day1 = dt.datetime(2026, 10, 27, 10, 0)
        monkeypatch.setattr(main, "ist_now", lambda: day1)
        main._record_blocked_trigger("universal_score")
        main._record_blocked_trigger("universal_score")
        main._record_blocked_trigger("orb_breakout")
        assert main._strategy_blocked_triggers["universal_score"] == 2
        assert main._strategy_blocked_triggers["orb_breakout"] == 1
        day2 = dt.datetime(2026, 10, 28, 10, 0)
        monkeypatch.setattr(main, "ist_now", lambda: day2)
        main._record_blocked_trigger("universal_score")
        assert main._strategy_blocked_triggers["universal_score"] == 1
        assert "orb_breakout" not in main._strategy_blocked_triggers
        assert main._strategy_blocked_triggers["_day"] == "2026-10-28"
    finally:
        main._strategy_blocked_triggers.clear()
        main._strategy_blocked_triggers.update(saved)
