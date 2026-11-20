"""B-1655: View 2/3 data (/strategy-symbol-matrix) timed out at 30 s on Render. The display loops now read the ALL
TRADING switch once per build and look registry rows up by index; the verdict must match the per-call gate exactly."""
from contextlib import closing

import main


def _set_switch(on: bool):
    with closing(main.get_db()) as c:
        c.execute("CREATE TABLE IF NOT EXISTS trading_control (id INTEGER PRIMARY KEY, enabled INTEGER)")
        c.execute("INSERT OR REPLACE INTO trading_control (id, enabled) VALUES (1, ?)", (1 if on else 0,))
        c.commit()


def test_once_switch_matches_per_call_gate_both_switch_states():
    tags = list(main._STRATEGY_TAG_TO_REGISTRY_NAME)[:300] + [None, "", "not_a_real_tag"]
    try:
        for on in (True, False):
            _set_switch(on)
            vv = main._viability_once_switch()
            for t in tags:
                assert vv(t) == main._is_strategy_viable_for_real_money(t), (on, t)
            if not on:
                assert not any(vv(t) for t in tags)
    finally:
        _set_switch(True)


def test_registry_entry_returns_first_match_like_linear_scan():
    import strategy_registry as sr
    for name in [d.name for d in sr.REGISTRY[:50]] + ["no_such_strategy_xyz"]:
        assert main._registry_entry(name) is next((x for x in sr.REGISTRY if x.name == name), None)


def test_matrix_compute_reads_switch_once():
    calls = {"n": 0}
    real = main.is_trading_enabled

    def counting(conn):
        calls["n"] += 1
        return real(conn)

    main.is_trading_enabled = counting
    try:
        main._strategy_scan_activity_compute(True)
    finally:
        main.is_trading_enabled = real
    assert calls["n"] <= 3, calls["n"]  # was one read per tag (~2,000)
