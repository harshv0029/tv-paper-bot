"""Unit tests for kotak_neo.search_scrip's login-client cache
(2026-09-16, live Render OOM/slowness incident): resolve_fo_universe()
calls search_scrip (via nse_fo_chain._fo_rows) roughly 645 times in one
pass, and each call used to trigger a brand-new kotak_neo.login() (a
real TOTP login) - real resource churn that was a major contributor
to both the resolution's slowness and the app's live OOM crashes.
search_scrip now reuses a cached login() client for
_SEARCH_SCRIP_CLIENT_CACHE_TTL_SECONDS. login() itself is unchanged -
still fresh every call - since real-order placement code deliberately
relies on that.

Run: pytest tests/ -v
"""
from unittest.mock import MagicMock, patch

import kotak_neo


def _reset_cache():
    kotak_neo._search_scrip_client_cache["value"] = None
    kotak_neo._search_scrip_client_cache["resolved_at"] = 0.0


def test_repeated_calls_within_ttl_reuse_the_same_client_not_a_fresh_login():
    _reset_cache()
    mock_client = MagicMock()
    mock_client.search_scrip.return_value = []
    with patch("kotak_neo.login", return_value=mock_client) as mock_login:
        kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="nifty")
        kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="banknifty")
        kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="sensex")
    mock_login.assert_called_once()
    assert mock_client.search_scrip.call_count == 3


def test_login_itself_is_never_touched_so_real_order_callers_stay_fresh():
    # search_scrip's caching must be entirely internal to this function -
    # login() itself must still do a fresh TOTP login every time it's
    # called directly, exactly as before, since kotak_real_orders.py/
    # kotak_real_fo_orders.py deliberately want that.
    _reset_cache()
    with patch("kotak_neo.NeoAPI") as mock_neo_api, \
         patch("kotak_neo._current_totp_code", return_value="123456"), \
         patch.dict("os.environ", {
             "KOTAK_NEO_CONSUMER_KEY": "x", "KOTAK_NEO_MOBILE_NUMBER": "x",
             "KOTAK_NEO_UCC": "x", "KOTAK_NEO_MPIN": "x", "KOTAK_NEO_TOTP_SEED": "x",
         }):
        mock_client = MagicMock()
        mock_client.totp_login.return_value = {"data": {}}
        mock_client.totp_validate.return_value = {"data": {}}
        mock_client.configuration.edit_token = "tok"
        mock_client.configuration.edit_sid = "sid"
        mock_neo_api.return_value = mock_client
        kotak_neo.login()
        kotak_neo.login()
    assert mock_neo_api.call_count == 2  # every login() call still builds a brand-new client


def test_cache_expires_after_ttl_and_re_logs_in():
    _reset_cache()
    mock_client = MagicMock()
    mock_client.search_scrip.return_value = []
    with patch("kotak_neo.login", return_value=mock_client) as mock_login:
        kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="nifty")
        kotak_neo._search_scrip_client_cache["resolved_at"] -= (
            kotak_neo._SEARCH_SCRIP_CLIENT_CACHE_TTL_SECONDS + 1
        )
        kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="nifty")
    assert mock_login.call_count == 2


def test_a_search_scrip_failure_clears_the_cache_and_reraises():
    _reset_cache()
    bad_client = MagicMock()
    bad_client.search_scrip.side_effect = RuntimeError("session expired")
    with patch("kotak_neo.login", return_value=bad_client):
        try:
            kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="nifty")
            assert False, "expected the exception to propagate"
        except RuntimeError:
            pass
    assert kotak_neo._search_scrip_client_cache["value"] is None

    good_client = MagicMock()
    good_client.search_scrip.return_value = []
    with patch("kotak_neo.login", return_value=good_client) as mock_login:
        kotak_neo.search_scrip(exchange_segment="nse_fo", symbol="nifty")
    mock_login.assert_called_once()  # the failure forced a fresh login, not a repeat of the stale one


def test_search_scrip_still_passes_through_every_filter_argument():
    _reset_cache()
    mock_client = MagicMock()
    mock_client.search_scrip.return_value = ["row"]
    with patch("kotak_neo.login", return_value=mock_client):
        result = kotak_neo.search_scrip(
            exchange_segment="nse_fo", symbol="nifty", expiry="2026-10-27",
            option_type="CE", strike_price=24500.0,
        )
    mock_client.search_scrip.assert_called_once_with(
        exchange_segment="nse_fo", symbol="nifty", expiry="2026-10-27",
        option_type="CE", strike_price=24500.0,
    )
    assert result == ["row"]
