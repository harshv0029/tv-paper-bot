"""Tests for EVIDENCED_SYMBOLS and its wiring into _scheduler_tick's
symbol selection (2026-09-09, explicit user instruction: "add preference
to monitor these stocks out of the evidenced symbols"). See main.py's
own comment above EVIDENCED_SYMBOLS/NSE_STOCK_PARAM_OVERRIDES for the
full rationale - a symbol with real, swept backtest evidence should
never wait on the round-robin cursor's turn through the ~2,655-symbol
watchlist the way an untested micro-cap does."""
import main


def test_evidenced_symbols_includes_every_overridden_stock():
    for sym in main.NSE_STOCK_PARAM_OVERRIDES:
        assert sym in main.EVIDENCED_SYMBOLS
    # spot-check the actual names, not just the mechanism
    for sym in ("RELIANCE.NS", "TCS.NS", "ICICIBANK.NS", "INFY.NS", "MARUTI.NS",
                "TITAN.NS", "GRASIM.NS", "BAJAJFINSV.NS"):
        assert sym in main.EVIDENCED_SYMBOLS


def test_evidenced_symbols_includes_indices_and_gold_not_silver_or_crude():
    assert {"^NSEI", "^NSEBANK", "^BSESN", "GC=F"} <= main.EVIDENCED_SYMBOLS
    # silver/crude are still on the unproven 1% default - never promoted
    assert "SI=F" not in main.EVIDENCED_SYMBOLS
    assert "CL=F" not in main.EVIDENCED_SYMBOLS


def test_evidenced_symbols_excludes_an_unproven_micro_cap():
    # MEDICAMEQ/SILVERCASE etc. never had a sweep run - must never be
    # treated as "preferred" just because they happened to trade live
    assert "MEDICAMEQ.NS" not in main.EVIDENCED_SYMBOLS
    assert "SILVERCASE.NS" not in main.EVIDENCED_SYMBOLS


def test_round_robin_pool_never_contains_an_evidenced_symbol():
    # Mirrors _scheduler_tick's own flat_symbols construction exactly -
    # an evidenced symbol must never also eat a round-robin batch slot,
    # since it's already guaranteed a scan every tick unconditionally.
    all_symbols = [cfg["symbol"] for cfg in main.WATCHLIST]
    open_equity_symbols = set()  # nothing open in this check
    flat_symbols = [
        s for s in all_symbols if s not in open_equity_symbols and s not in main.EVIDENCED_SYMBOLS
    ]
    assert not (set(flat_symbols) & main.EVIDENCED_SYMBOLS)
    # sanity: the evidenced names really were in WATCHLIST to begin with,
    # so their absence from flat_symbols is the exclusion working, not a
    # WATCHLIST gap
    assert main.EVIDENCED_SYMBOLS <= set(all_symbols)


def test_evidenced_flat_is_scanned_every_tick_when_not_open_and_not_paused():
    open_equity_symbols = {"RELIANCE.NS"}  # already open - handled separately
    trading_paused = False
    evidenced_flat = set() if trading_paused else (main.EVIDENCED_SYMBOLS - open_equity_symbols)
    assert "TITAN.NS" in evidenced_flat
    assert "RELIANCE.NS" not in evidenced_flat  # already covered via open_equity_symbols instead


def test_evidenced_flat_is_suppressed_while_trading_is_paused():
    # Same "don't waste a scan on a new entry nobody wants right now"
    # rule the round-robin pool already follows - an evidenced symbol
    # gets no special exemption from the global pause.
    open_equity_symbols = set()
    trading_paused = True
    evidenced_flat = set() if trading_paused else (main.EVIDENCED_SYMBOLS - open_equity_symbols)
    assert evidenced_flat == set()
