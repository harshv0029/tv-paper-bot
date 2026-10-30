"""B-1438: every TRAILING long swing tag re-places its resting SL (after the exchange's 15:15 cancel) at its trailed
strategy stop, never above the last price, never below the old behaviour; non-trailing tags unchanged."""
import os
import tempfile
from contextlib import closing

import pytest

import main

XROC = main.GAP_AND_GO_XROC_LIVE_TAG

# tag -> (initial stop, atr_at_entry, running_max_close, expected trailed level); entry 100
CASES = {
    "minervini_vcp": (90.0, 4.0, 130.0, 130.0 - main.MINERVINI_ATR_STOP_MULT * 4.0),
    "minervini_vcp_livermore": (90.0, 4.0, 130.0, 130.0 - main.MINERVINI_ATR_STOP_MULT * 4.0),
    "primary_base": (90.0, 4.0, 130.0, 130.0 - main.MINERVINI_ATR_STOP_MULT * 4.0),
    "power_play": (90.0, 4.0, 130.0, 130.0 - main.POWER_PLAY_ATR_STOP_MULT * 4.0),
    "order_block_delta": (90.0, 4.0, 130.0, 130.0 - main.ORDER_BLOCK_ATR_TRAIL_MULT * 4.0),
    "volume_profile_poc": (90.0, 4.0, 130.0, 130.0 - main.VP_ATR_TRAIL_MULT * 4.0),
    main.ORPHAN_SWING_STRATEGY_TAG: (90.0, 4.0, 130.0, 130.0 - main.ORPHAN_SWING_TRAIL_R_MULT * 4.0),
    "minervini_vcp_be3r": (90.0, 4.0, 131.0, 100.0),  # peak gained >= 3R (30) -> breakeven = entry
    XROC: (90.0, 4.0, 130.0, 106.0),
}


@pytest.fixture
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 0.0)
    main._SWING_LAST_CLOSE.clear()
    main._SWING_TRAIL_SKIP_LOGGED.clear()
    with closing(main.get_db()) as conn:
        yield conn
    main._SWING_LAST_CLOSE.clear()


def _row(conn, sym, tag, init, atr, rmc, entry=100.0):
    conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                 "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (sym, tag, "2026-10-01", entry, init, 95.0, 5, 1.0, 1.0, atr, rmc))
    conn.commit()


def test_every_trailing_tag_is_covered():
    for tag in CASES:
        assert main._swing_is_trailing_tag(tag), tag
    for tag in ("gap_and_go", main.BRK20_SWING_TAG, main.SWING_EXITINVAL_VP_TAG, main.SWING_EXITINVAL_OB_TAG,
                main.SECTOR_ROT_TAG, *list(main.PL1D_CELLS)[:1], *list(main.CHAN_SHAPE_CELLS)[:1],
                *list(main.ISLAND_ALL_TAGS)[:1], *list(main.GAPFADE_TAGS)[:1]):
        assert not main._swing_is_trailing_tag(tag), tag


@pytest.mark.parametrize("tag", list(CASES))
def test_replace_uses_trailed_level_per_tag(db, tag):
    init, atr, rmc, want = CASES[tag]
    assert main._swing_strategy_stop_level(tag, init, atr, rmc, entry_price=100.0) == pytest.approx(want)
    _row(db, "T.NS", tag, init, atr, rmc)
    main._SWING_LAST_CLOSE["T.NS"] = 128.0
    assert main._swing_stop_floored(db, "T.NS", init) == pytest.approx(round(max(init, want), 2))
    assert main._swing_exitfamily_trail_floor is main._swing_trail_floor  # B-1427 alias kept


def test_be3r_flat_until_3r_and_without_entry_price():
    assert main._swing_strategy_stop_level("minervini_vcp_be3r", 90.0, 4.0, 129.0, entry_price=100.0) == 90.0
    assert main._swing_strategy_stop_level("minervini_vcp_be3r", 90.0, 4.0, 131.0) == 90.0  # old 4-arg call unchanged


def test_non_trailing_tags_unchanged(db):
    for i, tag in enumerate(("gap_and_go", main.BRK20_SWING_TAG, main.SWING_EXITINVAL_OB_TAG, main.SECTOR_ROT_TAG)):
        _row(db, f"N{i}.NS", tag, 90.0, 4.0, 200.0)
        main._SWING_LAST_CLOSE[f"N{i}.NS"] = 199.0
        assert main._swing_stop_floored(db, f"N{i}.NS", 90.0) == 90.0


def test_never_above_last_close_or_live_price(db, monkeypatch):
    _row(db, "M.NS", "minervini_vcp", 90.0, 4.0, 130.0)
    trail = 130.0 - main.MINERVINI_ATR_STOP_MULT * 4.0
    main._SWING_LAST_CLOSE["M.NS"] = trail - 1.0  # trail >= last close: previous behaviour
    assert main._swing_stop_floored(db, "M.NS", 90.0) == 90.0
    assert main._SWING_TRAIL_SKIP_LOGGED.get("M.NS")
    main._SWING_LAST_CLOSE["M.NS"] = 140.0
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: trail)  # live price at the trail: also refused
    assert main._swing_stop_floored(db, "M.NS", 90.0) == 90.0
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: trail + 5)
    assert main._swing_stop_floored(db, "M.NS", 90.0) == pytest.approx(round(trail, 2))


def test_only_raises_never_lowers(db):
    _row(db, "R.NS", "power_play", 90.0, 4.0, 130.0)
    main._SWING_LAST_CLOSE["R.NS"] = 129.0
    assert main._swing_stop_floored(db, "R.NS", 125.0) == 125.0  # a higher stored stop is kept


def test_missing_data_falls_back(db):
    _row(db, "A.NS", "minervini_vcp", 90.0, None, 130.0)  # no ATR
    _row(db, "B.NS", "minervini_vcp", 90.0, 4.0, None)  # no running max
    _row(db, "C.NS", "minervini_vcp", 90.0, 4.0, 130.0)  # no reference price at all
    main._SWING_LAST_CLOSE["A.NS"] = main._SWING_LAST_CLOSE["B.NS"] = 129.0
    for s in ("A.NS", "B.NS", "C.NS", "NOROW.NS"):
        assert main._swing_stop_floored(db, s, 90.0) == 90.0
    # the B-1427 cell keeps its B-1427 behaviour without a reference price
    _row(db, "X.NS", XROC, 90.0, 4.0, 130.0)
    assert main._swing_stop_floored(db, "X.NS", 90.0) == 106.0


def test_exit_loop_records_last_completed_close():
    src = open(main.__file__).read()
    assert '_SWING_LAST_CLOSE[symbol] = float(df["Close"].iloc[-1])' in src
