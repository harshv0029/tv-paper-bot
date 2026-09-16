"""Unit tests for /scheduler-status's unified watchlist_size (2026-09-16)
- now equity + every currently-subscribed F&O leg (options AND
futures), not equity-only, per the user's own earlier agreement that
this should happen once the F&O RSI2 engine started running on a
schedule. See main.scheduler_status.

Run: pytest tests/ -v
"""
from unittest.mock import patch

import main

_UNIVERSE = {
    ("nse_fo", "1"): {"kind": "option"},
    ("nse_fo", "2"): {"kind": "option"},
    ("nse_fo", "3"): {"kind": "future"},
}


def test_watchlist_size_is_equity_plus_fo_legs():
    with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value=_UNIVERSE):
        result = main.scheduler_status()
    assert result["watchlist_size"] == len(main.WATCHLIST) + 3


def test_watchlist_breakdown_splits_by_source():
    with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value=_UNIVERSE):
        result = main.scheduler_status()
    breakdown = result["watchlist_breakdown"]
    assert breakdown["equity"] == len(main.WATCHLIST)
    assert breakdown["fo_options"] == 2
    assert breakdown["fo_futures"] == 1
    assert breakdown["total"] == len(main.WATCHLIST) + 3


def test_watchlist_size_falls_back_to_equity_only_when_fo_universe_unresolved():
    with patch("kotak_fo_candle_feed.get_cached_fo_universe", return_value={}):
        result = main.scheduler_status()
    assert result["watchlist_size"] == len(main.WATCHLIST)
    assert result["watchlist_breakdown"] == {
        "equity": len(main.WATCHLIST), "fo_options": 0, "fo_futures": 0, "total": len(main.WATCHLIST),
    }


def test_watchlist_size_never_raises_when_fo_candle_feed_import_fails():
    with patch.dict("sys.modules", {"kotak_fo_candle_feed": None}):
        result = main.scheduler_status()  # import inside the function fails -> falls back, never raises
    assert result["watchlist_size"] == len(main.WATCHLIST)
