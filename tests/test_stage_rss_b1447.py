"""B-1447: per-stage RSS bookkeeping (measure before changing any prefetch/scan constant)."""
import main


def _reset():
    main._STAGE_RSS.clear()
    main._PREFETCH_ACTIVE["n"] = 0


def test_stage_records_before_after_delta(monkeypatch):
    _reset()
    vals = iter([100.0, 180.0])
    monkeypatch.setattr(main, "_current_rss_mb", lambda: next(vals))
    with main._stage_rss("swing_pattern_cells"):
        pass
    st = main._stage_rss_snapshot()["swing_pattern_cells"]
    assert st["runs"] == 1 and st["last_delta_mb"] == 80.0 and st["max_after_mb"] == 180.0
    assert st["last_overlap_prefetch"] is False and st["last_ist"].endswith("IST")


def test_overlap_with_prefetch_is_flagged(monkeypatch):
    _reset()
    monkeypatch.setattr(main, "_current_rss_mb", lambda: 500.0)
    with main._stage_rss("tick_prefetch", prefetch=True):
        with main._stage_rss("swing_short_1h"):
            pass
    snap = main._stage_rss_snapshot()
    assert snap["swing_short_1h"]["overlap_runs"] == 1
    assert main._PREFETCH_ACTIVE["n"] == 0


def test_exception_still_recorded_and_counter_released(monkeypatch):
    _reset()
    monkeypatch.setattr(main, "_current_rss_mb", lambda: None)
    try:
        with main._stage_rss("tick_prefetch", prefetch=True):
            raise ValueError("x")
    except ValueError:
        pass
    assert main._PREFETCH_ACTIVE["n"] == 0
    assert main._STAGE_RSS["tick_prefetch"]["runs"] == 1


def test_memory_check_exposes_stage_rss(monkeypatch):
    _reset()
    out = main._memory_pressure_check(now_mb=10.0, trim=False)
    assert "stage_rss" in out


def test_prefetch_wrapper_records_stage(monkeypatch):
    _reset()
    monkeypatch.setattr(main, "_prefetch_tick_ohlc_impl", lambda syms, *a, **k: {"symbols": len(syms)})
    assert main._prefetch_tick_ohlc(["A.NS"], workers=1) == {"symbols": 1}
    assert main._STAGE_RSS["tick_prefetch"]["runs"] == 1
