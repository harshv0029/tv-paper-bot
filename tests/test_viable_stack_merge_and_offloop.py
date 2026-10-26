"""B-1366: a restart must not drop the newest viability definition. B-1365: real-order work stays off the event loop."""
import inspect
import json
import os
import tempfile
from unittest.mock import patch

import main


def test_merge_makes_the_newest_saved_definition_active():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    with main.closing(main.get_db()) as c:  # stale restore: only the 21-Oct row
        c.execute("INSERT INTO strategy_viable_stack (created_at, label, names) VALUES (?,?,?)",
                  (1792559921.69, "pfnet(1.04-100), min(30), maxhold(6)", json.dumps([])))
        c.commit()
    git_rows = [{"created_at": 1792559921.69, "label": "pfnet(1.04-100), min(30), maxhold(6)", "names": []},
                {"created_at": 1793018299.87, "label": "pfnet(1.04-100), min(30), maxhold(12.5)", "names": []}]
    with patch.object(main, "_VIABLE_STACK_GIT_RESTORE_IN_TESTS", True), \
            patch("main._viable_stack_git_rows", return_value=git_rows), \
            patch("main.sync_generic_tables_external"):
        assert main._viable_stack_merge_remote() == 1
        assert main._viable_stack_merge_remote() == 0  # idempotent
    with main.closing(main.get_db()) as c:
        top = c.execute("SELECT label FROM strategy_viable_stack ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "maxhold(12.5)" in top


def test_first_sight_merges_before_pushing():
    src = inspect.getsource(main)  # conftest stubs the function itself
    src = src[src.index("def _ensure_viable_stack_hydrated"):]
    assert src.index("_viable_stack_merge_remote()") < src.index("_viable_stack_push_direct()  # first sight")


def test_scheduler_tick_runs_real_order_work_off_the_event_loop():
    src = inspect.getsource(main._scheduler_tick)
    for fn in ("_retry_pending_real_swing_orders", "_sync_swing_resting_sl_to_strategy", "_run_fo_options_scan",
               "_maybe_sync_real_stop_loss", "_maybe_place_real_entry", "_maybe_sync_real_stop_loss_short"):
        assert f"{fn}(conn" not in src and f"{fn}(real_conn" not in src, fn
        assert f"_real_off_loop({fn}" in src, fn
