"""B-1551 (user 2026-11-11 IST): a LATE news entry needs the news still fresh AND the stock reacting now."""
import datetime as dt
from unittest.mock import patch

import pandas as pd

import main

STOCK = {"hard_pos": [("upgrade", "t", "livemint")], "top": [{"hard": ["upgrade"], "age_h": 3.0, "score": 0.6}]}


def _df(prev_close, today_open, vol=1_000_000, days=25):
    today = main.ist_now().date()
    idx = [pd.Timestamp(today - dt.timedelta(days=days - i)) for i in range(days)] + [pd.Timestamp(today)]
    rows = [{"Open": prev_close, "High": prev_close, "Low": prev_close, "Close": prev_close, "Volume": vol}] * days
    rows.append({"Open": today_open, "High": today_open, "Low": today_open, "Close": today_open, "Volume": vol})
    return pd.DataFrame(rows, index=idx)


def _run(ltp, prev=700.0, opn=705.0, nifty_prev=25000.0, nifty=25000.0, vol_today=2_000_000, stock=STOCK,
         hhmm=(12, 0)):
    frames = {"LENSKART.NS": _df(prev, opn), "^NSEI": _df(nifty_prev, nifty_prev)}
    ticks = {"LENSKART.NS": {"ltp": ltp, "volume_traded_today": vol_today}, "^NSEI": {"ltp": nifty}}
    now = dt.datetime.combine(main.ist_now().date(), dt.time(*hhmm))
    with patch.object(main, "fetch_ohlc", side_effect=lambda s, p, i: frames[s]), \
            patch("kotak_live_feed.get_live_ticks", return_value=ticks), patch.object(main, "ist_now", return_value=now):
        return main._news_market_reacting("LENSKART.NS", "long", ltp, stock)


def test_reacting_stock_passes():
    ok, why = _run(712.0)
    assert ok, why


def test_flat_stock_is_held_back():
    ok, why = _run(701.0)
    assert not ok and "not reacting" in why


def test_market_wide_move_is_not_the_news():
    ok, why = _run(712.0, nifty=25400.0)
    assert not ok and "market, not the news" in why


def test_fading_reaction_is_held_back():
    ok, why = _run(708.0, opn=715.0)
    assert not ok and "fading" in why


def test_thin_volume_is_held_back():
    ok, why = _run(712.0, vol_today=100_000)
    assert not ok and "volume" in why


def test_stale_news_is_held_back():
    old = {"hard_pos": STOCK["hard_pos"], "top": [{"hard": ["upgrade"], "age_h": 30.0, "score": 0.6}]}
    ok, why = _run(712.0, stock=old)
    assert not ok and "stale" in why


def test_missing_data_fails_closed():
    with patch.object(main, "fetch_ohlc", side_effect=RuntimeError("yahoo down")):
        ok, why = main._news_market_reacting("LENSKART.NS", "long", 712.0, STOCK)
    assert not ok and "failed" in why
