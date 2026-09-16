"""Unit tests for SENSEX support and the full-strike-chain resolver
(nse_fo_chain.py, 2026-09-16, explicit user request: "Need to add Sensex
too, every strike means 24500, 24550... for nifty and both call n put
strike"). Mocks kotak_neo.search_scrip with rows shaped exactly like the
real live dump confirmed the same day (GET /kotak-neo/search-scrip
against bse_fo) - a genuinely distinct index "SENSEX50" (lot_size=75)
substring-matches "sensex" too and is deliberately included in every
fixture here to prove the exact-pSymbolName filter still excludes it,
same real finding that motivated the filter for NIFTY/NIFTYFPI.

Run: pytest tests/ -v
"""
import datetime as dt
from unittest.mock import patch

import nse_fo_chain


def _row(pSymbolName, pTrdSymbol, pOptionType, dStrikePrice, pExpiryDate,
         pInstType="IO", lLotSize=20, pSymbol=1000001):
    return {
        "pSymbol": pSymbol, "pSymbolName": pSymbolName, "pTrdSymbol": pTrdSymbol,
        "pOptionType": pOptionType, "dStrikePrice;": dStrikePrice,
        "pExpiryDate": pExpiryDate, "pInstType": pInstType, "lLotSize": lLotSize,
    }


# Dates computed relative to dt.date.today() rather than hardcoded, so this
# test never goes stale the way tests/test_trend_weakened_range_exclusion.py
# did (see that file's own docstring, fixed 2026-09-16 in this same
# session) - list_nse_option_strike_chain filters to (expiry - today).days
# >= 0, so a hardcoded past-tense expiry would silently start returning
# "no_upcoming_expiry" on every future test run.
#
# NEAR and FAR are both placed in the SAME calendar month, safely >=1 full
# month ahead of today regardless of today's own day-of-month - required
# for classify_expiries_weekly_monthly's real rule ("monthly" = latest
# expiry within the soonest expiry's own month) to actually pick FAR as
# "monthly" rather than collapsing to equal NEAR.
_TODAY = dt.date.today()
_TARGET_MONTH_INDEX = _TODAY.year * 12 + (_TODAY.month - 1) + 2  # +2 months out
_TARGET_YEAR, _TARGET_MONTH = divmod(_TARGET_MONTH_INDEX, 12)
_TARGET_MONTH += 1
_NEAR_EXPIRY = dt.date(_TARGET_YEAR, _TARGET_MONTH, 5)
_FAR_EXPIRY = dt.date(_TARGET_YEAR, _TARGET_MONTH, 26)
_NEAR_STR = _NEAR_EXPIRY.strftime("%d%b%Y")
_FAR_STR = _FAR_EXPIRY.strftime("%d%b%Y")
_NEAR_ISO = _NEAR_EXPIRY.strftime("%Y-%m-%d")
_FAR_ISO = _FAR_EXPIRY.strftime("%Y-%m-%d")

# Both expiries have a handful of SENSEX (lot 20) strikes plus interleaved
# SENSEX50 (lot 75) rows - shaped exactly like the real live dump confirmed
# 2026-09-16 (GET /kotak-neo/search-scrip against bse_fo) - that must never
# leak into the result.
_FIXTURE_ROWS = [
    _row("SENSEX", "SENSEXNEAR67000CE", "ce", 6700000.0, _NEAR_STR, pSymbol=1),
    _row("SENSEX", "SENSEXNEAR67100CE", "ce", 6710000.0, _NEAR_STR, pSymbol=2),
    _row("SENSEX", "SENSEXNEAR67200CE", "ce", 6720000.0, _NEAR_STR, pSymbol=3),
    _row("SENSEX50", "SENSEX50NEAR23250CE", "ce", 2325000.0, _NEAR_STR, pSymbol=101),
    _row("SENSEX", "SENSEXFAR67000CE", "ce", 6700000.0, _FAR_STR, pSymbol=4),
    _row("SENSEX", "SENSEXFAR67100CE", "ce", 6710000.0, _FAR_STR, pSymbol=5),
    _row("SENSEX50", "SENSEX50FAR23250CE", "ce", 2325000.0, _FAR_STR, pSymbol=102),
]


def test_sensex_maps_to_bse_fo_segment():
    assert nse_fo_chain._UNDERLYING_TO_SEGMENT["SENSEX"] == "bse_fo"


def test_sensex50_is_not_aliased_to_sensex():
    # A real, distinct BSE index - deliberately not added under "SENSEX50"
    # unless the user asks for it separately.
    assert "SENSEX50" not in nse_fo_chain._UNDERLYING_TO_SEGMENT


def test_strike_chain_excludes_the_substring_matching_sensex50_rows():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        chain, err = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
    assert err is None
    assert len(chain) == 3
    assert all(c["underlying"] == "SENSEX" for c in chain)
    assert all("SENSEX50" not in c["kotak_trading_symbol"] for c in chain)


def test_strike_chain_converts_raw_dstrikeprice_correctly():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        chain, err = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
    assert err is None
    # raw dStrikePrice; 6700000.0 -> real strike 67000.00 (lPrecision=2)
    assert [c["strike"] for c in chain] == [67000.0, 67100.0, 67200.0]


def test_strike_chain_is_sorted_ascending():
    unsorted_rows = list(reversed(_FIXTURE_ROWS))
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=unsorted_rows):
        chain, err = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
    assert err is None
    strikes = [c["strike"] for c in chain]
    assert strikes == sorted(strikes)


def test_strike_chain_picks_weekly_vs_monthly_expiry_correctly():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        weekly, err1 = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
        monthly, err2 = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "monthly")
    assert err1 is None and err2 is None
    assert all(c["expiry"] == _NEAR_ISO for c in weekly)
    assert all(c["expiry"] == _FAR_ISO for c in monthly)
    assert len(weekly) == 3
    assert len(monthly) == 2


def test_strike_chain_includes_put_side_when_requested():
    put_row = _row("SENSEX", "SENSEX26SEP67000PE", "pe", 6700000.0, "24Sep2026", pSymbol=6)
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS + [put_row]):
        calls, _ = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
        puts, _ = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "put", "weekly")
    assert len(calls) == 3
    assert len(puts) == 1
    assert puts[0]["right"] == "put"


def test_strike_chain_rejects_invalid_expiry_class():
    chain, err = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "daily")
    assert chain is None
    assert "invalid_expiry_class" in err


def test_strike_chain_reports_no_option_rows_for_unmapped_underlying():
    chain, err = nse_fo_chain.list_nse_option_strike_chain("UNKNOWNIDX", "call", "weekly")
    assert chain is None
    assert "no_segment_mapping_for" in err


def test_strike_chain_reports_no_option_rows_when_only_other_symbol_matches():
    # Only SENSEX50 rows in the response - real SENSEX has zero option
    # rows this tick (a plausible live state, e.g. between expiries).
    only_sensex50 = [r for r in _FIXTURE_ROWS if r["pSymbolName"] == "SENSEX50"]
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=only_sensex50):
        chain, err = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
    assert chain is None
    assert err == "no_exact_pSymbolName_match_for:SENSEX"


def test_strike_chain_dict_shape_matches_single_contract_resolver_minus_premium():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        chain, _ = nse_fo_chain.list_nse_option_strike_chain("SENSEX", "call", "weekly")
    expected_keys = {
        "underlying", "right", "expiry", "dte", "expiry_class", "strike",
        "kotak_trading_symbol", "instrument_token", "exchange_segment", "lot_size",
    }
    assert set(chain[0].keys()) == expected_keys
    assert "premium" not in chain[0]
