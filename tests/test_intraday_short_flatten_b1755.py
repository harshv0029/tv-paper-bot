"""B-1755 (user 2026-11-27 "Yes": close intraday shorts before 15:00 IST). Kotak auto-squared-off MIS shorts at
15:05:21 IST on 27-Nov; intraday shorts now stop new real entries at 14:45 and flatten from 14:50 IST."""
import datetime as dt
import time

import main
import pytest
from tests.test_news_trades_b1541 import BAD2, _agg, _conn

SHORT_TAG = main.NEWS_TRADE_TAGS["short"]


def _ist_ts(h, m):  # 27-Nov-2026 at h:m IST as epoch
    return dt.datetime(2026, 11, 27, h, m, tzinfo=dt.timezone(dt.timedelta(minutes=330))).timestamp()


def test_short_windows_end_before_kotak_squareoff_and_longs_unchanged():
    assert main.INTRADAY_SHORT_ENTRY_CUTOFF_MIN == 14 * 60 + 45
    assert main.CHAN_SHORT_ENTRY_CUTOFF_MIN < main.CHAN_SHORT_FLATTEN_START_MIN == 14 * 60 + 50
    assert main.CHAN_SHORT_FLATTEN_END_MIN == 15 * 60  # flat before Kotak's ~15:05 MIS square-off
    assert main.NEWS_SHORT_ENTRY_CUTOFF_MIN < main.INTRADAY_SHORT_SQUAREOFF_MIN
    assert (main.CHAN_LONG_ENTRY_CUTOFF_MIN, main.CHAN_LONG_FLATTEN_START_MIN, main.CHAN_LONG_FLATTEN_END_MIN) == (
        15 * 60, 15 * 60 + 10, 15 * 60 + 15)


def test_generic_short_engine_squareoff_capped_for_nse_only():
    f = main._intraday_short_squareoff_min
    assert f("SBIN.NS", main.IST_OFFSET_MIN, 914) == 14 * 60 + 50
    assert f("SBIN.NS", main.IST_OFFSET_MIN, 800) == 800  # an earlier config is kept
    assert f("BTC-USD", 0, 1439) == 1439
    src = open("main.py").read()
    assert 'squareoff_min=_intraday_short_squareoff_min(cfg["symbol"], cfg["tz_offset_min"], cfg["squareoff_min"])' in src


@pytest.mark.parametrize("hm, blocked", [((14, 44), False), ((14, 45), True), ((14, 58), True)])
def test_real_short_entry_cutoff_1445(monkeypatch, hm, blocked):
    seen = []
    monkeypatch.setattr(main, "is_real_trading_enabled", lambda c: True)
    monkeypatch.setattr(main, "_asset_class_and_source", lambda s: ("nse_equity", None, None))
    monkeypatch.setattr(main, "ist_now", lambda: dt.datetime(2026, 11, 27, *hm))
    monkeypatch.setattr(main, "_log_real_attempt", lambda c, s, side, status, **k: seen.append(status))

    class _Stop(Exception):
        pass

    def _etf(sym):
        raise _Stop  # the next gate: reaching it means the cutoff let the entry through
    monkeypatch.setattr(main, "_etf_entry_range_ok", _etf)
    if blocked:
        main._maybe_place_real_short_entry(None, "SBIN.NS")
        assert seen == ["skipped_after_entry_cutoff"]
    else:
        with pytest.raises(_Stop):
            main._maybe_place_real_short_entry(None, "SBIN.NS")
        assert seen == []


def _seed_short(c, opened):
    c.execute("INSERT INTO news_trades (symbol, direction, tag, opened_ts, entry_price, stop_price, open_reason, publishers_n) "
              "VALUES ('XYZ.NS', 'short', ?, ?, 100.0, 103.0, 'downgrade confirmed by a, b', 2)", (SHORT_TAG, opened))


@pytest.fixture
def _in_session(monkeypatch):
    monkeypatch.setattr(main, "_news_opened_outside_session", lambda ts: False)
    monkeypatch.setattr(main, "_news_late_entry_ok", lambda *a, **k: True)


def test_news_short_flattened_from_1450(_in_session):
    c = _conn()
    _seed_short(c, _ist_ts(11, 0))
    acts = main._news_trades_step(c, "XYZ.NS", _agg(BAD2), _ist_ts(14, 51), 99.0)
    assert ("XYZ.NS", "short", "close") in acts
    r = c.execute("SELECT status, close_reason FROM news_trades WHERE direction = 'short'").fetchone()
    assert r["status"] == "closed" and "B-1755" in r["close_reason"]


def test_news_short_kept_before_1450(_in_session):
    c = _conn()
    _seed_short(c, _ist_ts(11, 0))
    acts = main._news_trades_step(c, "XYZ.NS", _agg(BAD2), _ist_ts(14, 40), 99.0)
    assert ("XYZ.NS", "short", "close") not in acts
    assert c.execute("SELECT status FROM news_trades WHERE direction = 'short'").fetchone()["status"] == "open"
