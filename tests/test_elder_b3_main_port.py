"""B-1472 (b): main.py port of the Elder batch-3 cells (osc div_class kb, osc reversal rsi 30/70, chan pivot_tl_break)
must reproduce scripts/elder_batch3_research.py's signals and sim2 exits exactly, and use no future bars."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import main as m  # noqa: E402
import elder_batch3_research as b3  # noqa: E402
import elder_b3_main_replay as rp  # noqa: E402

COST = m.ROUND_TRIP_COST_PCT / 100.0


def frame(seed, n=420, double_bottoms=True, bad_bar=None):
    df = rp.synthetic_frame(seed, n)
    if double_bottoms:  # repeat a recent low within 0.5% so class-b divergences exist
        lo = df["Low"].to_numpy().copy()
        for i in range(80, n - 20, 37):
            j = i - 12
            if lo[j] == lo[j - 3:j + 4].min():
                lo[i] = lo[j] * 1.001
                df.loc[i, "Low"] = lo[i]
                df.loc[i, ["Open", "Close"]] = np.maximum(df.loc[i, ["Open", "Close"]].to_numpy(), lo[i] * 1.002)
                df.loc[i, "High"] = max(df.loc[i, "High"], df.loc[i, "Close"], df.loc[i, "Open"])
    if bad_bar is not None:
        df.loc[bad_bar, ["Open", "Close"]] = df.loc[bad_bar, ["Open", "Close"]].to_numpy() * 3.0
        df.loc[bad_bar, "High"] = df.loc[bad_bar, ["Open", "Close", "High"]].max()
    return rp.prep(df)


def research_sig(df, source):
    _fam, var, p = m.ELDER_B3_SOURCES[source]
    if var == "div_class":
        return b3.v_diverge_class(df, p["k"], p["osc"])
    if var == "reversal":
        return b3.v_reversal(df, p["osc"], p["lo"], p["hi"])
    return b3.v_pivot_trendline(df, p["w"])


def research_trades(df, tag):
    src, direction, am = m.ELDER_B3_TAG_INFO[tag]
    s = research_sig(df, src)
    tr = b3.sim2(df, s[direction], direction, am, s["stop_" + direction], s["tgt_" + direction], s["exit_" + direction],
                 cost=COST)
    return [(t["entry_i"], t["reason"], t["hold"], round(t["ret"], 12)) for t in tr]


def main_trades(df, tag):
    src, direction, _am = m.ELDER_B3_TAG_INFO[tag]
    sigs = rp.collect_signals(m, df, src)
    trs, _ = rp.simulate_tag(m, df, tag, sorted(k for k, v in sigs.items() if v[direction]), COST)
    return [(t["entry_i"], t["reason"], t["held"], round(t["net"], 12)) for t in trs]


def test_tags_follow_research_grammar():
    assert m.elder_b3_tag("div_kb_rsi", "long", 3.0, mr=False) == "osc__div_class__long__1d__atr3_kb_oscrsi__v1"
    assert m.elder_b3_tag("rev_rsi_30_70", "long", 3.0, mr=False) == "osc__reversal__long__1d__atr3_hi70_lo30_oscrsi__v1"
    assert m.elder_b3_tag("ptl_w5", "long", 3.0, mr=False) == "chan__pivot_tl_break__long__1d__atr3_w5__v1"
    assert m.elder_b3_tag("ptl_w5", "short", 1.5) == "chan__pivot_tl_break_mr__short__1d__atr1d5_w5__v1"
    assert len(m.ELDER_B3_ALL_TAGS) == 30


@pytest.mark.parametrize("source", list(m.ELDER_B3_SOURCES))
def test_full_frame_signals_match_research(source):
    for seed in (1, 2, 3):
        df = frame(seed)
        a, r = m.elder_b3_signal_arrays(df, source), research_sig(df, source)
        for k in ("long", "short", "exit_long", "exit_short"):
            assert np.array_equal(a[k], r[k]), (source, seed, k)


def test_signals_fire_on_synthetic():
    tot = {s: 0 for s in m.ELDER_B3_SOURCES}
    for seed in (1, 2, 3):
        df = frame(seed)
        for s in tot:
            a = m.elder_b3_signal_arrays(df, s)
            tot[s] += int(a["long"].sum() + a["short"].sum())
    assert all(v > 0 for v in tot.values()), tot


@pytest.mark.parametrize("source", ["div_kb_rsi", "rev_rsi_30_70", "ptl_w3", "ptl_w5"])
def test_bar_by_bar_trades_match_research_sim2(source):
    for seed, bad in ((1, None), (2, 200), (3, 311)):
        df = frame(seed, bad_bar=bad)
        for tag in rp.tags_for_sources(m, (source,)):
            assert main_trades(df, tag) == research_trades(df, tag), (tag, seed)


def test_macdh_walk_forward_uses_prefix_median_only():
    """Documented deviation: the research takes the macdh tolerance over the WHOLE history (future bars). The port's
    walk-forward value at t equals the research detector run on bars <= t."""
    df = frame(4)
    for t in range(60, len(df) - 1, 7):
        sub = df.iloc[:t + 1]
        r = research_sig(sub, "div_kb_macdh")
        got = m.elder_b3_last_bar_signals(sub, "div_kb_macdh")
        assert got == {"long": bool(r["long"][-1]), "short": bool(r["short"][-1])}


@pytest.mark.parametrize("source", list(m.ELDER_B3_SOURCES))
def test_no_look_ahead(source):
    """Signal on bar t is unchanged when every bar after t is replaced by garbage."""
    df = frame(5)
    rng = np.random.default_rng(9)
    for t in range(40, len(df) - 2, 11):
        base = m.elder_b3_last_bar_signals(df.iloc[:t + 1], source)
        mut = df.copy()
        k = len(df) - t - 1
        scale = rng.uniform(0.5, 1.5, k)
        for col in ("Open", "High", "Low", "Close"):
            mut.loc[t + 1:, col] = mut.loc[t + 1:, col].to_numpy() * scale
        full = m.elder_b3_signal_arrays(mut.iloc[:t + 1], source)
        assert base == {"long": bool(full["long"][-1]), "short": bool(full["short"][-1])}
        if source != "div_kb_macdh":  # full-frame value at t == walk-forward value (macdh: whole-df median)
            whole = m.elder_b3_signal_arrays(df, source)
            assert base == {"long": bool(whole["long"][t]), "short": bool(whole["short"][t])}


def test_exit_reason_uses_bars_up_to_j_only():
    df = frame(6)
    tag = m.elder_b3_tag("rev_rsi_30_70", "long", 2.0)
    e, px = 100, float(df["Open"].iloc[100])
    stop = px * 0.9
    full_exit = m.elder_b3_signal_arrays(df, "rev_rsi_30_70")["exit_long"]
    lo = df["Low"].to_numpy()
    seen = False
    for j in range(e, e + 31):
        reason, xp = m.elder_b3_exit_reason(df.iloc[:j + 1], tag, e, px, stop)
        if lo[j] > stop and j > e:  # no stop hit: rule exit on the prefix == full-frame rule value at j
            assert (reason == "rule_exit") == bool(full_exit[j])
            seen = True
        if reason:
            assert xp is not None
            break
    assert seen


def test_stop_attached_on_every_entry():
    df = frame(7)
    for tag in m.ELDER_B3_ALL_TAGS:
        src, direction, am = m.ELDER_B3_TAG_INFO[tag]
        for s in np.flatnonzero(m.elder_b3_signal_arrays(df, src)[direction])[:3]:
            sig = m.elder_b3_entry_signal(df.iloc[:s + 1], tag)
            if sig is None or s + 1 >= len(df):
                continue
            px = float(df["Open"].iloc[s + 1])
            stop = m.elder_b3_initial_stop(px, sig)
            assert stop is not None and (stop < px if direction == "long" else stop > px)


def test_replay_merge_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNTHETIC", "1")
    monkeypatch.setenv("SYMBOL_LIMIT", "1")
    monkeypatch.setenv("FAMILY", "osc_rev")
    rp.run()
    out = rp.merge(str(tmp_path / "out"), str(tmp_path / "rows.json"))
    tags = {r["tag"] for r in out["rows"]}
    assert tags == set(rp.tags_for_sources(m, m.ELDER_B3_FAMILY_SOURCES["osc_rev"]))
    r = next(x for x in out["rows"] if x["tag"] == "osc__reversal_mr__long__1d__atr3_hi70_lo30_oscrsi__v1")
    assert r["research_tag"] == "osc__reversal__long__1d__atr3_hi70_lo30_oscrsi__v1"
    assert r["registry_tag"].endswith("_rn38211452647__v1")
    for k in ("pfnet", "pfgross", "win_pct", "n", "avg_held_hrs", "exit_reasons"):
        assert k in r
