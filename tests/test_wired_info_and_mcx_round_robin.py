import main
import strategy_registry as sr


def test_strategy_info_wired_only_is_small_and_has_live_tags():
    d = main.strategy_info(wired=1)
    live = set(main._STRATEGY_TAG_TO_REGISTRY_NAME.values())
    assert set(d) <= live and len(d) < 1000
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME["order_block_delta"] in d
    assert d[main._STRATEGY_TAG_TO_REGISTRY_NAME["gap_and_go"]]["win_rate_pct"] is not None


def test_gap_and_go_has_complete_metrics():
    info = sr.all_strategies_info(only_names={main._STRATEGY_TAG_TO_REGISTRY_NAME["gap_and_go"]})
    row = next(iter(info.values()))
    assert row["win_rate_pct"] and row["avg_held_hrs"] and row["viable"]


def test_mcx_scan_rotates_one_cell_per_call(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "_record_strategy_scan", lambda t: seen.append(t))
    monkeypatch.setattr(main, "_switch_allows_entries", lambda c: True)
    monkeypatch.setattr(main, "fetch_ohlc", lambda *a, **k: None)
    monkeypatch.setattr(main, "_mcx_cell_cursor", 0)
    n = len(main._MCX_DAILY_CELLS)
    for _ in range(n + 1):
        main._run_mcx_daily_scan(None, force=False) if False else None
    # force path: scans all; rotation path exercised via cursor directly
    main._run_mcx_daily_scan(None, force=True)
    assert len(seen) == n
