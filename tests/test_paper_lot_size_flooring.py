"""Tests for paper-side lot-size flooring on index/commodity WATCHLIST
symbols (2026-09-21, explicit user instruction: "stop paper to do trading
in fraction if exchange does not allow. Paper trading should mimic all
conditions of exchange trading" - lot-size source explicitly chosen as
"fetch live from Kotak", not a hardcoded constant). Reuses the bullish-
engulfing entry fixture from test_round_trip_cost_gate.py (a simple,
exactly-specifiable two-candle trigger) since it's asset-class agnostic."""
import datetime as real_datetime
import os
import tempfile
from unittest.mock import patch

import pandas as pd

import main


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    return path


class _FixedUtcNow(real_datetime.datetime):
    _fixed = real_datetime.datetime(2026, 9, 9, 5, 45, 0)  # UTC -> 11:15 IST, mid-session

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _bullish_engulfing_fixture():
    # Same fixture as test_round_trip_cost_gate.py's own copy - see that
    # file's docstring for why bullish_engulfing over orb_breakout.
    base = pd.Timestamp("2026-09-09 03:45:00")  # UTC -> 09:15 IST
    rows = []
    for i in range(23):
        c = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        rows.append({
            "Date": base + pd.Timedelta(minutes=5 * i), "Open": c, "High": c + 0.1,
            "Low": c - 0.1, "Close": c, "Volume": 1000,
        })
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 23), "Open": 101.0, "High": 101.1,
        "Low": 99.6, "Close": 99.7, "Volume": 1000,
    })
    rows.append({
        "Date": base + pd.Timedelta(minutes=5 * 24), "Open": 99.5, "High": 101.6,
        "Low": 99.4, "Close": 101.5, "Volume": 3000,
    })
    return pd.DataFrame(rows)


def _run(symbol, future_result):
    _fresh_db()
    fixture = _bullish_engulfing_fixture()
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=fixture), \
         patch("nse_fo_chain.select_nse_future", return_value=future_result):
        return main._auto_signal_core(
            symbol, currency="INR", strategy="bullish_engulfing",
            trend_sma=0, rr=10.0,
        )


def test_gold_entry_qty_floors_to_a_whole_lot():
    result = _run("GC=F", ({"lot_size": 10, "underlying": "GOLDM"}, None))
    assert result["action_taken"] == "entered_long"
    assert result["entry"]["qty"] % 10 == 0
    assert result["entry"]["qty"] > 0


def test_nifty_entry_qty_floors_to_a_whole_lot():
    result = _run("^NSEI", ({"lot_size": 75, "underlying": "NIFTY"}, None))
    assert result["action_taken"] == "entered_long"
    assert result["entry"]["qty"] % 75 == 0
    assert result["entry"]["qty"] > 0


def test_sensex_uses_the_bare_sensex_underlying_key():
    # ^BSESN has no real-order mirror (_INDEX_TO_FO_UNDERLYING doesn't
    # cover it) but must still floor to SENSEX's own real lot size via
    # nse_fo_chain, not fall through to fractional sizing.
    with patch("main.dt.datetime", _FixedUtcNow), \
         patch("main.fetch_ohlc", return_value=_bullish_engulfing_fixture()) as mock_fetch, \
         patch("nse_fo_chain.select_nse_future") as mock_future:
        mock_future.return_value = ({"lot_size": 20, "underlying": "SENSEX"}, None)
        _fresh_db()
        result = main._auto_signal_core(
            "^BSESN", currency="INR", strategy="bullish_engulfing", trend_sma=0, rr=10.0,
        )
    mock_future.assert_called_once_with("SENSEX")
    assert result["action_taken"] == "entered_long"
    assert result["entry"]["qty"] % 20 == 0


def test_lot_size_resolution_failure_skips_the_entry_not_fractional_fallback():
    result = _run("GC=F", (None, "no_future_rows"))
    assert result["action_taken"] == "skipped_no_lot_size"
    assert result["detail"] == "no_future_rows"


def test_equity_symbol_is_unaffected_still_floors_to_whole_shares():
    # Sanity check this change doesn't touch the pre-existing nse_equity path.
    result = _run("TESTSTOCK.NS", ({"lot_size": 999, "underlying": "SHOULD_NOT_BE_CALLED"}, None))
    assert result["action_taken"] == "entered_long"
    assert result["entry"]["qty"] == float(int(result["entry"]["qty"]))
