"""B-1650: per-phase tick timing (observability only) so the ~450 s ticks can be attributed."""
import asyncio
import time

import main


def test_off_loop_and_timed_thread_record_phases():
    main._TICK_PHASES.update(day="", max={}, current={})

    def slow_step(conn):
        time.sleep(0.05)

    def plain():
        time.sleep(0.02)

    asyncio.run(main._real_off_loop(slow_step))
    asyncio.run(main._timed_aw(asyncio.to_thread(plain), "plain"))
    top = main._tick_phases_take_top()
    names = [k for k, _ in top]
    assert names[0] == "slow_step" and "plain" in names
    assert main._TICK_PHASES["current"] == {}
    assert main._TICK_PHASES["max"]["slow_step"]["seconds"] >= 0.04
    assert "phase_max_today" in main._tick_timing_summary()


def test_phase_noted_even_when_step_raises():
    main._TICK_PHASES.update(day="", max={}, current={})

    def boom(conn):
        raise ValueError("x")
    try:
        asyncio.run(main._real_off_loop(boom))
    except ValueError:
        pass
    assert "boom" in main._TICK_PHASES["current"]
