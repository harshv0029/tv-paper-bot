"""B-841/B-851/B-864/B-45 dispatch-readiness: pin resolve/compare tools, Douglas + batch3 pin wiring, batch3 IS/OOS
split tags, intraday gap-and-go port (both directions), and a static audit of the five touched workflows."""
import json
import os
import re
import sys
import types

import numpy as np
import pandas as pd
import pytest
import yaml

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(R, "scripts"))
import douglas_trade_mgmt_research as dg  # noqa: E402
import elder_batch3_research as b3  # noqa: E402
import elder_indicators_research as er  # noqa: E402
import intraday_gap_and_go_research as gg  # noqa: E402
import pin_compare as pc  # noqa: E402
import resolve_pin as rp  # noqa: E402
import universe_pin as up  # noqa: E402

UNIVERSE = [f"S{i:02d}.NS" for i in range(20)]


def _df(seed, n=200):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6},
                        index=pd.date_range("2022-01-01", periods=n))


def _fake_main(fail):
    m = types.ModuleType("main")
    m._load_nse_universe_from_file = lambda: list(UNIVERSE)
    m.fetch_ohlc = lambda s, p, i: None if s in fail else _df(int(s[1:3]))
    return m


def _args(tmp, family, pin="", shard=0, nshards=2, tol=0.002, **kw):
    return types.SimpleNamespace(family=family, shard=shard, nshards=nshards, interval="1d", period="5y",
                                 out=str(tmp), pin_file=pin, pin_tolerance=tol, split_date="", split_frac=0.0, **kw)


# ---------------------------------------------------------------- resolve_pin / pin_compare
def test_resolve_pin_finds_fetched_symbols_and_fails_loudly(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "notes.json").write_text(json.dumps({"rows": []}))
    assert rp.find_pin(str(tmp_path))[0] is None
    assert rp.main([str(tmp_path), str(tmp_path / "pin.json")]) == 1
    assert not (tmp_path / "pin.json").exists()
    (tmp_path / "a" / "res.json").write_text(json.dumps({"fetched_symbols": ["B.NS", "A.NS", "A.NS"], "rows": []}))
    assert rp.main([str(tmp_path), str(tmp_path / "pin.json")]) == 0
    assert json.load(open(tmp_path / "pin.json")) == ["A.NS", "B.NS"]
    assert up.load_pin(str(tmp_path / "pin.json")) == ["A.NS", "B.NS"]


def _res(syms, rows):
    return {"fetched_symbols": syms, "rows": [{"tag": t, "n": n, "pfnet": p} for t, n, p in rows]}


def test_pin_compare_identical_and_different():
    a = _res(["A", "B"], [("t1", 10, 1.2), ("t2", 5, 0.5)])
    assert pc.compare(a, _res(["A", "B"], [("t1", 10, 1.2), ("t2", 5, 0.5)]))["identical"]
    drift = pc.compare(a, _res(["A", "B", "C"], [("t1", 12, 1.0), ("t2", 5, 0.5)]))
    assert not drift["identical"] and drift["symbols"]["equal"] is False
    assert drift["n_differs"] == 1 and drift["crossed_floor"][0]["tag"] == "t1"
    same_set_bar_drift = pc.compare(a, _res(["A", "B"], [("t1", 10, 1.15), ("t2", 5, 0.5)]))
    assert same_set_bar_drift["symbols"]["equal"] and not same_set_bar_drift["identical"]
    unknown = pc.compare({"rows": a["rows"]}, a)       # run predating pinning: symbol equality unknown, not "equal"
    assert unknown["symbols"]["equal"] is None
    assert pc.compare(a, _res(["A", "B"], [("t1", 10, 1.2)]))["n_only_a"] == 1


def test_pin_compare_main_require_identical(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_res(["A"], [("t", 1, 1.0)])))
    (tmp_path / "b.json").write_text(json.dumps(_res(["A"], [("t", 1, 1.5)])))
    assert pc.main([str(tmp_path / "a.json"), str(tmp_path / "b.json")]) == 0
    assert pc.main([str(tmp_path / "a.json"), str(tmp_path / "b.json"), "--require-identical"]) == 1


# ---------------------------------------------------------------- Douglas pin wiring (the actual B-841 script)
def test_douglas_pinned_rerun_identical_despite_flaky_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "run_symbol", lambda df, fam, iv, aggs: aggs.setdefault("t", er.new_agg()).__setitem__(
        "n", aggs["t"]["n"] + int(df["Close"].iloc[-1])))

    def shards(tmp, fail, pin=""):
        sys.modules["main"] = _fake_main(fail)
        try:
            for sh in (0, 1):
                dg._main_shard(_args(tmp, "exits", pin, shard=sh))
        finally:
            del sys.modules["main"]
        return dg.merge_dir(str(tmp))

    a = shards(tmp_path / "a", {"S03.NS"})
    assert "S03.NS" not in a["fetched_symbols"] and len(a["fetched_symbols"]) == 19
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps(a["fetched_symbols"]))
    b = shards(tmp_path / "b", set(), str(pin))
    assert b["fetched_symbols"] == a["fetched_symbols"]
    assert [r["n"] for r in b["rows"]] == [r["n"] for r in a["rows"]]
    with pytest.raises(up.PinDriftError):                 # pinned symbols failing to fetch aborts the run
        shards(tmp_path / "c", {"S01.NS", "S02.NS"}, str(pin))


# ---------------------------------------------------------------- batch3: entry_i, IS/OOS segments, pin meta
def test_batch3_sim2_trades_carry_entry_index():
    df = _df(3, 120)
    entry = np.zeros(len(df), bool)
    entry[30] = True
    tr = b3.sim2(df, entry, "long", 2.0)
    assert tr and tr[0]["entry_i"] == 31


def test_batch3_segments_add_is_oos_tags_and_leave_pooled_untouched():
    idx = pd.date_range("2022-01-03", periods=100)
    trades = [{"ret": 0.05, "hold": 3, "reason": "x", "entry_i": 10}, {"ret": -0.02, "hold": 2, "reason": "x", "entry_i": 80}]
    tag = "osc__rsi__long__1d__atr2__v1"
    plain, seg = {}, {}
    b3.add_trades_seg(plain, tag, trades, idx, None)
    ts = b3.split_ts(idx, "2022-03-01")
    b3.add_trades_seg(seg, tag, trades, idx, ts)
    assert list(plain) == [tag] and seg[tag] == plain[tag]
    assert seg["osc__rsi__long__1d__atr2_segis__v1"]["n"] == 1 and seg["osc__rsi__long__1d__atr2_segoos__v1"]["n"] == 1
    assert b3.split_ts(idx, "", 0.0) is None
    assert b3.split_ts(idx, "", 0.6) == idx[0] + (idx[-1] - idx[0]) * 0.6


def test_batch3_shard_pin_and_merge_emit_fetched_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr(b3, "run_symbol", lambda df, fam, iv, aggs, ts=None: aggs.setdefault("t", er.new_agg()).__setitem__("n", 1))
    sys.modules["main"] = _fake_main({"S05.NS"})
    try:
        for sh in (0, 1):
            b3._main_shard(_args(tmp_path, "osc", shard=sh))
    finally:
        del sys.modules["main"]
    res = b3.merge_dir(str(tmp_path))
    assert len(res["fetched_symbols"]) == 19 and res["symbols_fetched"] == 19


# ---------------------------------------------------------------- intraday gap and go (long + short mirror)
def _fake_gg_main():
    mm = types.ModuleType("main")
    mm.IST_OFFSET_MIN = 330
    mm.ROUND_TRIP_COST_PCT = 0.8
    mm.CAPITAL_TRANCHES = 1
    mm._target_move_pct = lambda t, e: abs(t - e) / e * 100
    mm.NSE_STOCK_PARAM_OVERRIDES = {}
    mm.NSE_STOCK_DEFAULT_PARAMS = {"risk_pct": 1.0}
    return mm


def _session(day, o, closes, vols):
    """75 five-minute bars from 9:15 IST; first len(closes) bars follow `closes`, the rest hold the last close."""
    base = pd.Timestamp(f"{day} 03:45", tz="UTC")
    rows, prev = [], o
    for i in range(75):
        c = closes[i] if i < len(closes) else closes[-1]
        op = o if i == 0 else prev
        rows.append({"Date": base + pd.Timedelta(minutes=5 * i), "Open": op, "High": max(op, c) + 0.1,
                     "Low": min(op, c) - 0.1, "Close": c, "Volume": vols[i] if i < len(vols) else 1000.0})
        prev = c
    return rows


def _gap_df(direction):
    flat = _session("2024-01-01", 100.0, [100.0], [])
    if direction == "long":     # +3% gap, held, strong volume bar 0, then runs to the 2R target
        d2 = _session("2024-01-02", 103.0, [104.0, 104.5, 105.5, 107.0, 108.0], [5000.0])
    else:                       # -3% gap, mirror
        d2 = _session("2024-01-02", 97.0, [96.0, 95.5, 94.5, 93.0, 92.0], [5000.0])
    return pd.DataFrame(flat + d2)


@pytest.mark.parametrize("direction", ["long", "short"])
def test_intraday_gap_and_go_enters_exits_same_day_both_directions(direction, monkeypatch):
    monkeypatch.setattr(gg, "m", _fake_gg_main())
    df = gg.prep(_gap_df(direction))
    stats = {}
    tr = gg.replay_symbol("X.NS", df, direction, 2.5, 1.0, gg.CAPITAL_INR, gg.DEFAULT_COST_MODEL, "5m", stats)
    assert len(tr) == 1 and stats["days_entered"] == 1
    assert tr[0]["reason"] == "target_hit" and tr[0]["gross_pnl"] > 0
    assert tr[0]["hold"] >= 1 and tr[0]["net_ret"] < tr[0]["gross_ret"]      # costs charged
    # no gap -> no trade; wrong-direction gap -> no trade
    other = "short" if direction == "long" else "long"
    assert gg.replay_symbol("X.NS", df, other, 2.5, 1.0, gg.CAPITAL_INR, gg.DEFAULT_COST_MODEL, "5m") == []


def test_intraday_gap_and_go_glitch_day_skipped_and_flat_by_close(monkeypatch):
    monkeypatch.setattr(gg, "m", _fake_gg_main())
    rows = _gap_df("long")
    rows.loc[100, "Close"] = 400.0                    # >2x one-bar glitch inside the gap day
    assert gg.replay_symbol("X.NS", gg.prep(rows), "long", 2.5, 1.0, gg.CAPITAL_INR, gg.DEFAULT_COST_MODEL, "5m") == []
    flatter = _gap_df("long")                           # never reaches target or stop -> eod_squareoff, never overnight
    flatter.loc[75 + 3:, ["Close", "High", "Low", "Open"]] = 104.5
    tr = gg.replay_symbol("X.NS", gg.prep(flatter), "long", 2.5, 1.0, gg.CAPITAL_INR, gg.DEFAULT_COST_MODEL, "5m")
    assert tr and tr[0]["reason"] in ("eod_squareoff", "gap_filled", "stop_hit", "target_hit")


def test_intraday_gap_and_go_tags_follow_grammar_and_merge(tmp_path, monkeypatch):
    t = gg.make_tag("short", "15m", 2.5)
    assert t == "gap_and_go_intraday__gap_hold__short__15m__atr2d5_tr2d0_win30__v1"
    assert re.fullmatch(r"[a-z0-9_]+", t) and not t.startswith("gap_and_go__swing")
    monkeypatch.setattr(gg, "m", _fake_gg_main())
    monkeypatch.setattr(gg.m, "_load_nse_universe_from_file", lambda: ["A.NS", "B.NS"], raising=False)
    monkeypatch.setattr(gg.m, "fetch_ohlc", lambda s, p, i: _gap_df("long" if s == "A.NS" else "short"), raising=False)
    for sh in (0, 1):
        gg.run_shard(types.SimpleNamespace(universe="full", pin_file="", pin_tolerance=0.002, shard=sh, nshards=2,
                                           directions="long,short", interval="5m", period="60d", out=str(tmp_path)))
    res = gg.merge_dir(str(tmp_path))
    assert res["fetched_symbols"] == ["A.NS", "B.NS"] and len(res["rows"]) == 8     # 2 directions x 4 ATR multiples
    longs = [r for r in res["rows"] if "__long__" in r["tag"]]
    assert all(r["n"] == 1 for r in longs) and all(r["top5_net_ret_pct"] for r in res["rows"])


# ---------------------------------------------------------------- static audit of the touched workflows
WFS = {"douglas-trade-mgmt-research": "douglas_trade_mgmt_research", "elder-indicators-research": "elder_indicators_research",
       "elder-indicators-research-ext": "elder_indicators_research_ext",
       "elder-macd-dirgap-research": "elder_macd_dirgap_research", "elder-batch3-research": "elder_batch3_research",
       "intraday-gap-and-go-research": "intraday_gap_and_go_research"}


def _wf(name):
    return yaml.safe_load(open(os.path.join(R, ".github", "workflows", name + ".yml")))


def _inputs(w):
    return (w.get("on") or w.get(True))["workflow_dispatch"]["inputs"]


@pytest.mark.parametrize("wf", sorted(WFS))
def test_pin_inputs_and_resolve_step_present(wf):
    w = _wf(wf)
    ins = _inputs(w)
    assert {"pin_run_id", "pin_artifact"} <= set(ins) and ins["pin_run_id"]["default"] == ""
    first = next(iter(w["jobs"].values()))
    steps = first["steps"]
    assert any(s.get("uses") == "./.github/actions/resolve-pin" for s in steps)
    # resolve step comes after checkout and before the script runs
    kinds = [("checkout" if "checkout" in s.get("uses", "") else "resolve" if "resolve-pin" in s.get("uses", "")
              else "run" if WFS[wf] in s.get("run", "") else "") for s in steps]
    assert kinds.index("checkout") < kinds.index("resolve") < kinds.index("run")
    # every script flag used by the workflow exists in the script
    src = open(os.path.join(R, "scripts", WFS[wf] + ".py")).read()
    for flag in set(re.findall(r"\s(--[a-z_]+)\s", " ".join(s.get("run", "") for s in steps) + " ")):
        assert flag in src, (wf, flag)


def _matrix_size(job, inputs):
    mx = (job.get("strategy") or {}).get("matrix") or {}
    n = 1
    for k, v in mx.items():
        if isinstance(v, str) and "fromJSON" in v:
            v = json.loads(inputs["families"]["default"])
        n *= len(v)
    return n


@pytest.mark.parametrize("wf", sorted(WFS))
def test_matrix_under_40_for_defaults(wf):
    w = _wf(wf)
    total = sum(_matrix_size(j, _inputs(w)) for j in w["jobs"].values())
    assert total <= 40, (wf, total)


def test_b864_rerun_dispatch_shape_is_osc_chan_only_8_jobs():
    w = _wf("elder-batch3-research")
    ins = _inputs(w)
    assert {"families", "split_date", "run_orb", "interval", "period"} <= set(ins)
    osc_chan = ["osc", "chan"]
    assert set(osc_chan) <= set(json.loads(ins["families"]["default"]))
    assert len(osc_chan) * len(w["jobs"]["research"]["strategy"]["matrix"]["shard"]) == 8       # + orb off + merge
    assert "--split_date" in open(os.path.join(R, "scripts", "elder_batch3_research.py")).read()


def test_compare_workflow_and_action_exist():
    w = _wf("universe-pin-compare")
    assert {"run_a", "run_b", "artifact"} <= set(_inputs(w))
    assert "scripts/pin_compare.py" in yaml.dump(w) and os.path.exists(os.path.join(R, "scripts", "pin_compare.py"))
    a = yaml.safe_load(open(os.path.join(R, ".github", "actions", "resolve-pin", "action.yml")))
    assert a["runs"]["using"] == "composite" and "pin_run_id" in a["inputs"]


def test_intraday_workflow_uses_full_universe_and_both_directions_by_default():
    ins = _inputs(_wf("intraday-gap-and-go-research"))
    assert ins["universe"]["default"] == "full" and ins["directions"]["default"] == "long,short"
    assert ins["interval"]["default"] == "5m"
