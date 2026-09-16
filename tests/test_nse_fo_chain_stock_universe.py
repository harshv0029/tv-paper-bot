"""Unit tests for STOCK_FO_UNDERLYINGS (nse_fo_chain.py, 2026-09-16,
explicit user request: expand F&O trading to single-stock options).
Confirmed live 2026-09-16 via GET /kotak-neo/search-scrip against
exchange_segment=nse_fo, option_type=FUT, no symbol filter - 210
distinct pInstType=="FUTSTK" pSymbolName values found that day.

Run: pytest tests/ -v
"""
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
