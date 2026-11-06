"""B-1509 (user 2026-11-06 IST): 1-share real floor, three reject flags, daily no-entry record."""
import datetime as dt
import os
import tempfile
from contextlib import closing

import pytest

import main


@pytest.fixture
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", path)
    main.init_db()
    yield path
    os.unlink(path)


def test_one_share_floor_when_stop_loss_fits_1pct_of_free_net():
    # Net Rs5,904 -> limit Rs59.05 at the stop; usable tranche Rs2,952
    assert main._real_one_share_floor(0, 5904.53, 300.0, 45.0, 2952.0) == 1
    assert main._real_one_share_floor(0, 5904.53, 300.0, 60.0, 2952.0) == 0     # stop loss Rs60 > Rs59
    assert main._real_one_share_floor(0, 5904.53, 3500.0, 40.0, 2952.0) == 0    # one share not affordable
    assert main._real_one_share_floor(3, 5904.53, 300.0, 45.0, 2952.0) == 3     # formula already gives shares
    assert main._real_one_share_floor(0, 0.0, 300.0, 1.0, 0.0) == 0


def test_real_swing_risk_qty_uses_the_floor(monkeypatch):
    monkeypatch.setattr(main, "_refresh_real_capital_cache", lambda: None)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: 5904.53)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: False)
    assert main._real_swing_qty_by_risk(None, "ZZTEST.NS", 300.0, 255.0) == 1
    assert main._real_swing_qty_by_risk(None, "ZZTEST.NS", 300.0, 230.0) == 0   # Rs70 stop loss > 1% of Net


def test_reject_flag_classes():
    assert main._entry_reject_flag("skipped_strategy_not_viable") == "viability"
    assert main._entry_reject_flag("skipped_low_balance") == "money"
    assert main._entry_reject_flag("skipped_insufficient_real_qty") == "money"
    assert main._entry_reject_flag("skipped_sector_cap") == "other"
    assert main._entry_reject_flag("skipped_after_entry_cutoff") == "other"


def test_entry_funnel_reports_reject_flags(db):
    with closing(main.get_db()) as c:
        day = main.ist_now().strftime("%Y-%m-%d")
        for st in ("skipped_sector_cap", "skipped_low_balance", "skipped_strategy_not_viable"):
            c.execute("INSERT INTO real_trades (ts, day, symbol, side, status, strategy) VALUES (?, ?, 'Y.NS', 'B', ?, 'x')",
                      (main.time.time(), day, st))
        c.commit()
    fl = main.entry_funnel()["categories"]["buy"]["reject_flags"]
    assert fl["viability"] >= 1 and fl["money"] == 1 and fl["other"] == 1


def test_no_entry_day_logged_once_after_close(db, monkeypatch):
    monkeypatch.setattr(main, "_no_entry_day_checked", "")
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: True)
    t = dt.datetime(2026, 11, 6, 15, 40)
    with closing(main.get_db()) as c:
        assert main._no_entry_day_check(c, now=dt.datetime(2026, 11, 6, 15, 20)) is None   # before 15:35
        assert main._no_entry_day_check(c, now=t) is not None
        monkeypatch.setattr(main, "_no_entry_day_checked", "")   # simulated restart: the DB row stops a repeat
        assert main._no_entry_day_check(c, now=t) is None
        assert c.execute("SELECT COUNT(*) FROM real_order_events WHERE event='no_entry_day'").fetchone()[0] == 1


def test_no_entry_day_silent_when_an_entry_confirmed(db, monkeypatch):
    monkeypatch.setattr(main, "_no_entry_day_checked", "")
    monkeypatch.setattr(main, "is_nse_trading_day", lambda d=None: True)
    with closing(main.get_db()) as c:
        main._log_real_order_event(c, "A.NS", "entry", "confirmed", reason="test")
        assert main._no_entry_day_check(c, now=dt.datetime(2026, 11, 6, 15, 40)) is None
