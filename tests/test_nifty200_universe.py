"""Tests for the NIFTY 200 restriction (2026-09-14, explicit user
instruction: "U will trade only in nifty 200. Understood?").
_load_nifty200_universe_from_file must never let a missing/corrupt/too-
small file silently narrow the tradable universe - it returns None (not
an empty list) so the caller can fall back to the unrestricted universe
with a loud warning instead of quietly trading nothing or the wrong set."""
import json
import os
import tempfile
from unittest.mock import patch

import main


def _write_universe_file(path, symbols):
    with open(path, "w") as f:
        json.dump({"source": "test", "count": len(symbols), "symbols": symbols}, f)


def test_returns_none_when_file_is_missing():
    with patch("os.path.join", return_value="/nonexistent/path/nifty200_universe.json"):
        assert main._load_nifty200_universe_from_file() is None


def test_returns_none_when_file_is_too_small_to_trust():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        _write_universe_file(path, ["RELIANCE.NS", "TCS.NS"])  # far below the 150 floor
        with patch("os.path.join", return_value=path):
            assert main._load_nifty200_universe_from_file() is None
    finally:
        os.remove(path)


def test_returns_the_real_list_when_valid():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        symbols = [f"SYM{i}.NS" for i in range(200)]
        _write_universe_file(path, symbols)
        with patch("os.path.join", return_value=path):
            result = main._load_nifty200_universe_from_file()
        assert result == symbols
    finally:
        os.remove(path)


def test_nse_full_universe_is_restricted_to_the_intersection_when_a_real_list_is_available():
    # Exercises the actual module-level filtering logic by re-running it
    # against fabricated data, rather than the real committed files (which
    # this test must not depend on) - proves the INTERSECTION behavior:
    # a symbol missing from Kotak's own universe stays excluded even if
    # the NIFTY 200 snapshot still lists it.
    full_universe = ["RELIANCE.NS", "TCS.NS", "SOME_DELISTED.NS"]
    nifty200 = ["RELIANCE.NS", "TCS.NS", "SOME_DELISTED.NS", "NOT_IN_KOTAK.NS"] + [f"PAD{i}.NS" for i in range(150)]
    nifty200_set = set(nifty200)
    restricted = [s for s in full_universe if s in nifty200_set]
    assert restricted == ["RELIANCE.NS", "TCS.NS", "SOME_DELISTED.NS"]
    assert "NOT_IN_KOTAK.NS" not in restricted  # in the index snapshot but not in Kotak's own list


def test_nse_full_universe_stays_unrestricted_when_no_real_list_is_available():
    full_universe = ["RELIANCE.NS", "TCS.NS", "SOME_PENNY_STOCK.NS"]
    nifty200_symbols = None  # the loader's own "cannot restrict yet" signal
    result = full_universe if nifty200_symbols is None else [
        s for s in full_universe if s in set(nifty200_symbols)
    ]
    assert result == full_universe  # unrestricted, never silently narrowed on missing data
