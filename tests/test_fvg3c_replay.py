"""Smoke/behaviour tests for scripts/fvg3c_replay.py (B-32 research harness)."""
import importlib.util
import pathlib
import re

import numpy as np
import pandas as pd

import main

_spec = importlib.util.spec_from_file_location(
    "fvg3c_replay", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fvg3c_replay.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def _synthetic(days=4, seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    px = 100.0
    for d in range(days):
        base = pd.Timestamp("2026-09-01", tz="UTC") + pd.Timedelta(days=d, hours=3, minutes=45)  # 09:15 IST
        for b in range(75):
            o = px
            c = px * (1 + rng.normal(0, 0.004))
            h = max(o, c) * (1 + abs(rng.normal(0, 0.002)))
            l = min(o, c) * (1 - abs(rng.normal(0, 0.002)))
            rows.append((base + pd.Timedelta(minutes=5 * b), o, h, l, c, 10000))
            px = c
    return pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])


def test_cell_tag_follows_naming_convention():
    tag = fr.cell_tag("valid_retest", "short", "5m", {"rr": 3.0})
    assert tag.startswith("fvg3c__valid_retest__short__5m__") and tag.endswith("__v1")
    assert re.fullmatch(r"[a-z0-9_]+", tag)
    assert "rr3d0" in tag
    # different params -> different tags (never pooled)
    assert tag != fr.cell_tag("valid_retest", "short", "5m", {"rr": 2.0})


def test_all_cells_run_on_synthetic_data_without_error():
    df, sessions, mins, ts = fr.prep(_synthetic())
    total = 0
    for v in main.FVG3C_VARIANTS:
        for d in ("long", "short"):
            trades = fr.replay_cell("SYN.NS", df, v, d, {"min_gap_atr": 0.1, "cons_bars": 1}, sessions, mins, ts)
            total += len(trades)
            for t in trades:
                assert t["exit_reason"] in {"stop_hit", "target_hit", "max_hold_timeout", "eod_squareoff", "window_end_forced_close"}
                assert t["total_cost"] > 0
    assert total > 0  # the synthetic walk produces at least some fvg3c trades


def test_short_gross_pnl_sign():
    t = fr._trade("X", "short", 100.0, 101.0, 10, 0.0, 60.0, 99.0, "target_hit", 5.0)
    assert t["gross_pnl"] == 10.0 and t["net_pnl"] < t["gross_pnl"]
    t2 = fr._trade("X", "long", 100.0, 99.0, 10, 0.0, 60.0, 101.0, "target_hit", 5.0)
    assert t2["gross_pnl"] == 10.0


def test_snd_zone_replay_harness_runs_and_names_tags():
    spec = importlib.util.spec_from_file_location(
        "snd_zone_replay", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "snd_zone_replay.py")
    sz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sz)
    t_long = sz.cell_tag("demand_retest", "5m", {})
    t_short = sz.cell_tag("supply_retest", "5m", {})
    assert t_long.startswith("snd_zone__demand_retest__long__5m__") and t_long.endswith("__v1")
    assert t_short.startswith("snd_zone__supply_retest__short__5m__")
    assert re.fullmatch(r"[a-z0-9_]+", t_long) and t_long != t_short
    assert t_long != sz.cell_tag("demand_retest", "5m", {"rr": 3.0})
    df, sessions, mins, ts = fr.prep(_synthetic(days=6, seed=11))
    for v, d in sz.VARIANT_DIR:
        scanner = lambda frame, prm, sess, _d=d: main.snd_zone_scan(frame, _d, prm, sessions=sess)  # noqa: E731
        trades = fr.replay_cell("SYN.NS", df, v, d, {"explosive_body_atr": 0.8, "confirm_bars": 1},
                                sessions, mins, ts, scanner=scanner, defaults=main.SND_DEFAULT_PARAMS)
        for t in trades:
            assert t["total_cost"] > 0


def test_dmi_replay_harness_runs_and_names_tags():
    spec = importlib.util.spec_from_file_location(
        "dmi_replay", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "dmi_replay.py")
    dr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dr)
    tags = {dr.cell_tag(v, d, "5m", {}) for v, d in dr.VARIANT_DIR}
    assert len(tags) == 6 and all(t.startswith("dmi_adx__") and t.endswith("__v1") and re.fullmatch(r"[a-z0-9_]+", t) for t in tags)
    assert dr.cell_tag("cross", "long", "5m", {"period": 20}) != dr.cell_tag("cross", "long", "5m", {})
    df, sessions, mins, ts = fr.prep(_synthetic(days=8, seed=13))
    n = 0
    for v, d in dr.VARIANT_DIR:
        scanner = lambda frame, prm, sess, _v=v, _d=d: main.dmi_scan(frame, _v, _d, prm, sessions=sess)  # noqa: E731
        trades = fr.replay_cell("SYN.NS", df, v, d, {"period": 7}, sessions, mins, ts, scanner=scanner, defaults=main.DMI_DEFAULT_PARAMS)
        n += len(trades)
        assert all(t["total_cost"] > 0 for t in trades)
    assert n > 0
