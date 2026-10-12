"""GET /fo-entry-diagnosis: read-only, no account data, picks a primary blocker."""
import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()


def _get(real_fo=True, viable=True, monitor=None, window=True):
    _fresh_db()
    main._fo_strike_monitor.clear()
    main._fo_strike_monitor.update(monitor or {})
    import datetime as dt
    now = dt.datetime(2026, 10, 12, 11, 0) if window else dt.datetime(2026, 10, 12, 8, 0)
    with patch.object(main, "is_real_fo_trading_enabled", return_value=real_fo), \
         patch.object(main, "_is_strategy_viable_for_real_money", return_value=viable), \
         patch.object(main, "ist_now", return_value=now):
        r = TestClient(main.app).get("/fo-entry-diagnosis")
    main._fo_strike_monitor.clear()
    assert r.status_code == 200
    return r.json()


def test_real_fo_off_is_primary_blocker():
    d = _get(real_fo=False)
    assert d["underlyings"]["NIFTY"]["primary_blocker"] == "real_fo_switch_off"
    assert set(d["underlyings"]) == {"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"}


def test_outside_window():
    assert _get(window=False)["underlyings"]["NIFTY"]["primary_blocker"].startswith("outside_entry_window")


def test_no_viable_tags():
    assert _get(viable=False)["underlyings"]["NIFTY"]["primary_blocker"] == "no_viable_strike_setup_tag"


def test_warming_up_and_counts():
    mon = {"A": {"underlying": "NIFTY", "status": "warming_up_need_30_candles"},
           "B": {"underlying": "NIFTY", "status": "warming_up_need_30_candles"}}
    u = _get(monitor=mon)["underlyings"]["NIFTY"]
    assert u["primary_blocker"] == "all_strikes_warming_up_or_stale_candles"
    assert u["strikes_by_status"] == {"warming_up_need_30_candles": 2}


def test_no_setup_and_no_account_data():
    mon = {"A": {"underlying": "BANKNIFTY", "status": "monitored_no_setup"}}
    d = _get(monitor=mon)
    assert d["underlyings"]["BANKNIFTY"]["primary_blocker"] == "no_setup_fired_on_monitored_strikes"
    txt = str(d).lower()
    assert "capital" not in txt and "balance" not in txt
