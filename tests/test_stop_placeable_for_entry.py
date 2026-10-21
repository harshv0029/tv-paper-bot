"""B-1308: a real buy is skipped when no stop can rest inside the day's price band."""
import kotak_real_orders as kro


def _ref(monkeypatch, prev, last):
    monkeypatch.setattr(kro, "_reference_prices", lambda s: (prev, last))
    monkeypatch.setattr(kro, "_tick_size_for", lambda s: 0.05)


def test_stop_inside_band_ok(monkeypatch):
    _ref(monkeypatch, 100.0, 101.0)
    ok, why = kro.stop_placeable_for_entry("X-EQ", 96.0, 101.0)
    assert ok and "inside" in why


def test_wide_stop_ok_when_band_floor_fits_under_market(monkeypatch):
    _ref(monkeypatch, 238.0, 238.8)  # BANKBARODA-like: stop 15% below
    ok, why = kro.stop_placeable_for_entry("BANKBARODA-EQ", 203.35, 238.81)
    assert ok and "band floor" in why


def test_skipped_when_no_band_floor_fits(monkeypatch):
    _ref(monkeypatch, 100.0, 90.5)  # down ~9.5%: every floor sits at/above the market
    ok, why = kro.stop_placeable_for_entry("X-EQ", 85.0, 90.5)
    assert not ok and "reject" in why


def test_unknown_reference_does_not_block(monkeypatch):
    _ref(monkeypatch, None, None)
    ok, _ = kro.stop_placeable_for_entry("X-EQ", 85.0, 90.5)
    assert ok


def test_entry_paths_call_the_check():
    src = open("main.py").read()
    assert src.count("stop_placeable_for_entry(") == 2
    assert src.count('"skipped_stop_outside_price_band"') == 2
