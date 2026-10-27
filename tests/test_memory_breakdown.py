"""B-1382: /memory-breakdown census is read-only, cached and returns the expected shape."""
import main


def test_memory_breakdown_shape_and_cache():
    main._MEM_BREAKDOWN_STATE.update(ts=0.0, out=None)
    out = main.memory_breakdown()
    assert out["gc_objects"] > 0 and out["by_type"] and out["largest_globals"]
    assert {"name", "len", "shallow_bytes"} <= set(out["largest_globals"][0])
    assert main.memory_breakdown() is out  # cached for 60 s


def test_memory_breakdown_busy_returns_last():
    main._MEM_BREAKDOWN_STATE.update(ts=0.0, out={"x": 1})
    assert main._MEM_BREAKDOWN_LOCK.acquire()
    try:
        assert main.memory_breakdown() == {"x": 1}
    finally:
        main._MEM_BREAKDOWN_LOCK.release()
