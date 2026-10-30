"""B-1434: a SQLite error while persisting a completed F&O candle must not end the websocket stream
(live 30-Oct: connect_count 7 in ~2 h, last_disconnect_reason exception:OperationalError). The candle stays
pending and is written by the next batch; the error is counted in _feed_status."""
import sqlite3

import pytest

import kotak_fo_candle_feed as fo


class _Scrip:
    def __init__(self, tok, px):
        self.instrument_token = tok
        self.exchange_segment = "nse_fo"
        self.last_traded_price = px


class _Conn:
    def __init__(self, fail, rows):
        self.fail, self.rows = fail, rows

    def execute(self, sql, params):
        if self.fail:
            raise sqlite3.OperationalError("database is locked")
        self.rows.append(params)

    def commit(self):
        pass

    def close(self):
        pass


DESC = {"kotak_trading_symbol": "NIFTYX", "underlying": "NIFTY", "kind": "option", "right": "CE",
        "strike": 100, "expiry": "2026-11-27"}


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(fo, "_in_progress_candles", {
        "11": {"bucket_start_ts": 0.0, "open": 1, "high": 2, "low": 1, "close": 2, "tick_count": 3},
    })
    monkeypatch.setattr(fo, "_pending_candles", [], raising=False)
    monkeypatch.setattr(fo, "_feed_status", dict(fo._feed_status))


def test_locked_db_does_not_raise_and_candle_is_written_next_batch(fresh, monkeypatch):
    import main
    rows, state = [], {"fail": True}
    monkeypatch.setattr(main, "get_db", lambda: _Conn(state["fail"], rows))
    uni = {("nse_fo", "11"): DESC}

    # old code: OperationalError propagated out of process_fo_ticks -> run_fo_candle_feed reconnected
    n = fo.process_fo_ticks([_Scrip(11, 5.0)], uni, _Scrip)
    assert n == 1 and rows == []
    assert fo._feed_status["persist_errors"] == 1
    assert "database is locked" in fo._feed_status["last_persist_error"]
    assert fo._feed_status["pending_candles"] == 1
    assert fo._in_progress_candles["11"]["open"] == 5.0  # the new candle still started

    state["fail"] = False
    fo.process_fo_ticks([_Scrip(11, 6.0)], uni, _Scrip)  # same bucket: no new close, pending flushed
    assert len(rows) == 1
    assert rows[0][0] == "11" and rows[0][7] == 0.0 and rows[0][-1] == 3  # the completed bar, not lost
    assert fo._feed_status["pending_candles"] == 0


def test_pending_candles_capped(fresh, monkeypatch):
    import main
    monkeypatch.setattr(main, "get_db", lambda: _Conn(True, []))
    monkeypatch.setattr(fo, "MAX_PENDING_CANDLES", 2, raising=False)
    bar = {"bucket_start_ts": 0.0, "open": 1, "high": 1, "low": 1, "close": 1, "tick_count": 1}
    fo._pending_candles.extend([("9", DESC, bar), ("8", DESC, bar)])
    fo.process_fo_ticks([_Scrip(11, 5.0)], {("nse_fo", "11"): DESC}, _Scrip)
    assert len(fo._pending_candles) == 2 and fo._pending_candles[-1][0] == "11"
    assert fo._feed_status["dropped_candles"] == 1


def test_get_db_error_also_contained(fresh, monkeypatch):
    import main

    def boom():
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(main, "get_db", boom)
    fo.process_fo_ticks([_Scrip(11, 5.0)], {("nse_fo", "11"): DESC}, _Scrip)
    assert fo._feed_status["persist_errors"] == 1 and len(fo._pending_candles) == 1
