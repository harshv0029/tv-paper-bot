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
    if request.node.fspath.basename in ("test_viable_stack_never_empty.py", "test_b1379_pileup_and_sl_lock.py"):
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


@pytest.fixture(autouse=True)
def _registry_gate_without_stack_in_tests(request, monkeypatch):
    """2026-10-21: live real entry needs the explorer stack. Most gate tests check the registry PFnet path with no stack
    saved, so they run with the old fallback; test_real_entry_needs_explorer_stack.py checks the live rule itself."""
    if request.node.fspath.basename == "test_real_entry_needs_explorer_stack.py":
        return
    try:
        import main
    except Exception:
        return
    # a test that re-imports main leaves older test modules holding the previous module object: patch both
    for _m in {id(main): main, id(getattr(request.module, "main", main)): getattr(request.module, "main", main)}.values():
        if hasattr(_m, "REAL_ENTRY_REQUIRES_EXPLORER_STACK"):
            monkeypatch.setattr(_m, "REAL_ENTRY_REQUIRES_EXPLORER_STACK", False)


@pytest.fixture(autouse=True)
def _clear_fo_rows_cache():
    """B-1362: nse_fo_chain caches search_scrip rows; tests patch search_scrip with different data, so start empty."""
    import nse_fo_chain
    nse_fo_chain._fo_rows_cache.clear()


@pytest.fixture(autouse=True)
def _swing_session_open_in_tests(request, monkeypatch):
    """B-1373: real swing entries are blocked outside NSE hours; existing swing tests assume an open session, so stub it
    open (test_swing_entry_market_closed.py checks the closed case itself)."""
    if request.node.fspath.basename == "test_swing_entry_market_closed.py":
        return
    try:
        import main
    except Exception:
        return
    for _m in {id(main): main, id(getattr(request.module, "main", main)): getattr(request.module, "main", main)}.values():
        if hasattr(_m, "_swing_real_entry_session_open"):
            monkeypatch.setattr(_m, "_swing_real_entry_session_open", lambda: True)


@pytest.fixture(autouse=True)
def _reset_recent_sl_placed():
    """B-1379: kotak_real_orders remembers SLs it placed in the last few seconds; never carry that between tests."""
    import kotak_real_orders as _kro
    _kro._RECENT_SL_PLACED.clear()
    yield
    _kro._RECENT_SL_PLACED.clear()
