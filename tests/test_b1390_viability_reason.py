"""B-1390: every viability-gate rejection row records WHY, and View 4's unlock hint shows it instead of a guess."""
import sqlite3
import types

import main
from tests.test_viability_rejections_counter import _db, _stack


def test_verdict_reasons(monkeypatch):
    import strategy_registry as sr
    monkeypatch.setattr(main, "_STRATEGY_TAG_TO_REGISTRY_NAME", {"t": "reg_t", "n": "reg_none"})
    strat = types.SimpleNamespace(metrics=types.SimpleNamespace(pfnet=1.5), is_viable=lambda: True)
    monkeypatch.setattr(main, "_registry_entry", lambda n: strat if n == "reg_t" else None)
    monkeypatch.setattr(main, "_load_viable_overrides", lambda: None)
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", set())
    monkeypatch.setattr(main, "is_trading_enabled", lambda c: True)
    assert main._viability_verdict(None) == (False, "no_tag")
    assert main._viability_verdict("x") == (False, "unmapped_tag")
    assert main._viability_verdict("n") == (False, "no_registry_entry")
    monkeypatch.setattr(main, "REAL_ENTRY_REQUIRES_EXPLORER_STACK", True)
    monkeypatch.setattr(sr, "VIABLE_STACK_ACTIVE", False)
    assert main._viability_verdict("t") == (False, "no_stack")
    monkeypatch.setattr(sr, "VIABLE_OVERRIDES", {"reg_t"})
    assert main._viability_verdict("t") == (True, "override")
    assert main._is_strategy_viable_for_real_money("t") is True
    monkeypatch.setattr(main, "is_trading_enabled", lambda c: False)
    assert main._viability_verdict("t") == (False, "switch_off")
    assert main._is_strategy_viable_for_real_money("t") is False


def test_skip_rows_stamped_and_hint_shows_reason(monkeypatch):
    monkeypatch.setattr(main, "_viability_verdict", lambda tag, check_switch=True: (False, "switch_off"))
    c = _db()
    main._log_real_attempt(c, "TCS.NS", "B", "skipped_strategy_not_viable", strategy="tag_a")
    main._log_real_attempt(c, "TCS.NS", "B", "placed", strategy="tag_a", detail="ok")
    main._log_real_fo_attempt(c, "NIFTY:CE", "B", "skipped_strategy_not_viable", detail="strategy_tag=tag_f")
    dets = [r[0] for r in c.execute("SELECT detail FROM real_trades ORDER BY rowid")]
    assert dets == ["viability_reason=switch_off", "ok"]
    assert c.execute("SELECT detail FROM real_fo_trades").fetchone()[0] == "strategy_tag=tag_f viability_reason=switch_off"
    day = main.ist_now().strftime("%Y-%m-%d")
    c.execute("INSERT INTO real_trades (day, symbol, side, status, strategy) VALUES (?,'X','B','skipped_strategy_not_viable','tag_a')", (day,))
    rej = main._viability_rejections_today(c, day)
    by = {x["strategy"]: x for x in rej["by_strategy"]}
    assert by["tag_a"]["reasons"] == {"switch_off": 1, "not_recorded": 1}
    assert by["tag_f"]["reasons"] == {"switch_off": 1}
    mets = types.SimpleNamespace(pfnet=1.5, n_trades=500, avg_held_hrs=10.0)
    monkeypatch.setattr(main, "_STRATEGY_TAG_TO_REGISTRY_NAME", {"tag_a": "reg_a"})
    monkeypatch.setattr(main, "_registry_entry", lambda n: types.SimpleNamespace(metrics=mets))
    _stack(c, "pfnet(1.1-99), min(100), maxhold(100)")
    h = main._viability_unlock_hint(c, rej)
    e = {x["strategy"]: x for x in h["per_strategy"]}["tag_a"]
    assert e["changes"] == [] and "switch_off x1" in e["note"] and "not_recorded x1" in e["note"]
    assert "another rule" not in e["note"]


def test_stamp_never_claims_viable(monkeypatch):
    monkeypatch.setattr(main, "_viability_verdict", lambda tag, check_switch=True: (True, "viable"))
    assert main._stamp_viability_reason("strategy_tag=x", "x") == "strategy_tag=x viability_reason=unknown"
    monkeypatch.setattr(main, "_viability_verdict", lambda *a, **k: 1 / 0)
    assert main._stamp_viability_reason(None, "x") == "viability_reason=unknown"
