import os
import tempfile
import json
import time

import main
import strategy_registry as sr


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def test_label_parses_three_factors():
    c = main._stack_criteria("pfnet(1.05-100), min(30), maxhold(37.5)")
    assert c == {"pf_min": 1.05, "pf_max": 100.0, "min_trades": 30, "max_hold_hrs": 37.5}
    assert main._stack_criteria("pfnet(1.1-100), min(0), maxhold(any)")["max_hold_hrs"] is None
    assert main._stack_criteria("explorer set") is None


def test_names_follow_the_three_factors():
    crit = {"pf_min": 1.05, "pf_max": 100.0, "min_trades": 30, "max_hold_hrs": 37.5}
    names = main._names_meeting_criteria(crit)
    by = {d.name: d.metrics for d in sr.REGISTRY if d.metrics}
    for n, m in by.items():
        ok = (1.05 <= m.pfnet <= 100 and (m.n_trades or 0) >= 30
              and m.avg_held_hrs is not None and m.avg_held_hrs <= 37.5)
        assert (n in names) == ok


def test_active_stack_entry_with_criteria_is_rederived_not_snapshot():
    _fresh_db()
    with main.get_db() as c:
        c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (?,?,?)",
                  (time.time(), "pfnet(1.05-100), min(30), maxhold(37.5)", json.dumps(["not_a_real_strategy"])))
        c.commit()
    active = main._load_viable_overrides()
    assert "not_a_real_strategy" not in active
    assert active == main._names_meeting_criteria(main._stack_criteria("pfnet(1.05-100), min(30), maxhold(37.5)"))
    assert sr.VIABLE_STACK_ACTIVE is True
