"""B-1554: when yfinance cannot give a reference close, the SL band retry uses the band Kotak states in its own
"Circuit breach" rejection (live 2026-11-10 IST: UNIONBANK/BANKINDIA/BIOCON resent the same doomed stop all day)."""
import pytest

import kotak_real_orders as k

REJ = ("order 1 rejected: RMS:Rule: Check circuit limit including square off order exceeds : Circuit breach, "
       "Order Price :168.80,  Low Price Range:177.30 High Price Range:216.70  for entity account-X")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    k._KOTAK_BAND_CACHE.clear()
    k._BAND_REF_CACHE.clear()
    monkeypatch.setattr(k, "_reference_prices", lambda s: (None, None))   # yfinance down, as on Render
    monkeypatch.setattr(k, "apply_entry_day_floor", lambda s, t, side: (t, {}))
    monkeypatch.setattr(k, "_tick_size_for", lambda s: 0.05)
    yield
    k._KOTAK_BAND_CACHE.clear()


def _once_factory(calls, low=177.30, high=216.70):
    def once(sym, qty, trig, *rest):
        calls.append(trig)
        if trig < low or trig > high:
            return {"ok": False, "detail": REJ}
        return {"ok": True, "order_id": "9", "trigger_price": trig}
    return once


def test_long_retry_uses_kotak_band_when_yfinance_is_down(monkeypatch):
    calls = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once", _once_factory(calls))
    monkeypatch.setattr(k, "_LTP_PROVIDER", lambda s: 195.0)
    r = k.place_real_stop_loss("UNIONBANK-EQ", 1, 168.80)
    assert r["ok"] and r["band_source"] == "kotak_rejection" and r["band_clamped_from"] == 168.80
    assert 177.30 < calls[-1] < 195.0 * 0.995 and len(calls) == 2


def test_cached_band_preclamps_the_next_send(monkeypatch):
    calls = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once", _once_factory(calls))
    monkeypatch.setattr(k, "_LTP_PROVIDER", lambda s: 195.0)
    k.place_real_stop_loss("UNIONBANK-EQ", 1, 168.80)
    calls.clear()
    r = k.place_real_stop_loss("UNIONBANK-EQ", 1, 168.80)   # next tick: no doomed first send
    assert r["ok"] and len(calls) == 1 and calls[0] > 177.30


def test_no_ltp_leaves_the_stop_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once", _once_factory(calls))
    monkeypatch.setattr(k, "_LTP_PROVIDER", None)
    r = k.place_real_stop_loss("UNIONBANK-EQ", 1, 168.80)
    assert not r["ok"] and calls == [168.80]


def test_band_floor_at_or_above_market_is_not_used(monkeypatch):
    calls = []
    monkeypatch.setattr(k, "_place_real_stop_loss_once", _once_factory(calls))
    monkeypatch.setattr(k, "_LTP_PROVIDER", lambda s: 178.0)   # near the lower circuit: floor would sell at once
    r = k.place_real_stop_loss("UNIONBANK-EQ", 1, 168.80)
    assert not r["ok"] and calls == [168.80]


def test_band_cache_expires_with_the_ist_day(monkeypatch):
    k._KOTAK_BAND_CACHE["UNIONBANK-EQ"] = ("2000-01-01", 177.30, 216.70)
    assert k._kotak_band("UNIONBANK-EQ") is None


def test_short_retry_uses_kotak_band(monkeypatch):
    calls = []
    monkeypatch.setattr(k, "_place_real_short_stop_loss_once", _once_factory(calls))
    monkeypatch.setattr(k, "_LTP_PROVIDER", lambda s: 200.0)
    r = k.place_real_short_stop_loss("UNIONBANK-EQ", 1, 230.0)
    assert r["ok"] and r["band_source"] == "kotak_rejection"
    assert 200.0 * 1.005 < calls[-1] < 216.70
