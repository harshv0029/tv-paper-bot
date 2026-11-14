"""B-1569: COMMODITY + CURRENCY categories, single/multi leg option labels, per-category sessions, closed-market limits."""
import datetime as dt

import main
import strategy_registry as sr


def test_new_categories_and_labels():
    keys = {c.value for c in sr.TradeCategory}
    assert {"commodity", "currency", "options", "options_multi"} <= keys
    assert sr.CATEGORY_LABELS["options"] == "Single leg option"
    assert sr.CATEGORY_LABELS["options_multi"] == "Multi leg option"
    assert set(sr.CATEGORY_LABELS) == keys
    assert sr.MAX_STRATEGY_CHECKS_PER_SYMBOL_PER_CYCLE == len(sr.TradeCategory) * sr.TOP_N_PER_CATEGORY


def test_mcx_strategies_moved_to_commodity_equity_intermarket_untouched():
    mcx = [d for d in sr.REGISTRY if "mcx" in str(getattr(d.metrics, "universe", "") or "").lower()]
    assert mcx and all(sr.TradeCategory.COMMODITY in d.categories for d in mcx)
    assert all(sr.TradeCategory.FUTURES not in d.categories for d in mcx)
    usd = [d for d in sr.REGISTRY if d.name.startswith("intermarket__usdinr")]
    assert usd and all(sr.TradeCategory.CURRENCY not in d.categories for d in usd)  # equity swing reading a signal


def test_funnel_and_labels_endpoint_cover_every_category():
    cats = main._funnel_categories()
    assert set(cats) == {c.value for c in sr.TradeCategory}
    d = main.category_labels()
    assert [c["key"] for c in d["categories"]] == cats


def _ist(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi)


def test_category_sessions():
    mon = _ist(2026, 11, 16, 10, 0)
    assert main.category_market_open("buy", mon) and main.category_market_open("commodity", mon)
    eve = _ist(2026, 11, 16, 20, 0)
    assert not main.category_market_open("swing", eve) and main.category_market_open("commodity", eve)
    assert not main.category_market_open("currency", eve)
    hol = _ist(2026, 11, 24, 11, 0)  # NSE holiday: MCX still runs
    assert not main.category_market_open("options", hol) and main.category_market_open("commodity", hol)
    sat = _ist(2026, 11, 14, 11, 0)
    assert not any(main.category_market_open(c, sat) for c in main._funnel_categories())


def test_all_markets_closed_has_open_buffer():
    assert main.all_markets_closed(_ist(2026, 11, 14, 11, 0))      # Saturday
    assert main.all_markets_closed(_ist(2026, 11, 17, 2, 0))       # weekday night
    assert not main.all_markets_closed(_ist(2026, 11, 17, 8, 50))  # 10 min before MCX opens
    assert not main.all_markets_closed(_ist(2026, 11, 16, 23, 40))  # MCX just closed, still inside the buffer


def test_closed_market_slows_tick_and_noncritical_writers(monkeypatch):
    monkeypatch.setattr(main, "all_markets_closed", lambda now=None, buffer_min=15: True)
    assert main._scheduler_sleep_after_tick(5.0) == main.CLOSED_MARKET_TICK_SECONDS - 5.0
    monkeypatch.setattr(main, "_upstash_budget_level", lambda: 0)
    assert main._upstash_noncritical_interval(300) == 300 * main.CLOSED_MARKET_UPSTASH_SLOWDOWN
    monkeypatch.setattr(main, "all_markets_closed", lambda now=None, buffer_min=15: False)
    assert main._scheduler_sleep_after_tick(5.0) == main.SCHEDULER_INTERVAL_SECONDS - 5.0
