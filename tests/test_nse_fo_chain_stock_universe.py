"""Unit tests for STOCK_FO_UNDERLYINGS (nse_fo_chain.py, 2026-09-16,
explicit user request: expand F&O trading to single-stock options).
Confirmed live 2026-09-16 via GET /kotak-neo/search-scrip against
exchange_segment=nse_fo, option_type=FUT, no symbol filter - 210
distinct pInstType=="FUTSTK" pSymbolName values found that day.

Run: pytest tests/ -v
"""
import datetime as dt
from unittest.mock import patch

import nse_fo_chain


def test_stock_universe_has_the_confirmed_live_count():
    assert len(nse_fo_chain.STOCK_FO_UNDERLYINGS) == 210


def test_stock_universe_has_no_duplicates():
    assert len(nse_fo_chain.STOCK_FO_UNDERLYINGS) == len(set(nse_fo_chain.STOCK_FO_UNDERLYINGS))


def test_stock_universe_excludes_known_index_names():
    # "nifty" substring-collision family confirmed live earlier this
    # session (NIFTYFPI etc.) - none of these are FUTSTK, must never
    # leak into the stock universe.
    index_family = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYFPI", "NIFTYNXT50"}
    assert index_family.isdisjoint(nse_fo_chain.STOCK_FO_UNDERLYINGS)


def test_every_stock_underlying_maps_to_nse_fo_segment():
    for name in nse_fo_chain.STOCK_FO_UNDERLYINGS:
        assert nse_fo_chain._UNDERLYING_TO_SEGMENT[name] == "nse_fo"


def test_a_known_confirmed_stock_is_present():
    # RELIANCE - the specific stock live-confirmed with pInstType=FUTSTK,
    # lot_size=500, pSettlementType="Physical" this same session.
    assert "RELIANCE" in nse_fo_chain.STOCK_FO_UNDERLYINGS


def test_select_nse_future_resolves_a_real_futstk_row():
    # Live regression (2026-09-21): select_nse_future's own pInstType
    # filter only ever allowed FUTIDX/FUTCOM, never FUTSTK (the real
    # value this module's own docstring above confirms every single-
    # stock future actually carries) - so this always returned
    # "no_future_rows" for all 210 stock underlyings, live-confirmed via
    # /kotak-neo/fo-candle-feed-status showing every one of them failing
    # identically while NIFTY/BANKNIFTY (FUTIDX) succeeded. This proves
    # the fix: a real FUTSTK row for RELIANCE must now resolve.
    expiry = dt.date.today() + dt.timedelta(days=20)
    row = {
        "pSymbol": "12345", "pSymbolName": "RELIANCE", "pTrdSymbol": "RELIANCE26OCTFUT",
        "pInstType": "FUTSTK", "pExpiryDate": expiry.strftime("%d%b%Y"), "lLotSize": 500,
    }
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=[row]):
        contract, err = nse_fo_chain.select_nse_future("RELIANCE")
    assert err is None
    assert contract is not None
    assert contract["kotak_trading_symbol"] == "RELIANCE26OCTFUT"
    assert contract["lot_size"] == 500
