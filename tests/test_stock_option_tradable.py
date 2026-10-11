import nse_fo_chain as n

C = {"premium": 50.0, "lot_size": 100}
L = {"bid": 49.5, "ask": 50.5, "open_interest": 100 * 500, "volume": 100 * 100}


def test_passes_liquid():
    assert n.stock_option_tradable(C, L) == (True, "ok")


def test_fail_closed_on_missing():
    assert not n.stock_option_tradable(None, L)[0]
    assert not n.stock_option_tradable(C, None)[0]
    assert not n.stock_option_tradable({"premium": 50.0}, L)[0]
    assert not n.stock_option_tradable({"lot_size": 100}, L)[0]
    for k in L:
        assert not n.stock_option_tradable(C, {**L, k: None})[0]


def test_rejections():
    assert "premium_below_min" in n.stock_option_tradable({**C, "premium": 1.0}, L)[1]
    assert "lot_notional" in n.stock_option_tradable({"premium": 5000.0, "lot_size": 100}, L)[1]
    assert "spread_too_wide" in n.stock_option_tradable(C, {**L, "bid": 40.0, "ask": 50.0})[1]
    assert not n.stock_option_tradable(C, {**L, "bid": 51.0, "ask": 50.0})[0]
    assert "open_interest" in n.stock_option_tradable(C, {**L, "open_interest": 100})[1]
    assert "volume" in n.stock_option_tradable(C, {**L, "volume": 1})[1]


def test_parse_liquidity():
    q = [{"bp": "49.5", "sp": "50.5", "open_int": "99", "last_volume": "7"}]
    assert n.parse_option_liquidity(q) == {"bid": 49.5, "ask": 50.5, "open_interest": 99.0, "volume": 7.0}
    q2 = [{"depth": {"buy": [{"price": "10"}], "sell": [{"price": "11"}]}}]
    r = n.parse_option_liquidity(q2)
    assert r["bid"] == 10.0 and r["ask"] == 11.0 and r["open_interest"] is None
    assert n.parse_option_liquidity({"error": 1}) == {"bid": None, "ask": None, "open_interest": None, "volume": None}
