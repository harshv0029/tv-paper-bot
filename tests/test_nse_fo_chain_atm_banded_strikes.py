"""Unit tests for select_atm_banded_option_strikes (nse_fo_chain.py,
2026-09-16, explicit user instruction: ATM +/- 15 strikes per expiry,
not every listed strike - a live-confirmed capacity fit against Kotak's
WebSocket subscription cap, see DEFAULT_ATM_STRIKE_BAND's own comment).
Mocks kotak_neo.search_scrip with a wide synthetic strike ladder to
exercise the banding/clamping logic precisely.

Run: pytest tests/ -v
"""
import datetime as dt
from unittest.mock import patch

import nse_fo_chain


def _row(pSymbolName, pTrdSymbol, pOptionType, dStrikePrice, pExpiryDate, pSymbol):
    return {
        "pSymbol": pSymbol, "pSymbolName": pSymbolName, "pTrdSymbol": pTrdSymbol,
        "pOptionType": pOptionType, "dStrikePrice;": dStrikePrice,
        "pExpiryDate": pExpiryDate, "pInstType": "IO", "lLotSize": 50,
    }


_TODAY = dt.date.today()
_TARGET_MONTH_INDEX = _TODAY.year * 12 + (_TODAY.month - 1) + 2
_TARGET_YEAR, _TARGET_MONTH = divmod(_TARGET_MONTH_INDEX, 12)
_TARGET_MONTH += 1
_EXPIRY = dt.date(_TARGET_YEAR, _TARGET_MONTH, 5)
_EXPIRY_STR = _EXPIRY.strftime("%d%b%Y")
_EXPIRY_ISO = _EXPIRY.strftime("%Y-%m-%d")

# A wide, evenly-spaced synthetic ladder: strikes 24000..24980 step 20
# (50 strikes), spot placed near the middle so both sides of the band
# have plenty of room, matching a real liquid index chain's shape.
_STRIKES = list(range(2400000, 2498000 + 1, 2000))  # raw dStrikePrice; values
_FIXTURE_ROWS = [
    _row("NIFTY", f"NIFTY{i}CE", "ce", strike, _EXPIRY_STR, pSymbol=1000 + i)
    for i, strike in enumerate(_STRIKES)
]
_SPOT = 24500.0  # lands exactly on one of the synthetic strikes (24500.00)


def test_band_returns_31_strikes_for_band_15_with_plenty_of_room():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, err = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", _SPOT, "call", "monthly", band=15)
    assert err is None
    assert len(band) == 31  # 15 below + ATM + 15 above


def test_band_is_centered_on_the_true_atm_strike():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, _ = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", _SPOT, "call", "monthly", band=15)
    strikes = [c["strike"] for c in band]
    atm = min(strikes, key=lambda s: abs(s - _SPOT))
    assert atm == _SPOT
    idx = strikes.index(atm)
    assert idx == 15  # exactly 15 strikes below it in the returned band


def test_band_picks_nearest_strike_when_spot_is_between_two_strikes():
    off_spot = 24510.0  # between 24500 and 24520, closer to 24500
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, err = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", off_spot, "call", "monthly", band=15)
    assert err is None
    strikes = [c["strike"] for c in band]
    assert 24500.0 in strikes
    assert len(band) == 31


def test_band_clamps_at_the_low_end_of_a_short_chain():
    # Spot sits near the very bottom of the ladder - fewer than 15 strikes
    # exist below it, band must clamp rather than error or wrap.
    low_spot = float(_STRIKES[2]) / 100.0  # 3rd strike from the bottom
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, err = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", low_spot, "call", "monthly", band=15)
    assert err is None
    strikes = [c["strike"] for c in band]
    assert strikes[0] == float(_STRIKES[0]) / 100.0  # can't go below the first real strike
    assert len(band) == 2 + 1 + 15  # 2 below (clamped) + ATM + 15 above


def test_band_clamps_at_the_high_end_of_a_short_chain():
    high_spot = float(_STRIKES[-3]) / 100.0  # 3rd strike from the top
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, err = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", high_spot, "call", "monthly", band=15)
    assert err is None
    strikes = [c["strike"] for c in band]
    assert strikes[-1] == float(_STRIKES[-1]) / 100.0
    assert len(band) == 15 + 1 + 2


def test_band_covers_the_entire_chain_when_band_exceeds_chain_width():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, err = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", _SPOT, "call", "monthly", band=10000)
    assert err is None
    assert len(band) == len(_STRIKES)


def test_band_rejects_non_positive_band_size():
    band, err = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", _SPOT, "call", "monthly", band=0)
    assert band is None
    assert "invalid_band" in err


def test_band_propagates_underlying_resolution_errors():
    band, err = nse_fo_chain.select_atm_banded_option_strikes("UNKNOWNIDX", _SPOT, "call", "monthly")
    assert band is None
    assert "no_segment_mapping_for" in err


def test_band_result_is_sorted_ascending_by_strike():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, _ = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", _SPOT, "call", "monthly", band=15)
    strikes = [c["strike"] for c in band]
    assert strikes == sorted(strikes)


def test_band_uses_default_band_of_15_when_unspecified():
    with patch("nse_fo_chain.kotak_neo.search_scrip", return_value=_FIXTURE_ROWS):
        band, _ = nse_fo_chain.select_atm_banded_option_strikes("NIFTY", _SPOT, "call", "monthly")
    assert len(band) == 31
    assert nse_fo_chain.DEFAULT_ATM_STRIKE_BAND == 15
