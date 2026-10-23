import asyncio
import main


def test_ok_no_trim():
    main._DATA_CACHE["x"] = 1
    r = main._memory_pressure_check(500.0)
    assert r["memory_level"] == "ok" and "x" in main._DATA_CACHE
    main._DATA_CACHE.pop("x", None)


def test_warn_trims_cache_only():
    main._DATA_CACHE["x"] = 1
    before = main._MEMORY_STATE["trims"]
    r = main._memory_pressure_check(1600.0)
    assert r["memory_level"] == "warn" and not main._DATA_CACHE
    assert main._MEMORY_STATE["trims"] == before + 1


def test_alarm_level_and_health_no_trim():
    assert main._memory_pressure_check(1900.0)["memory_level"] == "alarm"
    main._DATA_CACHE["y"] = 1
    h = asyncio.run(main.health())
    assert "memory_level" in h and "y" in main._DATA_CACHE
    main._DATA_CACHE.pop("y", None)
