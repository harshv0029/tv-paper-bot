"""B-1500 (2026-11-06 IST, CLAUDE.md WIRING RULE): every exit variant (fixed / peak-LTP / chandelier / breakeven) of a
live LONG swing tag with pooled PFnet > 1.00 is wired; variants are tried in return-per-day order and the first whose
own registry tag passes the viability gate owns the entry. Stored per position (swing_exit_variant, Upstash T1).

Run: pytest tests/test_swing_exit_variants_b1500.py -v
"""
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

GG = "gap_and_go"
FADE = "gaps__common_fade__long__1d__atr3_nb5__v1"  # not a B-1486 trail cell (fixed today)


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


def _today():
    return main.ist_now().strftime("%Y-%m-%d")


def _row(conn, sym, tag, day, entry=100.0, stop=90.0):
    conn.execute("INSERT INTO signal_state_swing (symbol, strategy, entry_day, entry_price, initial_stop_loss, gap_low, "
                 "qty, entry_ts, fx_to_inr, atr_at_entry, running_max_close) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (sym, tag, day, entry, stop, None, 5, 1.0, 1.0, 2.5, entry))
    conn.commit()


# ------------------------------------------------------------------ generated priority list
def test_mode_rules_match_the_replay():
    assert main.SWING_EXIT_MODE_RULES == bc.TRAIL_RULES
    assert main.SWING_TRAIL_BE_COST == pytest.approx(bc.BE_COST)
    assert main.swing_exit_mode_rule("live") is None and main.swing_exit_mode_rule("bogus") is None
    assert main.swing_exit_mode_rule("live_tr1d5") == ("chand", 1.5)
    assert main.swing_exit_mode_rule("live_be2") == ("be", 2.0) and main.swing_exit_mode_rule("live_lt0d5") == ("ltp", 0.5)


def test_generated_module_is_fresh():
    assert open(gen.OUT).read() == gen.render(gen.build_rows()), "run python3 scripts/gen_swing_exit_variants.py"


def test_variant_lists_pfnet_gt_1_and_return_per_day_order():
    import strategy_registry as sr
    v = main.SWING_EXIT_VARIANTS
    assert len(v) >= 20 and GG in v and FADE in v
    hourly = set(main.MACDDIV_LONG_LIVE_CELLS) | set(main.ENVELOPE_LONG_LIVE_CELLS) | set(main.BRK20_1H_LONG_CELLS)
    for t, cands in v.items():
        assert t in main._STRATEGY_TAG_TO_REGISTRY_NAME and t not in hourly and (t == GG or "__long__" in t)
        rpds = [c[2] for c in cands]
        assert rpds == sorted(rpds, reverse=True), t
        modes = [c[0] for c in cands]
        assert len(set(modes)) == len(modes)
        for mode, reg, rpd, pf, n, net, held, _rid in cands:
            assert mode == "live" or main.swing_exit_mode_rule(mode) is not None  # every mode has a live implementation
            assert reg == bc.band_tag(t, mode) and pf > 1.0
            assert rpd == pytest.approx(net / held, abs=1e-5)
            assert main._registry_entry(reg).metrics.pfnet > sr.PFNET_LIVE_FLOOR
    # gap_and_go's best return per day is the B-1491 peak-LTP 0.5R trail it already runs
    assert v[GG][0][0] == "live_lt0d5"


# ------------------------------------------------------------------ live arithmetic == scripts/swing_bandcap.trailed_stop
def _rand_df(seed, n=40):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.004, 0.02, n))
    c[0] = 100.0
    o = c * (1 + rng.normal(0, 0.005, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.012, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.012, n)))
    idx = pd.bdate_range("2026-09-01", periods=n)
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c}, index=idx)


@pytest.mark.parametrize("mode", sorted(f"live_{k}" for k in bc.TRAIL_RULES))
@pytest.mark.parametrize("seed", [1, 2, 3, 7])
def test_each_mode_level_and_hit_equal_the_replay(mode, seed):
    df = _rand_df(seed)
    ep, stop0 = 100.0, 94.0
    kind, nmul = main.swing_exit_mode_rule(mode)
    pc = df["Close"].to_numpy()
    bc.reset_trail()
    nohit = df.assign(Low=np.nan)  # the level series alone, no hit cut
    bt_hit = None
    for j in range(1, len(df)):
        st = bc.trailed_stop(mode, "long", stop0, pc[j - 1], ep, df["High"].iloc[j], df["Low"].iloc[j])
        live = main.peak_ltp_trail_walk(nohit.iloc[:j], df.index[0].strftime("%Y-%m-%d"), ep, stop0, nmul, "long",
                                        kind=kind)["level"]
        assert live == pytest.approx(st, abs=1e-9), (mode, seed, j)
        if bt_hit is None and st > stop0 and df["Low"].iloc[j] <= st:
            bt_hit = (j, min(df["Open"].iloc[j], st))
    w = main.peak_ltp_trail_walk(df, df.index[0].strftime("%Y-%m-%d"), ep, stop0, nmul, "long", kind=kind)
    if bt_hit is None:
        assert w["hit_idx"] is None
    else:
        assert (w["hit_idx"], w["hit_price"]) == (bt_hit[0], pytest.approx(bt_hit[1]))


def test_be_level_math():
    assert main.swing_trail_level("be", "long", 100, 90, 109.9, 1.0) == 90.0
    assert main.swing_trail_level("be", "long", 100, 90, 110, 1.0) == pytest.approx(100.8)
    assert main.swing_trail_level("be", "long", 100, 90, 130, 2.0) == pytest.approx(100.8)
    assert main.swing_trail_level("be", "long", 100, 100, 130, 1.0) == 100.0  # R = 0 -> initial
    assert main.swing_trail_level("chand", "long", 100, 90, 120, 1.0) == 110.0


# ------------------------------------------------------------------ selection
def test_first_viable_variant_owns_the_entry_and_falls_through(db, monkeypatch):
    cands = main.SWING_EXIT_VARIANTS[GG]
    second = cands[1][1]
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name",
                        lambda name, tag, check_switch=False: (name == second, "viable" if name == second else "below_floor"))
    _row(db, "G.NS", GG, _today())
    sel = main._select_swing_exit_variant(db, "G.NS", GG)
    assert sel["mode"] == cands[1][0] and sel["gate_ok"] and sel["tried"] == [(cands[0][0], "below_floor"),
                                                                              (cands[1][0], "viable")]
    assert main._swing_exit_variant_get(db, "G.NS", _today(), GG)["mode"] == cands[1][0]
    assert main._swing_long_trail_rule(db, "G.NS", GG, _today()) == main.swing_exit_mode_rule(cands[1][0])
    # nothing passes -> the first (best return per day) variant, paper only
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name", lambda name, tag, check_switch=False: (False, "no_stack"))
    sel = main._select_swing_exit_variant(db, "G.NS", GG)
    assert sel["mode"] == cands[0][0] and not sel["gate_ok"] and sel["verdict"] == "no_variant_viable"


def test_frozen_once_real_money_is_in(db, monkeypatch):
    cands = main.SWING_EXIT_VARIANTS[FADE]
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name", lambda n, t, check_switch=False: (True, "viable"))
    _row(db, "F.NS", FADE, _today())
    main._swing_exit_variant_put(db, "F.NS", _today(), FADE, cands[-1][0], cands[-1][1])
    db.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
               "stop_loss, strategy) VALUES ('F.NS','F-EQ',5,100,1.0,?,90,?)", (_today(), FADE))
    db.commit()
    sel = main._select_swing_exit_variant(db, "F.NS", FADE)
    assert sel["frozen"] and sel["mode"] == cands[-1][0]  # never re-chosen under an open real position


def test_legacy_positions_unchanged(db):
    _row(db, "L.NS", GG, "2026-10-01")
    _row(db, "M.NS", FADE, "2026-10-01")
    assert main._select_swing_exit_variant(db, "L.NS", GG) is None  # not today's entry: never chosen retroactively
    assert main._swing_exit_variant_get(db, "L.NS") is None
    assert main._swing_long_trail_rule(db, "L.NS", GG, "2026-10-01") == ("ltp", 0.5)  # B-1486/B-1491 cell
    assert main._swing_long_trail_rule(db, "M.NS", FADE, "2026-10-01") is None  # fixed, as before
    assert main._select_swing_exit_variant(db, "X.NS", "power_play") is None  # no variants for this tag
    # a stale row of another position never applies
    main._swing_exit_variant_put(db, "L.NS", "2026-09-01", GG, "live", "x")
    assert main._swing_long_trail_rule(db, "L.NS", GG, "2026-10-01") == ("ltp", 0.5)


def test_stored_variant_drives_every_stop_path(db, monkeypatch):
    # gap_and_go is a B-1486 cell, but a stored fixed variant switches its trail OFF
    _row(db, "G.NS", GG, "2026-10-01")
    main._swing_exit_variant_put(db, "G.NS", "2026-10-01", GG, "live", bc.band_tag(GG, "live"))
    main._swing_trail_peak_put(db, "G.NS", "long", "2026-10-01", 130.0)
    assert main._swing_long_trail_rule(db, "G.NS", GG, "2026-10-01") is None
    assert main._swing_peak_trail_level(db, "G.NS") is None
    assert main._swing_trail_floor(db, "G.NS") is None
    # a fixed-stop tag with a stored breakeven variant trails to entry x 1.008 once the close peak gains 1R
    _row(db, "F.NS", FADE, "2026-10-01")
    main._swing_exit_variant_put(db, "F.NS", "2026-10-01", FADE, "live_be1", bc.band_tag(FADE, "live_be1"))
    main._swing_trail_peak_put(db, "F.NS", "long", "2026-10-01", 112.0)
    assert main._swing_peak_trail_level(db, "F.NS") == pytest.approx(100.8)
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 108.0)
    assert main._swing_trail_floor(db, "F.NS") == pytest.approx(100.8)
    assert main._swing_stop_floored(db, "F.NS", 90.0) == pytest.approx(100.8)
    monkeypatch.setattr(main, "_swing_live_ltp", lambda s: 100.5)
    assert main._swing_trail_floor(db, "F.NS") is None  # never at/above the market
    assert main._sl_kind("swing", FADE, "F.NS") in ("Trail", "Fixed")


def test_real_entry_gate_uses_the_chosen_variant(db, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "is_real_swing_trading_enabled", lambda: True)
    monkeypatch.setattr(main, "_swing_real_entry_session_open", lambda: True)
    monkeypatch.setattr(main, "_maybe_place_swing_option_leg", lambda *a, **k: None)
    monkeypatch.setattr(main, "_etf_entry_range_ok", lambda s: (True, ""))
    monkeypatch.setattr(main, "_log_signal_shadow", lambda *a, **k: None)
    monkeypatch.setattr(main, "_sector_cap_blocks", lambda *a, **k: "stop here")
    monkeypatch.setattr(main, "_log_real_attempt", lambda c, s, side, status, **k: seen.append((status, k.get("detail"))))
    monkeypatch.setattr(main, "_is_strategy_viable_for_real_money", lambda t, check_switch=True: False)
    cands = main.SWING_EXIT_VARIANTS[FADE]
    ok_tag = cands[2][1]
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name",
                        lambda n, t, check_switch=False: (n == ok_tag, "viable" if n == ok_tag else "below_floor"))
    _row(db, "F.NS", FADE, _today())
    main._maybe_place_real_swing_entry(db, "F.NS", 5, 100.0, 90.0, FADE)
    assert seen[-1][0] == "skipped_no_live_tick"  # B-1517: sector cap now runs after sizing; passed the PFnet gate through the 3rd variant
    assert main._swing_exit_variant_get(db, "F.NS")["mode"] == cands[2][0]
    # no variant viable and the tag's own row not viable -> gate closed (paper only, first variant)
    monkeypatch.setattr(main, "_viability_verdict_for_registry_name", lambda n, t, check_switch=False: (False, "below_floor"))
    main._maybe_place_real_swing_entry(db, "F.NS", 5, 100.0, 90.0, FADE)
    assert seen[-1][0] == "skipped_strategy_not_viable" and "B-1500" in seen[-1][1]
    assert main._swing_exit_variant_get(db, "F.NS")["mode"] == cands[0][0]


def test_exit_variant_survives_a_restart_wipe(monkeypatch):
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
        main._swing_exit_variant_put(c, "W.NS", "2026-10-01", FADE, "live_tr1", "reg")
    main.sync_generic_tables_external(only=("swing_exit_variant",))
    fresh()  # simulated Render restart
    main._generic_mirror_hydrated.clear()
    main.hydrate_generic_tables_from_external()
    with closing(main.get_db()) as c:
        assert main._swing_exit_variant_get(c, "W.NS", "2026-10-01", FADE)["mode"] == "live_tr1"
    main._generic_mirror_hydrated.clear()
    main._generic_mirror_last_hash.clear()


def test_daily_pass_uses_the_position_rule():
    import inspect
    src = inspect.getsource(main._run_swing_scan_pass)
    assert "_swing_long_trail_rule(" in src and "kind=_trule[0]" in src and "_swing_exit_variant_clear(" in src
    assert "_select_swing_exit_variant(" in inspect.getsource(main._maybe_place_real_swing_entry)


def test_b1504_position_sl_rule_states_the_stored_variant(db):
    assert GG in main.SWING_EXIT_VARIANTS
    # no stored variant -> the tag's default text
    assert main._position_sl_rule(db, "swing", GG, "X.NS") == main._SWING_SL_RULES.get(GG)
    main._swing_exit_variant_put(db, "X.NS", "2026-11-06", GG, "live", "t")
    assert main._position_sl_rule(db, "swing", GG, "X.NS").startswith("fixed initial stop")
    main._swing_exit_variant_put(db, "X.NS", "2026-11-06", GG, "live_tr1d5", "t")
    assert main._position_sl_rule(db, "swing", GG, "X.NS").startswith("chandelier trail")
    main._swing_exit_variant_put(db, "X.NS", "2026-11-06", GG, "live_be1", "t")
    assert "breakeven" in main._position_sl_rule(db, "swing", GG, "X.NS")
    # other categories are untouched
    assert main._position_sl_rule(db, "buy", GG, "X.NS") == main._SWING_SL_RULES.get(GG)
