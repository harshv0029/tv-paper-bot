"""B-396: /scheduler-pipeline banner extras never raise and carry the engine-status fields."""
import os, tempfile
import main


def test_banner_extras_fields_present():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    main.DB_PATH = path; main.init_db()
    x = main._banner_extras()
    for k in ("mcx_scan_done_today", "mcx_next_scan", "trading_enabled", "wired_strategies", "wired_gate_open", "wired_gate_closed",
              "shadow_signals_total", "protection_check_age_s"):
        assert k in x
    assert x["wired_gate_open"] + x["wired_gate_closed"] == x["wired_strategies"]
