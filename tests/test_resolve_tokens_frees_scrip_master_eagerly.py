"""Regression tests for kotak_live_feed.resolve_tokens's eager cleanup
(2026-09-16, live Render OOM incident): all_nse_cm/by_name together
hold Kotak's ENTIRE nse_cm scrip master (tens of thousands of rows) -
needed only for the brief symbol-lookup window, but previously stayed
referenced by the function's own frame through the MCX resolution
step too. Freed via `del` right after the lookup completes. This test
proves resolve_tokens' actual correctness is unchanged, plus that the
del is really there in source (a behavioral proof that memory was
freed mid-function isn't practical from a black-box test).

Run: pytest tests/ -v
"""
import inspect
from unittest.mock import MagicMock

import kotak_live_feed as feed

_FIXTURE_ROWS = [
    {"pSymbolName": "RELIANCE", "pSymbol": "111"},
    {"pSymbolName": "TCS", "pSymbol": "222"},
    {"pSymbolName": "INFY", "pSymbol": "333"},
]


def test_resolve_tokens_source_frees_the_full_scrip_master_eagerly():
    src = inspect.getsource(feed.resolve_tokens)
    assert "del all_nse_cm, by_name" in src


def test_resolve_tokens_still_resolves_nse_equity_symbols_correctly():
    client = MagicMock()
    client.search_scrip.return_value = _FIXTURE_ROWS
    resolved = feed.resolve_tokens(client, ["RELIANCE.NS", "TCS.NS", "WIPRO.NS"])
    assert resolved["RELIANCE.NS"] == ("nse_cm", "111")
    assert resolved["TCS.NS"] == ("nse_cm", "222")
    assert "WIPRO.NS" not in resolved  # not in the fixture rows - stays unresolved


def test_resolve_tokens_still_resolves_index_tokens_without_a_scrip_search():
    client = MagicMock()
    resolved = feed.resolve_tokens(client, list(feed._INDEX_TOKENS.keys()))
    for sym, tok in feed._INDEX_TOKENS.items():
        assert resolved[sym] == tok
    client.search_scrip.assert_not_called()  # no NSE-suffixed symbols requested


def test_resolve_tokens_survives_a_search_scrip_failure_without_raising():
    client = MagicMock()
    client.search_scrip.side_effect = RuntimeError("network error")
    resolved = feed.resolve_tokens(client, ["RELIANCE.NS"])
    assert "RELIANCE.NS" not in resolved
