"""Tests for the 2026-09-22 fix: SL/target price rounding must use each
symbol's REAL tick size from Kotak's own scrip master, not a blanket
hardcoded 0.05 - explicit live finding: ENRIN.NS/ENRIN-EQ ("SIEMENS
ENERGY INDIA LTD", an ASM/surveillance-flagged scrip) has dTickSize=10,
lPrecision=2 -> a real tick of Rs 0.10. _round_to_tick's old fixed 0.05
default produced a price Kotak rejected ("16283: Order price is not a
multiple of tick size"), leaving the position naked until the 60s
protection-degraded safety net force-closed it. See
kotak_real_orders._tick_size_for's own docstring for the full incident.

Run: pytest tests/test_real_sl_tick_size.py -v
"""
from unittest.mock import MagicMock, patch

import kotak_real_orders

_ENRIN_SCRIP_ROW = {
    "pSymbolName": "ENRIN", "pTrdSymbol": "ENRIN-EQ", "pExchSeg": "nse_cm",
    "dTickSize": 10, "lPrecision": 2,
}


def setup_function():
    kotak_real_orders._tick_size_cache.clear()


# ---- _tick_size_for: pure lookup -------------------------------------------

def test_returns_the_real_wider_tick_for_a_surveillance_flagged_symbol():
    with patch("kotak_neo.search_scrip", return_value=[_ENRIN_SCRIP_ROW]):
        assert kotak_real_orders._tick_size_for("ENRIN-EQ") == 0.10


def test_returns_standard_005_for_an_ordinary_symbol():
    row = {"pSymbolName": "RELIANCE", "pTrdSymbol": "RELIANCE-EQ", "dTickSize": 5, "lPrecision": 2}
    with patch("kotak_neo.search_scrip", return_value=[row]):
        assert kotak_real_orders._tick_size_for("RELIANCE-EQ") == 0.05


def test_falls_back_to_005_when_no_matching_row_is_returned():
    with patch("kotak_neo.search_scrip", return_value=[{"pTrdSymbol": "SOMEOTHER-EQ", "dTickSize": 5, "lPrecision": 2}]):
        assert kotak_real_orders._tick_size_for("ENRIN-EQ") == 0.05


def test_falls_back_to_005_when_the_lookup_itself_raises():
    with patch("kotak_neo.search_scrip", side_effect=Exception("network hiccup")):
        assert kotak_real_orders._tick_size_for("ENRIN-EQ") == 0.05


def test_falls_back_to_005_on_an_unparseable_non_list_response():
    with patch("kotak_neo.search_scrip", return_value={"error": ["bad token"]}):
        assert kotak_real_orders._tick_size_for("ENRIN-EQ") == 0.05


def test_result_is_cached_a_second_call_does_not_hit_kotak_again():
    with patch("kotak_neo.search_scrip", return_value=[_ENRIN_SCRIP_ROW]) as mock_search:
        first = kotak_real_orders._tick_size_for("ENRIN-EQ")
        second = kotak_real_orders._tick_size_for("ENRIN-EQ")
    assert first == second == 0.10
    mock_search.assert_called_once()


# ---- place_real_stop_loss / place_real_target: wired in -------------------

def _mock_client(order_id="O1", status_row=None):
    client = MagicMock()
    client.place_order.return_value = {"nOrdNo": order_id}
    client.order_report.return_value = {"data": [status_row or {"ordSt": "trigger pending", "rejRsn": "--"}]}
    return client


def test_sl_placement_rounds_to_the_symbols_real_tick_not_005():
    # 3211.33 rounded to a 0.05 tick would be 3211.35 (still not a genuine
    # multiple of 0.10) - rounded to the real 0.10 tick it must be 3211.30.
    client = _mock_client()
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_neo.search_scrip", return_value=[_ENRIN_SCRIP_ROW]):
        result = kotak_real_orders.place_real_stop_loss("ENRIN-EQ", 1, 3211.33)
    assert result["ok"] is True
    assert result["trigger_price"] == 3211.30
    sent_price = client.place_order.call_args.kwargs["price"]
    sent_trigger = client.place_order.call_args.kwargs["trigger_price"]
    assert sent_price == "3211.3"
    assert sent_trigger == "3211.3"


def test_target_placement_rounds_to_the_symbols_real_tick_not_005():
    client = _mock_client()
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_neo.search_scrip", return_value=[_ENRIN_SCRIP_ROW]):
        result = kotak_real_orders.place_real_target("ENRIN-EQ", 1, 3298.47)
    assert result["ok"] is True
    assert result["target_price"] == 3298.5  # nearest 0.10 multiple


def test_ordinary_symbol_still_rounds_to_005_as_before():
    client = _mock_client()
    row = {"pSymbolName": "RELIANCE", "pTrdSymbol": "RELIANCE-EQ", "dTickSize": 5, "lPrecision": 2}
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_neo.search_scrip", return_value=[row]):
        result = kotak_real_orders.place_real_stop_loss("RELIANCE-EQ", 1, 2500.02)
    assert result["ok"] is True
    assert result["trigger_price"] == 2500.00


def test_tick_lookup_failure_falls_back_to_005_rather_than_blocking_placement():
    client = _mock_client()
    with patch("kotak_neo.login", return_value=client), \
         patch("kotak_neo.search_scrip", side_effect=Exception("network hiccup")):
        result = kotak_real_orders.place_real_stop_loss("ENRIN-EQ", 1, 3211.33)
    assert result["ok"] is True
    assert result["trigger_price"] == 3211.35  # old 0.05 behavior, unchanged on lookup failure
