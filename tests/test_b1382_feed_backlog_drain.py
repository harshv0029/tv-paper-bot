"""B-1382: Kotak feed consumers drain the SDK's unbounded queue per wake-up and the F&O candle feed opens the DB only
when a tick closes a candle (2026-10-27 OOM: ~240k SFeedScrip queued)."""
import asyncio

import kotak_fo_candle_feed as fo
import kotak_live_feed as lf


class _WS:
    def __init__(self, items):
        self._message_queue = asyncio.Queue()
        for i in items:
            self._message_queue.put_nowait(i)


class _Scrip:
    def __init__(self, tok, ltp, seg="nse_fo"):
        self.instrument_token, self.last_traded_price, self.exchange_segment = tok, ltp, seg


def test_drain_pending_takes_everything_queued():
    ws = _WS([2, 3, 4])
    assert lf.drain_pending(ws, 1) == [1, 2, 3, 4]
    assert ws._message_queue.qsize() == 0


def test_drain_pending_without_queue_returns_first_only():
    assert lf.drain_pending(object(), "x") == ["x"]


def test_process_fo_ticks_no_db_within_one_candle(monkeypatch):
    import main
    opened = []
    monkeypatch.setattr(main, "get_db", lambda: opened.append(1))
    monkeypatch.setattr(fo, "_in_progress_candles", {})
    uni = {("nse_fo", "11"): {"kotak_trading_symbol": "X"}}
    n = fo.process_fo_ticks([_Scrip(11, 10.0), _Scrip(11, 12.0), _Scrip(11, 9.0), "other"], uni, _Scrip)
    assert n == 3 and opened == []
    bar = fo._in_progress_candles["11"]
    assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["tick_count"]) == (10.0, 12.0, 9.0, 9.0, 3)


def test_process_fo_ticks_opens_db_once_when_candle_closes(monkeypatch):
    import main

    class _Conn:
        closed = 0

        def close(self):
            _Conn.closed += 1
    opened, persisted = [], []
    monkeypatch.setattr(main, "get_db", lambda: opened.append(1) or _Conn())
    monkeypatch.setattr(fo, "_persist_candle", lambda conn, tok, d, bar: persisted.append(tok))
    monkeypatch.setattr(fo, "_in_progress_candles", {
        "11": {"bucket_start_ts": 0.0, "open": 1, "high": 1, "low": 1, "close": 1, "tick_count": 1},
        "12": {"bucket_start_ts": 0.0, "open": 1, "high": 1, "low": 1, "close": 1, "tick_count": 1},
    })
    uni = {("nse_fo", "11"): {}, ("nse_fo", "12"): {}}
    fo.process_fo_ticks([_Scrip(11, 5.0), _Scrip(12, 6.0), _Scrip(11, 7.0)], uni, _Scrip)
    assert opened == [1] and _Conn.closed == 1 and sorted(persisted) == ["11", "12"]
