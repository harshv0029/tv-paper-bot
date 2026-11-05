"""B-1481 (live 2026-11-05): Kotak's empty start-of-day order book must not block the 09:15 IST SL placement."""
import datetime as dt

import kotak_real_orders as kro
import main
from tests.test_sl_unreadable_book_b1462 import _setup

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def test_empty_book_reply_is_empty_list():
    assert kro.order_rows_from_report({"stat": "Not_Ok", "errMsg": "No Data", "stCode": 5203}) == []
    assert kro.order_rows_from_report({"stCode": 5203}) == []
    assert kro.order_rows_from_report({"emsg": "No orders found"}) == []
    assert kro.order_rows_from_report({"data": []}) == []


def test_genuine_error_stays_unreadable():
    assert kro.order_rows_from_report({"stat": "Not_Ok"}) is None
    assert kro.order_rows_from_report(None) is None
    assert kro.order_rows_from_report({"errMsg": "session expired"}) is None


def test_empty_book_places_even_when_periodic(monkeypatch):
    c, placed = _setup(monkeypatch, [{"stat": "Not_Ok", "errMsg": "No Data", "stCode": 5203}])
    r = kro.ensure_resting_sl("BANKINDIA-EQ", 8, 126.73, allow_unchecked=False)
    assert r["ok"] and placed == [("BANKINDIA-EQ", 8, 126.73)] and c.calls == 1


def test_open_protect_window():
    thu = dt.datetime(2026, 11, 5, tzinfo=IST)
    assert not main._in_open_protect_window(thu.replace(hour=9, minute=14, second=59))
    assert main._in_open_protect_window(thu.replace(hour=9, minute=15))
    assert main._in_open_protect_window(thu.replace(hour=9, minute=29, second=59))
    assert not main._in_open_protect_window(thu.replace(hour=9, minute=30))
    assert not main._in_open_protect_window(dt.datetime(2026, 11, 7, 9, 20, tzinfo=IST))  # Saturday


def test_open_protect_place_proceeds_on_unreadable_book(monkeypatch):
    monkeypatch.setattr(main.kotak_neo if hasattr(main, "kotak_neo") else __import__("kotak_neo"),
                        "order_report", lambda *a, **k: {"stat": "Not_Ok"})
    seen = {}
    monkeypatch.setattr(main, "_open_protect_pending", lambda plan, rows: seen.setdefault("rows", rows) and [] or [])
    out = main._open_protect_place({"holdings": {}, "rows": []})
    assert seen["rows"] == [] and out.get("error") != "order_report unreadable"
