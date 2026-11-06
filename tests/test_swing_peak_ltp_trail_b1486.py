"""B-1486: peak-LTP trailing stop wired into the live swing stop path for the cells where swing-bandcap-replay.yml run
41978699531 (band_cap=trail) showed it beating the fixed stop. Rule = scripts/swing_bandcap.py trailed_stop "ltp".

Run: pytest tests/test_swing_peak_ltp_trail_b1486.py -v
"""
import os
import sys
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd
import pytest

import main

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import swing_bandcap as bc  # noqa: E402

LONG_TAGS = {
    main.BRK20_SWING_TAG: 0.5,
    main.SWINGMINRR_GATE4_TAG: 1.5,
    "reversal__island_gap05__long__1d__atr1d5_within8__nonovl__v2": 0.5,
    main.GAP_RUNAWAY_TAG: 0.5,
    main.STARC_FULL_TAG: 1.5,
    "oneil_shakeout__plus3__long__1w__atr3_h26_pm1_srcmain__nonovl__v2": 0.5,  # B-1493
}
SHORT_TAG = "brk20_min_rr__main_replay__short__1d__atr4_rr4__v1"


def _df(rows, start="2026-10-01"):
    """rows = [(open, high, low, close)]; one business day each from start (start = entry day)."""
    idx = pd.bdate_range(start, periods=len(rows))
    o, h, lo, c = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c}, index=idx)


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


# ------------------------------------------------------------------ wiring / membership
def test_wired_cells_and_registry_tags():
    assert {t: n for t, (n, _r) in main.SWING_PEAK_LTP_TRAIL_CELLS.items()} == {**LONG_TAGS, "gap_and_go": 0.5}  # B-1491
    assert {t: n for t, (n, _r) in main.SHORT_SWING_PEAK_LTP_TRAIL_CELLS.items()} == {SHORT_TAG: 0.5}
    mode = {0.5: "live_lt0d5", 1.5: "live_lt1d5"}
    for t, (n, reg) in {**main.SWING_PEAK_LTP_TRAIL_CELLS, **main.SHORT_SWING_PEAK_LTP_TRAIL_CELLS}.items():
        if t != "gap_and_go":  # legacy tag predates the grammar; its band tag is gap_and_go__rsbandfloor__trailltp0d5r
            assert reg == bc.band_tag(t, mode[n]), t  # the validated trailed variant's own tag (naming grammar)
    for t in LONG_TAGS:
        assert t in main.SWING_TRAILING_STOP_TAGS and main._swing_is_trailing_tag(t)
        assert main._sl_kind("swing", t) == "Trail"
        assert "peak-LTP trail" in main._SWING_SL_RULES[t]
    assert main.SWING_PEAK_LTP_TRAIL_CELLS["gap_and_go"][1] == "gap_and_go__rsbandfloor__trailltp0d5r"  # B-1491 switch
    for t in (main.BRK20_LONG_SWING_TAGS[1], main.SWINGMINRR_GATE3_TAG, main.ISLAND_ALL_TAGS[1]):
        assert t not in main.SWING_PEAK_LTP_TRAIL_CELLS and not main._swing_is_trailing_tag(t)
    assert "swing_trail_peak" in main._GENERIC_MIRROR_TABLES and "swing_trail_peak" in main._GENERIC_MIRROR_T1


# ------------------------------------------------------------------ level math
def test_long_level_math_and_never_loosens():
    # entry 100, stop 90 -> R 10
    assert main.peak_ltp_trail_level("long", 100, 90, 100, 0.5) == 95.0
    assert main.peak_ltp_trail_level("long", 100, 90, 120, 0.5) == 115.0
    assert main.peak_ltp_trail_level("long", 100, 90, 120, 1.5) == 105.0
    assert main.peak_ltp_trail_level("long", 100, 90, 101, 1.5) == 90.0  # trail below the initial stop -> initial
    assert main.peak_ltp_trail_level("long", 100, 90, 80, 0.5) == 95.0   # peak never below entry


def test_short_level_math_and_never_loosens():
    # entry 100, stop 110 -> R 10
    assert main.peak_ltp_trail_level("short", 100, 110, 100, 0.5) == 105.0
    assert main.peak_ltp_trail_level("short", 100, 110, 80, 0.5) == 85.0
    assert main.peak_ltp_trail_level("short", 100, 110, 99, 1.5) == 110.0
    assert main.peak_ltp_trail_level("short", 100, 110, 130, 0.5) == 105.0


@pytest.mark.parametrize("ep,stop,want", [(100, 100, 100.0), (None, 90, 90.0), (0, 90, 90.0), ("x", 90, 90.0)])
def test_r_le_zero_or_missing_falls_back_to_initial(ep, stop, want):
    assert main.peak_ltp_trail_level("long", ep, stop, 130, 0.5) == want
    assert main.peak_ltp_trail_level("short", ep, stop, 50, 0.5) == want
    assert main.peak_ltp_trail_level("long", 100, 90, None, 0.5) == 90.0
    assert main._swing_strategy_stop_level(main.BRK20_SWING_TAG, 90, 2.5, 120) == 90.0  # no peak -> initial
    assert main._swing_strategy_stop_level(main.BRK20_SWING_TAG, 90, 2.5, 120, entry_price=100,
                                           peak_ltp=120) == 115.0


# ------------------------------------------------------------------ walk: completed bars only, entry bar excluded
def test_walk_excludes_entry_bar_and_matches_the_replay():
    # entry day bar (row 0) has a huge high that must NEVER join the peak
    df = _df([(100, 200, 99, 100), (100, 112, 99, 110), (110, 111, 108, 109), (109, 110, 100, 101)])
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 90.0, 0.5, "long")
    # bar1: level 95 (peak=entry), low 99 no hit, peak -> 112; bar2: level 107, low 108 no hit, peak 112;
    # bar3: level 107, low 100 -> hit at min(open 109, 107) = 107
    assert w["hit_idx"] == 3 and w["hit_price"] == pytest.approx(107.0) and w["peak"] == 112.0

    # the replay's own model on the same bars (fill bar = entry bar, checked from the bar after it)
    bc.reset_trail()
    hit = None
    pc = df["Close"].to_numpy()
    for j in range(1, len(df)):
        st = bc.trailed_stop("live_lt0d5", "long", 90.0, pc[j - 1], 100.0, df["High"].iloc[j], df["Low"].iloc[j])
        if df["Low"].iloc[j] <= st and st > 90.0:
            hit = (j, min(df["Open"].iloc[j], st))
            break
    assert hit == (3, pytest.approx(107.0))


def test_walk_forming_bar_is_never_used_and_no_hit_keeps_peak():
    df = _df([(100, 101, 99, 100), (100, 104, 99, 103)])
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 90.0, 0.5, "long")
    assert w["hit_idx"] is None and w["peak"] == 104.0 and w["level"] == pytest.approx(99.0)
    # the caller passes completed bars only (the swing scan drops today's forming bar in session): the stored peak
    # reflects exactly the bars handed in, never a later high
    w2 = main.peak_ltp_trail_walk(df.iloc[:1], "2026-10-01", 100.0, 90.0, 0.5, "long")
    assert w2["peak"] == 100.0 and w2["level"] == 95.0


def test_walk_initial_stop_hit_is_left_to_the_strategy_exit():
    df = _df([(100, 101, 99, 100), (95, 96, 85, 86)])  # level 95 > stop 90, low 85 -> trail hit (tighter than stop)
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 90.0, 0.5, "long")
    assert w["hit_idx"] == 1 and w["hit_price"] == 95.0
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 90.0, 2.0, "long")  # level = max(90, 100-20) = 90
    assert w["hit_idx"] is None  # a plain initial-stop hit: the strategy's own exit fn owns it


def test_walk_short_mirror():
    df = _df([(100, 101, 50, 100), (100, 101, 90, 91), (91, 97, 90, 96)])
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 110.0, 0.5, "short")
    # bar1: level 105, high 101 no hit, trough 90; bar2: level 95, high 97 -> hit at max(open 91, 95) = 95
    assert w["hit_idx"] == 2 and w["hit_price"] == 95.0 and w["peak"] == 90.0


# ------------------------------------------------------------------ persistence + re-place
def _long_row(conn, sym, tag, entry=100.0, stop=90.0, day="2026-10-01"):
    conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                 "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (sym, tag, day, entry, stop, None, 5, 1.0, 1.0, 2.5, entry))
    conn.commit()


def test_peak_store_only_tightens_and_ignores_a_stale_position(db):
    assert main._swing_trail_peak_put(db, "A.NS", "long", "2026-10-01", 110.0) == 110.0
    assert main._swing_trail_peak_put(db, "A.NS", "long", "2026-10-01", 105.0) == 110.0
    assert main._swing_trail_peak_get(db, "A.NS", "long", "2026-10-02") is None  # another position's row
    assert main._swing_trail_peak_put(db, "A.NS", "long", "2026-10-09", 101.0) == 101.0  # new position replaces
    assert main._swing_trail_peak_put(db, "B.NS", "short", "2026-10-01", 90.0) == 90.0
    assert main._swing_trail_peak_put(db, "B.NS", "short", "2026-10-01", 95.0) == 90.0


def test_replace_uses_trailed_level_and_live_ltp_reference(db, monkeypatch):
    tag = main.BRK20_SWING_TAG
    _long_row(db, "T.NS", tag)
    assert main._swing_trail_floor(db, "T.NS") is None  # no peak stored yet -> previous behaviour (stored stop)
    main._swing_trail_peak_put(db, "T.NS", "long", "2026-10-01", 120.0)
    main._SWING_LAST_CLOSE["T.NS"] = 114.0  # high-then-fade: level 115 sits above the last close
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 117.0)
    assert main._swing_trail_floor(db, "T.NS") == pytest.approx(115.0)  # live LTP is the reference, as the replay
    assert main._swing_stop_floored(db, "T.NS", 90.0) == pytest.approx(115.0)
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 114.5)
    assert main._swing_trail_floor(db, "T.NS") is None  # never re-placed at/above the market
    assert main._swing_peak_trail_level(db, "T.NS") == pytest.approx(115.0)  # ... the breach sweep closes it instead


def test_breach_sweep_uses_the_trailed_level(db, monkeypatch):
    tag = main.STARC_FULL_TAG
    _long_row(db, "S.NS", tag)
    main._swing_trail_peak_put(db, "S.NS", "long", "2026-10-01", 130.0)  # 1.5R trail -> 115
    db.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
               "stop_loss, strategy) VALUES ('S.NS','S-EQ',5,100,1.0,'2026-10-01',90,?)", (tag,))
    db.commit()
    seen = []
    monkeypatch.setattr(main, "_swing_entry_stop", lambda c, s: 90.0)
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 114.0)
    monkeypatch.setattr(main, "_swing_stop_breached_exit",
                        lambda c, s, stop, ltp, label="entry-day stop": seen.append((s, stop, ltp, label)) or True)
    assert main._swing_entry_stop_breach_sweep(db) == ["S.NS"]
    assert seen[0][:3] == ("S.NS", pytest.approx(115.0), 114.0) and "B-1486" in seen[0][3]


def test_trail_peak_survives_a_restart_wipe(monkeypatch):
    store = {}
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", "http://fake")
    monkeypatch.setattr(main, "UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(main, "_upstash_get", lambda k: store.get(k))
    monkeypatch.setattr(main, "_upstash_set", lambda k, v: store.__setitem__(k, v))
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()

    def fresh():
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        main.DB_PATH = path
        main.init_db()

    fresh()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        main._swing_trail_peak_put(c, "W.NS", "long", "2026-10-01", 123.4)
    main.sync_generic_tables_external(only=("swing_trail_peak",))
    fresh()  # simulated Render restart
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert main._swing_trail_peak_get(c, "W.NS", "long", "2026-10-01") == pytest.approx(123.4)
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()


def test_daily_pass_branch_wiring_present():
    import inspect
    src = inspect.getsource(main._run_swing_scan_pass)
    assert "peak_ltp_trail_walk(" in src and "peak_ltp_trail_stop_hit" in src and '"long", pos["entry_day"]' in src
    src = inspect.getsource(main._run_short_swing_pass)
    assert "SHORT_SWING_PEAK_LTP_TRAIL_CELLS" in src and "short_swing_peak_ltp_trail_stop_hit" in src
    assert "_swing_short_peak_trail_level(" in inspect.getsource(main._heal_real_swing_short_sl)
    assert np.isfinite(main.peak_ltp_trail_level("long", 100, 90, 110, 0.5))
