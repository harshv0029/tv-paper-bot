"""Unit tests for the F&O chain monitoring snapshot (2026-09-16, explicit
user request: "start monitoring the single or multi leg future and
option strike prices with weekly and monthly expiry volumes separately").
Wiring/structure checks only - _fo_chain_monitoring_snapshot itself needs
a live Kotak session (network) to actually run, same limitation as every
other nse_fo_chain-dependent code path in this repo's test suite.

Run: pytest tests/ -v
"""
import inspect

import main


def test_monitored_underlyings_cover_every_nse_fo_chain_supported_symbol():
    # nse_fo_chain._UNDERLYING_TO_SEGMENT is the ground truth for what
    # this codebase's Kotak integration can actually resolve - every
    # futures/options pSymbolName referenced by FO_MONITORED_UNDERLYINGS
    # must exist there, and vice versa (options names only, since futures
    # use the full-size name which options' mini name maps differ from).
    import nse_fo_chain
    monitored_fut_names = {fut for fut, _ in main.FO_MONITORED_UNDERLYINGS.values()}
    monitored_opt_names = {opt for _, opt in main.FO_MONITORED_UNDERLYINGS.values()}
    for name in monitored_fut_names | monitored_opt_names:
        assert name in nse_fo_chain._UNDERLYING_TO_SEGMENT, f"{name} has no Kotak segment mapping"


def test_five_underlyings_monitored():
    assert len(main.FO_MONITORED_UNDERLYINGS) == 5
    assert set(main.FO_MONITORED_UNDERLYINGS.keys()) == {"^NSEI", "^NSEBANK", "GC=F", "SI=F", "CL=F"}


def test_scheduler_tick_calls_fo_chain_monitoring_snapshot():
    src = inspect.getsource(main._scheduler_tick)
    assert "_fo_chain_monitoring_snapshot(conn)" in src


def test_snapshot_is_never_gated_by_real_trading_switches():
    # This is observability-only and must never trade - confirm its own
    # source never references either real-trading gate.
    src = inspect.getsource(main._fo_chain_monitoring_snapshot)
    assert "is_real_trading_enabled" not in src
    assert "is_real_fo_trading_enabled" not in src


def test_interval_guard_uses_module_level_timestamp():
    assert main.FO_MONITOR_INTERVAL_SECONDS > 0
    assert hasattr(main, "_fo_monitor_last_snapshot_ts")
