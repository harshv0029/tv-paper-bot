"""B-1420: View 4 capital card - free cash (Kotak sizing capital) vs capital tied in open real positions."""
import time
from contextlib import closing
from pathlib import Path

import pytest

import main


@pytest.fixture(autouse=True)
def _no_network_prices(monkeypatch):
    monkeypatch.setattr(main, "_open_positions_prices", lambda syms, wl, budget_s=None: {})
    monkeypatch.setitem(main._real_capital_cache, "value", 9644.78)


def _seed():
    main.init_db()
    with closing(main.get_db()) as c:
        for t in ("real_positions", "real_positions_short", "real_positions_swing", "real_positions_swing_short",
                  "signal_state", "signal_state_short", "signal_state_swing", "real_order_events"):
            c.execute(f"DELETE FROM {t}")
        now = time.time()
        c.execute("INSERT INTO real_positions (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, strategy) "
                  "VALUES ('AAA.NS','AAA-EQ',5,100,'E1',?,'2026-10-29','S1',96,'orb-universal-score')", (now,))
        c.execute("INSERT INTO real_positions_short (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, sl_order_id, sl_trigger_price, strategy) "
                  "VALUES ('CCC.NS','CCC-EQ',2,50,'E3',?,'2026-10-29','S3',52,'range_short_staged_ladder')", (now,))
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, entry_order_id, opened_at, day, stop_loss, sl_order_id, sl_trigger_price, strategy) "
                  "VALUES ('BBB.NS','BBB-EQ',3,200,'E2',?,'2026-10-27',190,'S2',190,'gap_and_go')", (now,))
        c.commit()


def test_capital_split_math():
    _seed()
    cap = main.real_positions_sl_today()["capital"]
    tied = 5 * 100 + 2 * 50 + 3 * 200  # 1200
    assert cap["tied_inr"] == tied and cap["open_positions"] == 3
    assert cap["free_cash_inr"] == 9644.78
    assert cap["total_inr"] == round(9644.78 + tied, 2)
    assert cap["tied_pct"] == round(100 * tied / (9644.78 + tied), 2)
    assert cap["free_cash_source"] == "kotak_neo_real_account"


def test_capital_split_free_cash_not_fetched(monkeypatch):
    monkeypatch.setitem(main._real_capital_cache, "value", None)
    cap = main._capital_split([{"entry_price": 10, "qty": 4}, {"entry_price": None, "qty": 1}])
    assert cap["tied_inr"] == 40 and cap["free_cash_inr"] is None
    assert cap["total_inr"] is None and cap["tied_pct"] is None and cap["free_cash_source"] == "not_yet_fetched"


def test_capital_split_no_positions():
    cap = main._capital_split([])
    assert (cap["tied_inr"], cap["total_inr"], cap["tied_pct"]) == (0.0, 9644.78, 0.0)


def test_view4_has_capital_card():
    h = (Path(main.__file__).parent / "static" / "trade-view4.html").read_text()
    assert 'id="capBox"' in h and 'id="capLine"' in h
    assert "d.capital" in h and "tied_pct" in h and "free_cash_inr" in h
