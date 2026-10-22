import time

import main


def _wait(pred, secs=5):
    end = time.time() + secs
    while time.time() < end and not pred():
        time.sleep(0.05)


def test_background_reconcile_returns_at_once_and_stores_result(monkeypatch):
    monkeypatch.setattr(main, "_reconcile_real_positions_core", lambda adopt=None: {"ok": adopt})
    main._reconcile_job.clear()
    first = main._start_reconcile_job("*")
    assert first["state"] == "running"
    _wait(lambda: main._reconcile_job.get("state") != "running")
    assert main._reconcile_job["state"] == "done"
    assert main._reconcile_job["result"] == {"ok": "*"}


def test_background_reconcile_records_failure(monkeypatch):
    def boom(adopt=None):
        raise RuntimeError("x")
    monkeypatch.setattr(main, "_reconcile_real_positions_core", boom)
    main._reconcile_job.clear()
    main._start_reconcile_job(None)
    _wait(lambda: main._reconcile_job.get("state") != "running")
    assert main._reconcile_job["state"] == "failed"
    assert "RuntimeError" in main._reconcile_job["error"]


def test_status_carries_process_start_so_a_restart_mid_run_is_detectable(monkeypatch):
    """B-1313: a restart resets the in-memory job to idle; the boot time lets the workflow detect it and re-run."""
    monkeypatch.setattr(main, "_reconcile_real_positions_core", lambda adopt=None: {"ok": 1})
    monkeypatch.setattr(main, "_require_kotak_token", lambda request: None)
    main._reconcile_job.clear()
    main._reconcile_job.update(state="idle")
    assert main.kotak_neo_reconcile_status(None)["process_started"] == main._PROCESS_STARTED_TS
    assert main._start_reconcile_job("*")["process_started"] == main._PROCESS_STARTED_TS
    _wait(lambda: main._reconcile_job.get("state") != "running")
    wf = open(".github/workflows/kotak-reconcile.yml").read()
    assert "process_started" in wf and "restarting the reconcile once" in wf
