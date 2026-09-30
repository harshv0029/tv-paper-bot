"""Tests for the 2026-09-30 squareoff time change (explicit user
instruction, given the exact 2026-09-22 CAS-transition-rejection history:
"Keep last trade entry by 3:13 and all intra day exit at 3:14 at market
rate"). Supersedes the 2026-09-22 decision that had reverted a brief
912/3:12pm attempt back to 915/3:15pm - the user was shown that history
(moving the cutoff minute did not, by itself, avoid NSE's Closing-
Auction-Session transition rejecting orders around squareoff) and chose
to proceed anyway.

Two things this covers:
1. NSE_STOCK_DEFAULT_PARAMS and the three index configs now carry
   squareoff_min=914 (3:14pm), so ENTRY_CUTOFF_BEFORE_SQUAREOFF_MINUTES
   (unchanged, =1) naturally gives a 913 (3:13pm) entry cutoff - matching
   the user's own stated last-entry time without a separate change.
2. The real exit order path was ALREADY market-rate before this change
   (kotak_real_orders.place_real_exit/place_real_short_cover both use
   order_type="MKT" unconditionally) - locked in here so a future edit
   that quietly switches either to a LIMIT order is caught immediately,
   since that was central to what the user asked for.

_auto_signal_core/_short_signal_core's own default squareoff_min
parameter (15*60+15) is deliberately UNCHANGED - live calls always pass
squareoff_min=cfg["squareoff_min"] explicitly from WATCHLIST, so this is
a WATCHLIST-config-level policy change, not a core-function change; the
existing tests/test_opening_window_and_squareoff_time.py suite tests the
generic mechanism at that default and stays valid unchanged.

Run: pytest tests/test_squareoff_314pm.py -v
"""
import inspect

import main
import kotak_real_orders


def test_nse_stock_default_squareoff_is_314pm():
    assert main.NSE_STOCK_DEFAULT_PARAMS["squareoff_min"] == 15 * 60 + 14


def test_entry_cutoff_naturally_lands_at_313pm():
    squareoff = main.NSE_STOCK_DEFAULT_PARAMS["squareoff_min"]
    entry_cutoff = squareoff - main.ENTRY_CUTOFF_BEFORE_SQUAREOFF_MINUTES
    assert entry_cutoff == 15 * 60 + 13


def test_index_configs_share_the_same_314pm_squareoff():
    by_symbol = {cfg["symbol"]: cfg for cfg in main.WATCHLIST if cfg["symbol"] in ("^NSEI", "^NSEBANK", "^BSESN")}
    assert set(by_symbol) == {"^NSEI", "^NSEBANK", "^BSESN"}
    for symbol, cfg in by_symbol.items():
        assert cfg["squareoff_min"] == 15 * 60 + 14, f"{symbol} squareoff_min"


def test_every_nse_equity_watchlist_entry_uses_the_314pm_squareoff():
    nse_equities = [cfg for cfg in main.WATCHLIST if cfg["symbol"].endswith(".NS")]
    assert nse_equities, "expected at least one NSE equity in WATCHLIST"
    for cfg in nse_equities:
        assert cfg.get("squareoff_min") == 15 * 60 + 14, f"{cfg['symbol']} squareoff_min"


def test_real_long_exit_is_unconditionally_market_rate():
    src = inspect.getsource(kotak_real_orders.place_real_exit)
    assert 'order_type="MKT"' in src


def test_real_short_cover_is_unconditionally_market_rate():
    src = inspect.getsource(kotak_real_orders.place_real_short_cover)
    assert 'order_type="MKT"' in src
