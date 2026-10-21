import pytest


@pytest.fixture(autouse=True)
def _swing_entry_cutoff_off_by_default(monkeypatch):
    # The 15:00 IST real swing entry cutoff is wall-clock dependent; tests that
    # exercise it set it explicitly. Everything else must not depend on when it runs.
    import main
    monkeypatch.setattr(main, "SWING_REAL_ENTRY_CUTOFF_MIN", 24 * 60 + 1)


import pytest as _pytest_viab


@_pytest_viab.fixture(autouse=True)
def _reset_viable_stack_state():
    """The explorer viable stack is process-global state (strategy_registry.VIABLE_OVERRIDES/VIABLE_STACK_ACTIVE,
    reloaded from the DB by main._load_viable_overrides); never let one test's stack leak into another."""
    import sys as _sys
    _m = _sys.modules.get("main")
    _db_path = getattr(_m, "DB_PATH", None)
    try:
        import strategy_registry as _sr
        _sr.VIABLE_OVERRIDES.clear()
        _sr.VIABLE_STACK_ACTIVE = False
    except Exception:
        pass
    try:
        if _m is not None:
            _m._SCAN_ACTIVITY_CACHE.clear()  # B-1276 30s cache must not leak across tests
    except Exception:
        pass
    yield
    if _m is not None and _db_path is not None:
        _m.DB_PATH = _db_path  # a test that swaps in a temp DB (stack rows) must not leak it


@pytest.fixture(autouse=True)
def _no_live_viable_stack_restore(request, monkeypatch):
    """B-1325: the stack restore pulls the owner's LIVE explorer stack (Upstash, then git) into the test DB, after
    which every viability test follows whatever stack was last saved. Only the restore's own tests may reach out."""
    if request.node.fspath.basename == "test_viable_stack_never_empty.py":
        return
    import main
    monkeypatch.setattr(main, "_ensure_viable_stack_hydrated", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _scan_gate_ignores_todays_calendar(monkeypatch):
    """_run_swing_scan / _scheduler_tick skip on NSE holidays and weekends.
    Tests that exercise them must not depend on the day the suite runs, so
    the no-argument ("today") form is pinned open. Explicit-date calls (the
    calendar tests) still hit the real function."""
    try:
        import main
    except Exception:
        return
    real = main.is_nse_trading_day
    monkeypatch.setattr(
        main, "is_nse_trading_day",
        lambda date=None: True if date is None else real(date))


@pytest.fixture(autouse=True)
def _option_pool_open_except_its_own_tests(request, monkeypatch):
    """B-1314's option-pool gate rejects the placeholder tags many option-mechanics tests use; those tests exercise
    SL/sizing, not the pool, so the gate is opened for them. tests/test_option_pool_gate.py tests the real gate."""
    if request.node.module.__name__.endswith("test_option_pool_gate"):
        return
    try:
        import main
    except Exception:
        return
    monkeypatch.setattr(main, "_option_pool_allows", lambda tag: True)


@pytest.fixture(autouse=True)
def _option_spread_unread_by_default(request, monkeypatch):
    """B-1328: _real_fo_buy_contract reads the live bid/ask; tests must never reach Kotak. Unread = no gate."""
    if request.node.fspath.basename == "test_option_spread_gate.py":
        return
    try:
        import nse_fo_chain
    except Exception:
        return
    monkeypatch.setattr(nse_fo_chain, "fetch_option_liquidity",
                        lambda c: {"bid": None, "ask": None, "open_interest": None, "volume": None})
