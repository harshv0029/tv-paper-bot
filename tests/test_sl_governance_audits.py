"""B-530 / B-550 / B-506 audit tests: SL may only ratchet in the trade's
favour (long: up, short: down); the Kotak backcheck is category-agnostic;
exits are MKT and stop orders are trigger-gated 'SL' (documented)."""
import inspect
import re

import kotak_real_orders
import main


def test_long_sync_never_loosens_stop():
    src = inspect.getsource(main._maybe_sync_real_stop_loss)
    assert re.search(r"new_stop\s*<=\s*current_sl_price", src)


def test_short_sync_never_loosens_stop():
    src = inspect.getsource(main._maybe_sync_real_stop_loss_short)
    assert re.search(r"new_stop\s*>=\s*current_sl_price", src)


def test_swing_sync_only_places_missing_sl_never_modifies_existing():
    src = inspect.getsource(main._maybe_sync_real_swing_stop_loss)
    assert "sl_order_id IS NULL" in src


def test_backcheck_is_category_agnostic_swing_and_option_symbols():
    kotak_open = {
        "NYKAA-EQ": {"qty": 5, "is_short": False},
        "NIFTY26OCT24500CE": {"qty": 75, "is_short": False},
        "XYZ-EQ": {"qty": 3, "is_short": True},
    }
    out = main._find_unprotected_open_positions(kotak_open, [])
    assert {r["kotak_trading_symbol"] for r in out} == set(kotak_open)
    orders = [
        {"trdSym": "NYKAA-EQ", "trnsTp": "S", "prcTp": "SL", "ordSt": "trigger pending"},
        {"trdSym": "NIFTY26OCT24500CE", "trnsTp": "S", "prcTp": "SL-M", "ordSt": "open"},
        {"trdSym": "XYZ-EQ", "trnsTp": "B", "prcTp": "SL", "ordSt": "trigger pending"},
    ]
    assert main._find_unprotected_open_positions(kotak_open, orders) == []


def test_exits_are_market_and_stops_are_trigger_gated_sl():
    assert 'order_type="MKT"' in inspect.getsource(kotak_real_orders)
    assert 'order_type="SL"' in inspect.getsource(kotak_real_orders.place_real_stop_loss)
    assert 'order_type="SL"' in inspect.getsource(kotak_real_orders.place_real_short_stop_loss)
