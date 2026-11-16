"""B-1501 (2026-11-15 IST): the B-1500 exit-variant chooser for the SHORT daily swing engine (signal_state_swing_short).
Every short variant with pooled PFnet > 1.00 is wired, tried in return-per-day order, the first whose own registry tag
passes the viability gate owns the entry (none -> the first, paper). Short rows are stored in swing_exit_variant under
"short:<symbol>" (never collides with the long row). A short trail only LOWERS the BUY stop.

Run: pytest tests/test_b1501_short_swing_exit_variants.py -v
"""
import inspect
import os
import sys
import tempfile
from contextlib import closing

import numpy as np
import pandas as pd
import pytest

import main

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import gen_swing_exit_variants as gen  # noqa: E402
import swing_bandcap as bc  # noqa: E402

BRK = "brk20_min_rr__main_replay__short__1d__atr4_rr4__v1"  # the B-1486 short trail cell
TAS = "tasuki__gap_etf__short__1d__atr6_h3__v1"  # fixed stop + 3-bar hold today


@pytest.fixture
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    main.DB_PATH = path
    main.init_db()
    with closing(main.get_db()) as conn:
        yield conn


def _today():
    return main.ist_now().strftime("%Y-%m-%d")


def _row(conn, sym, tag, day, entry=100.0, stop=110.0):
    conn.execute("INSERT INTO signal_state_swing_short (symbol, strategy, entry_day, entry_price, initial_stop_loss, "
                 "qty, entry_ts, fx_to_inr, atr_at_entry) VALUES (?,?,?,?,?,?,?,?,?)",
                 (sym, tag, day, entry, stop, 5, 1.0, 1.0, 2.5))
    conn.commit()


# ------------------------------------------------------------------ generator
def test_generator_emits_only_pfnet_gt_1_short_rows():
    import strategy_registry as sr
    v = main.SHORT_SWING_EXIT_VARIANTS
    assert v == gen.build_rows("short")
    assert BRK in v and TAS in v
    live_short = set(main.SHORT_SWING_TAGS) | set(main.TASUKI_SHORT_CELLS)
    for t, cands in v.items():
        assert "__short__" in t and "__1h__" not in t and t in live_short and not t.startswith("swingminrr")
        rpds = [c[2] for c in cands]
        assert rpds == sorted(rpds, reverse=True), t
        for mode, reg, rpd, pf, n, net, held, _rid in cands:
            assert mode == "live" or main.swing_exit_mode_rule(mode) is not None
            assert reg == bc.band_tag(t, mode) and pf > 1.0
            assert rpd == pytest.approx(net / held, abs=1e-5)
            assert main._registry_entry(reg).metrics.pfnet > sr.PFNET_LIVE_FLOOR
    # tasuki lt0d5 (PFnet 0.946) is <= 1.00 and never wired
    assert "live_lt0d5" not in [c[0] for c in v["tasuki__gap_etf__short__1d__atr4_h3__v1"]]
    # the long list is untouched by the short rows and the module is fresh
    assert not any("__short__" in t for t in main.SWING_EXIT_VARIANTS)
    assert open(gen.OUT).read() == gen.render(gen.build_rows("long"), v)


# ------------------------------------------------------------------ chooser
def test_first_viable_variant_owns_the_short_entry_and_falls_through(db, monkeypatch):
    cands = main.SHORT_SWING_EXIT_VARIANTS[BRK]
    second = cands[1][1]
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name",
                        lambda name, tag, check_switch=False: (name == second, "viable" if name == second else "below_floor"))
    _row(db, "S.NS", BRK, _today())
    sel = main._select_short_swing_exit_variant(db, "S.NS", BRK)
    assert sel["mode"] == cands[1][0] and sel["gate_ok"] and not sel["frozen"]
    assert sel["tried"] == [(cands[0][0], "below_floor"), (cands[1][0], "viable")]
    assert main._swing_short_exit_variant_get(db, "S.NS", _today(), BRK)["mode"] == cands[1][0]
    assert main._swing_short_trail_rule(db, "S.NS", BRK, _today()) == main.swing_exit_mode_rule(cands[1][0])
    # nothing passes -> the first (best return per day) variant, paper only; same-day re-pick before a real short
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name", lambda n, t, check_switch=False: (False, "no_stack"))
    sel = main._select_short_swing_exit_variant(db, "S.NS", BRK)
    assert sel["mode"] == cands[0][0] and not sel["gate_ok"] and sel["verdict"] == "no_variant_viable"


def test_frozen_once_a_real_short_exists(db, monkeypatch):
    cands = main.SHORT_SWING_EXIT_VARIANTS[TAS]
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name", lambda n, t, check_switch=False: (True, "viable"))
    _row(db, "T.NS", TAS, _today())
    main._swing_short_exit_variant_put(db, "T.NS", _today(), TAS, cands[-1][0], cands[-1][1])
    db.execute("INSERT INTO real_positions_swing_short (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
               "stop_loss, strategy) VALUES ('T.NS','T-EQ',5,100,1.0,?,110,?)", (_today(), TAS))
    db.commit()
    sel = main._select_short_swing_exit_variant(db, "T.NS", TAS)
    assert sel["frozen"] and sel["mode"] == cands[-1][0]
    # an older short (not today's entry) is never chosen retroactively
    _row(db, "O.NS", BRK, "2026-10-01")
    assert main._select_short_swing_exit_variant(db, "O.NS", BRK) is None
    assert main._swing_short_exit_variant_get(db, "O.NS") is None


def test_side_keying_never_collides_with_the_long_row(db):
    main._swing_exit_variant_put(db, "S.NS", "2026-10-01", "gap_and_go", "live_lt0d5", "long_reg")
    main._swing_short_exit_variant_put(db, "S.NS", "2026-10-01", BRK, "live", "short_reg")
    assert main._swing_exit_variant_get(db, "S.NS")["registry_tag"] == "long_reg"
    assert main._swing_short_exit_variant_get(db, "S.NS")["registry_tag"] == "short_reg"
    main._swing_short_exit_variant_clear(db, "S.NS")
    assert main._swing_short_exit_variant_get(db, "S.NS") is None
    assert main._swing_exit_variant_get(db, "S.NS")["mode"] == "live_lt0d5"


# ------------------------------------------------------------------ stop paths
def test_short_trail_only_lowers_the_buy_stop(db):
    _row(db, "S.NS", BRK, "2026-10-01")  # entry 100, BUY stop 110, R = 10
    main._swing_short_exit_variant_put(db, "S.NS", "2026-10-01", BRK, "live_be1", "x")
    main._swing_trail_peak_put(db, "S.NS", "short", "2026-10-01", 104.0)  # no 1R fall yet -> initial stop
    assert main._swing_short_peak_trail_level(db, "S.NS") is None
    main._swing_trail_peak_put(db, "S.NS", "short", "2026-10-01", 89.0)  # fell >= 1R -> net breakeven below entry
    assert main._swing_short_peak_trail_level(db, "S.NS") == pytest.approx(100 * (1 - main.SWING_TRAIL_BE_COST))
    # every mode, any trough: never above the initial stop
    for mode in main.SWING_EXIT_MODE_RULES:
        k, n = main.swing_exit_mode_rule("live_" + mode)
        for pk in (80.0, 95.0, 100.0, 130.0):
            assert main.swing_trail_level(k, "short", 100.0, 110.0, pk, n) <= 110.0
    # a rising market never lifts a short's trail above the initial stop and never "hits" the initial stop itself
    df = pd.DataFrame({"Date": [f"2026-10-0{i}" for i in range(2, 8)], "Open": np.linspace(101, 125, 6),
                       "High": np.linspace(102, 126, 6), "Low": np.linspace(100, 124, 6), "Close": np.linspace(101, 125, 6)})
    w = main.peak_ltp_trail_walk(df, "2026-10-01", 100.0, 110.0, 2.0, "short", "chand")
    assert w["level"] <= 110.0 and w["hit_idx"] is None


def test_unknown_mode_stays_on_the_fixed_initial_stop(db):
    _row(db, "S.NS", BRK, "2026-10-01")  # a B-1486 trail cell: a stored unknown mode must NOT fall back to the trail
    main._swing_short_exit_variant_put(db, "S.NS", "2026-10-01", BRK, "live_bogus", "x")
    main._swing_trail_peak_put(db, "S.NS", "short", "2026-10-01", 80.0)
    assert main._swing_short_trail_rule(db, "S.NS", BRK, "2026-10-01") is None
    assert main._swing_short_peak_trail_level(db, "S.NS") is None
    pos = db.execute("SELECT * FROM signal_state_swing_short WHERE symbol='S.NS'").fetchone()
    df = pd.DataFrame({"Date": ["2026-10-02"], "Open": [90.0], "High": [109.0], "Low": [85.0], "Close": [100.0]})
    xdf, hit = main._short_swing_trail_walk(db, "S.NS", pos, df)
    assert hit is None and len(xdf) == 1


def test_legacy_short_trail_cells_fallback(db):
    _row(db, "S.NS", BRK, "2026-10-01")
    _row(db, "T.NS", TAS, "2026-10-01")
    assert main._swing_short_trail_rule(db, "S.NS", BRK, "2026-10-01") == ("ltp", 0.5)  # B-1486 cell, no stored row
    assert main._swing_short_trail_rule(db, "T.NS", TAS, "2026-10-01") is None  # fixed, as before
    main._swing_trail_peak_put(db, "S.NS", "short", "2026-10-01", 90.0)
    assert main._swing_short_peak_trail_level(db, "S.NS") == pytest.approx(95.0)  # trough 90 + 0.5R
    # a stale row of an earlier short never applies
    main._swing_short_exit_variant_put(db, "S.NS", "2026-09-01", BRK, "live", "x")
    assert main._swing_short_trail_rule(db, "S.NS", BRK, "2026-10-01") == ("ltp", 0.5)
    # a stored fixed variant switches the B-1486 trail OFF for its own position
    main._swing_short_exit_variant_put(db, "S.NS", "2026-10-01", BRK, "live", "x")
    assert main._swing_short_peak_trail_level(db, "S.NS") is None


def test_tasuki_trail_variant_hits_and_closes(db, monkeypatch):
    _row(db, "T.NS", TAS, "2026-10-01")
    main._swing_short_exit_variant_put(db, "T.NS", "2026-10-01", TAS, "live_lt1", "x")
    pos = db.execute("SELECT * FROM signal_state_swing_short WHERE symbol='T.NS'").fetchone()
    # bar 1 falls to 88 (trail -> 88 + 10 = 98); bar 2 rallies to 99 -> trail hit at max(open, 98)
    df = pd.DataFrame({"Date": ["2026-10-01", "2026-10-02", "2026-10-05"], "Open": [100.0, 95.0, 96.0],
                       "High": [101.0, 96.0, 99.0], "Low": [99.0, 88.0, 95.0], "Close": [100.0, 90.0, 98.0]})
    xdf, hit = main._short_swing_trail_walk(db, "T.NS", pos, df)
    assert hit is not None and hit["hit_price"] == pytest.approx(98.0) and len(xdf) == 2
    assert main._swing_trail_peak_get(db, "T.NS", "short", "2026-10-01") == pytest.approx(88.0)
    src = inspect.getsource(main._run_short_swing_pass)
    assert src.count("_short_swing_trail_walk(") == 2 and "SHORT_SWING_PEAK_LTP_TRAIL_CELLS[" not in src


def test_close_clears_the_short_row_only(db, monkeypatch):
    monkeypatch.setattr(main, "_maybe_place_real_swing_short_exit", lambda *a, **k: None)
    _row(db, "S.NS", BRK, "2026-10-01")
    main._swing_short_exit_variant_put(db, "S.NS", "2026-10-01", BRK, "live_tr1", "x")
    main._swing_exit_variant_put(db, "S.NS", "2026-09-01", "gap_and_go", "live", "y")
    pos = db.execute("SELECT * FROM signal_state_swing_short WHERE symbol='S.NS'").fetchone()
    main._short_swing_close_paper(db, "S.NS", pos, 95.0, "test")
    assert main._swing_short_exit_variant_get(db, "S.NS") is None
    assert main._swing_exit_variant_get(db, "S.NS") is not None


def test_real_short_entry_runs_the_chooser_and_keeps_the_product_gate(db, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "SHORT_SWING_OVERNIGHT_PRODUCT_CONFIRMED", False)
    monkeypatch.setattr(main, "_log_real_attempt", lambda c, s, side, status, **k: seen.append(status))
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name", lambda n, t, check_switch=False: (False, "x"))
    _row(db, "S.NS", BRK, _today())
    main._maybe_place_real_swing_short_entry(db, "S.NS", 5, 100.0, 110.0, BRK)
    assert seen == ["skipped_overnight_short_product_unconfirmed"]  # the real leg stays held
    assert main._swing_short_exit_variant_get(db, "S.NS")["mode"] == main.SHORT_SWING_EXIT_VARIANTS[BRK][0][0]


def test_short_exit_variant_survives_a_restart_wipe(monkeypatch):
    assert "swing_exit_variant" in main._GENERIC_MIRROR_TABLES and "swing_exit_variant" in main._GENERIC_MIRROR_T1
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
        main._swing_short_exit_variant_put(c, "W.NS", "2026-10-01", BRK, "live_tr1", "reg")
        main._swing_exit_variant_put(c, "W.NS", "2026-10-01", "gap_and_go", "live", "lreg")
    main.sync_generic_tables_external(only=("swing_exit_variant",))
    fresh()  # simulated Render restart
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert main._swing_short_exit_variant_get(c, "W.NS", "2026-10-01", BRK)["mode"] == "live_tr1"
        assert main._swing_exit_variant_get(c, "W.NS", "2026-10-01", "gap_and_go")["mode"] == "live"
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()
