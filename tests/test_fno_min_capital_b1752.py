"""B-1752: View 6 trade table shows the minimum capital (1 lot x entry premium) per trade."""
import main


def setup_function(_):
    main._FNO_LOT_CACHE.clear()


def test_min_capital_is_premium_times_lot():
    assert main._fno_min_capital_inr(182.0, 75) == 13650.0
    assert main._fno_min_capital_inr(829.0, 20) == 16580.0


def test_min_capital_unknown_lot_is_none():
    assert main._fno_min_capital_inr(182.0, None) is None
    assert main._fno_min_capital_inr(None, 75) is None


def test_lot_cached_hit_and_miss_ttl():
    calls = []

    def res(u):
        calls.append(u)
        return ({"lot_size": 75}, None) if u == "NIFTY" else (None, "no contract")
    assert main._fno_lot_size_cached("nifty", now_ts=1000, resolver=res) == 75
    assert main._fno_lot_size_cached("NIFTY", now_ts=2000, resolver=res) == 75
    assert calls == ["NIFTY"]  # hit cached for 12 h
    assert main._fno_lot_size_cached("FINNIFTY", now_ts=1000, resolver=res) is None
    assert main._fno_lot_size_cached("FINNIFTY", now_ts=1300, resolver=res) is None
    assert calls == ["NIFTY", "FINNIFTY"]  # miss cached 10 min
    assert main._fno_lot_size_cached("FINNIFTY", now_ts=1700, resolver=res) is None
    assert calls[-1] == "FINNIFTY" and len(calls) == 3  # retried after 10 min


def test_resolver_error_or_zero_lot_never_raises():
    def boom(u):
        raise RuntimeError("feed down")
    assert main._fno_lot_size_cached("SENSEX", now_ts=1, resolver=boom) is None
    main._FNO_LOT_CACHE.clear()
    assert main._fno_lot_size_cached("SENSEX", now_ts=1, resolver=lambda u: ({"lot_size": 0}, None)) is None
    assert main._fno_lot_size_cached("", now_ts=1, resolver=boom) is None


def test_view6_html_has_column():
    t = open("static/trade-view6.html").read()
    assert "Min capital (1 lot)" in t and "min_capital_inr" in t
