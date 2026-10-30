"""B-1417: band_cap (live resting-stop model) replay of every other LIVE swing family, off vs live on the SAME data.

Each family job loads its frames once and replays every live tag twice through that family's own main.py replay
(scripts/swing_classic_main_replay.py, brk20_replay.py, chan_shape_macddiv_main_replay.py, swing_short_main_replay.py;
all call the REAL main.py entry/exit functions): once with band_cap=off (the existing result) and once with the chosen
mode (default live, scripts/swing_bandcap.py). Pure entry signals are memoised per symbol and shared by both passes
(swing_bandcap.MemoMain), so the second pass costs only the exits.

Families (FAMILY env):
  power_play, primary_base, gap_and_go, oneil  -> swing_classic_main_replay (daily, live fns, oneil = the 1w live cells
                                                  on daily bars as the live engine runs them)
  brk20        -> brk20_replay, LONG 1d, cell main.BRK20_SWING_ATR_MULT x main.BRK20_SWING_MIN_RR (= main.BRK20_SWING_TAG)
  chan_shape   -> chan_shape_macddiv_main_replay, main.CHAN_SHAPE_CELLS (1d)
  macddiv      -> chan_shape_macddiv_main_replay, main.MACDDIV_LONG_CELLS (1h; the daily band off the previous session)
  short_swing  -> swing_short_main_replay, main.SHORT_SWING_TAGS (1d brk20 short cells, BUY stop, band CEILING)
B-1426 additions (each live-wired in main._run_swing_scan_pass; tags exactly as the live scan iterates them):
  island       -> island_main_replay, the strict-FIFO tags of main.ISLAND_ALL_TAGS (gap05 nonovl + ISLAND_SWING_TAGS;
                  the v1 / segis / segoos rows are reporting views of the same rules and never own a live position)
  gapfade      -> gapfade_main_replay, main.GAPFADE_TAGS (1d, glitch bars cleaned as in its baseline replay)
  pl1d         -> pl1d_main_replay, main.PL1D_CELLS (1d, cleaned)
  swingminrr   -> swing_short_main_replay, main.SWINGMINRR_TAGS (VCP long 1d, the exact minervini_vcp prefilter gate)
  tasuki_short -> tasuki_swingminrr_short_main_replay, main.TASUKI_SHORT_CELLS (1d, ETF universe, BUY stop, CEILING)
  swm1h_short  -> tasuki_swingminrr_short_main_replay, main.SWINGMINRR_SHORT_1H_CELLS (1h, daily band, CEILING)
  envelope     -> envelope_main_replay, main.ENVELOPE_LONG_LIVE_CELLS (1h, cleaned, daily band off the prior session)
  cup_cheat    -> cup_cheat_main_replay, main.CUP_CHEAT_LONG_LIVE_CELLS (1h, cleaned)
Universe = main._load_nse_universe_from_file() (full). Cost = main.ROUND_TRIP_COST_PCT (0.8% round trip).

Modes: run   (env FAMILY, SHARD, NSHARDS, BAND_CAP, SYMBOL_LIMIT, SYNTHETIC=1 smoke) -> out/bandcap_<family>_s<shard>.json
       merge <dir> [out.json]  -> pooled per tag and mode; prints one summary line per tag (n, win %, PFnet off vs
                                  live) and one `RESULTS_JSON: {...}` line.
"""
import glob
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAMILIES = ("power_play", "primary_base", "gap_and_go", "oneil", "brk20", "chan_shape", "macddiv", "short_swing",
            "island", "gapfade", "pl1d", "swingminrr", "tasuki_short", "swm1h_short", "envelope", "cup_cheat")
CLASSIC = ("power_play", "primary_base", "gap_and_go", "oneil")  # == swing_classic_main_replay.FAMILIES (tested)
MEMO_FNS = ("power_play_entry_signal", "primary_base_entry_signal", "gap_and_go_entry_signal", "oneil_swing_entry_signal",
            "brk20_min_rr_entry_signal", "chan_shape_long_entry_signal", "macddiv_long_cell_signal",
            # B-1426
            "island_bottom_signal_on_last_bar", "island_swing_entry_signal", "gapfade_long_entry_signal",
            "pl1d_long_entry_signal", "minervini_vcp_entry_signal", "swingminrr_vcp_entry_signal",
            "tasuki_short_signal", "swingminrr_gate_short_entry_signal", "envelope_fade_entry_signal",
            "cup_cheat_3c_fires", "cup_cheat_3c_entry_signal")
TSM_GROUP = {"tasuki_short": "tasuki", "swm1h_short": "swm1h"}  # driver family -> tasuki_swingminrr_short GROUP
br = cs = bc = cl = ss = ir = gf = pl = tsm = env = cup = bh = None


def _load_mods():
    """Heavy imports (numpy/pandas via the family replays) only for run/merge, so `plan` runs on a bare runner."""
    global br, cs, bc, cl, ss, ir, gf, pl, tsm, env, cup, bh
    import bar_hygiene as bh  # noqa: F811
    import cup_cheat_main_replay as cup  # noqa: F811
    import envelope_main_replay as env  # noqa: F811
    import gapfade_main_replay as gf  # noqa: F811
    import island_main_replay as ir  # noqa: F811
    import pl1d_main_replay as pl  # noqa: F811
    import tasuki_swingminrr_short_main_replay as tsm  # noqa: F811
    import brk20_replay as br  # noqa: F811
    import chan_shape_macddiv_main_replay as cs  # noqa: F811
    import swing_bandcap as bc  # noqa: F811
    import swing_classic_main_replay as cl  # noqa: F811
    import swing_short_main_replay as ss  # noqa: F811


def parse_families(spec):
    s = (spec or "all").strip()
    if s in ("", "all"):
        return list(FAMILIES)
    fams = [f.strip() for f in s.split(",") if f.strip()]
    bad = [f for f in fams if f not in FAMILIES]
    if bad:
        raise SystemExit(f"unknown families {bad}; expected {FAMILIES}")
    return fams


def plan(env=None):
    e = os.environ if env is None else env
    fams = parse_families(e.get("STRATEGIES"))
    ns = int(e.get("NSHARDS") or 4)
    return {"include": [{"family": f, "shard": s, "nshards": ns} for f in fams for s in range(ns)]}


def family_tags(m, family):
    if family in CLASSIC:
        return cl.tags_for(m, family)
    if family == "brk20":
        return [m.BRK20_SWING_TAG]
    if family in ("chan_shape", "macddiv"):
        return cs.tags_for(m, family)
    if family == "island":
        return [t for t in m.ISLAND_ALL_TAGS if ir.mode_of(t) == "fifo"]
    live = {"gapfade": "GAPFADE_TAGS", "pl1d": "PL1D_CELLS", "swingminrr": "SWINGMINRR_TAGS",
            "tasuki_short": "TASUKI_SHORT_CELLS", "swm1h_short": "SWINGMINRR_SHORT_1H_CELLS",
            "envelope": "ENVELOPE_LONG_LIVE_CELLS", "cup_cheat": "CUP_CHEAT_LONG_LIVE_CELLS"}
    if family in live:
        return list(getattr(m, live[family]))
    return list(m.SHORT_SWING_TAGS)


def load(m, family, shard, nshards, limit):
    if family in CLASSIC:
        return cl.load_frames(m, shard, nshards, limit)
    if family == "brk20":
        if os.environ.get("SYNTHETIC") == "1":
            return {f"SYN{k}": br.synthetic_frame(k) for k in range(limit or 3)}
        return br.load_frames(m, "1d", shard, nshards, limit)
    if family in ("chan_shape", "macddiv"):
        return cs.load_frames(m, family, shard, nshards, limit)
    if family == "island":
        return ir.load_frames(m, "1d", "5y", shard, nshards, limit)
    # same loaders + bar-hygiene cleaning as each family's own baseline replay, so band_cap=off reproduces it
    if family == "gapfade":
        return bh.clean_frames(br.load_frames(m, "1d", shard, nshards, limit))[0]
    if family == "pl1d":
        return bh.clean_frames(cs.load_frames(m, "chan_shape", shard, nshards, limit))[0]
    if family in ("envelope", "cup_cheat"):
        return bh.clean_frames(cs.load_frames(m, "macddiv", shard, nshards, limit))[0]
    if family in TSM_GROUP:
        return tsm.load_frames(m, TSM_GROUP[family], shard, nshards, limit)
    return ss.load_frames(m, shard, nshards, limit)


def replay(m, family, df, tags, cost, mode):
    """{tag: trades} for one symbol, one band mode, via the family's own replay (real main.py fns)."""
    if family in CLASSIC:
        return {t: cl.replay_symbol(m, df, family, t, cost, mode) for t in tags}
    if family == "brk20":
        assert br.make_tag("long", "1d", m.BRK20_SWING_ATR_MULT, m.BRK20_SWING_MIN_RR) == m.BRK20_SWING_TAG
        return {tags[0]: br.replay_symbol(m, df, "long", m.BRK20_SWING_ATR_MULT, m.BRK20_SWING_MIN_RR, None, cost, mode)}
    if family in ("chan_shape", "macddiv"):
        return cs.replay_symbol(m, df, family, tags, cost, mode)
    if family == "island":
        return ir.replay_symbol(m, df, tags, cost, None, mode)
    if family == "gapfade":
        return gf.replay_symbol(m, df, tags, cost, mode)
    if family == "pl1d":
        return pl.replay_symbol(m, df, tags, cost, mode)
    if family == "envelope":
        return env.replay_symbol(m, df, tags, cost, mode)
    if family == "cup_cheat":
        return cup.replay_symbol(m, df, tags, cost, "long", mode)
    if family in TSM_GROUP:
        specs = tsm.tag_specs(m)
        return {t: tsm.replay_symbol(m, df, t, specs[t], cost, "signal_close", mode) for t in tags}
    specs = ss.tag_specs(m)
    if family == "swingminrr":
        # the exact prefilter swing_short_main_replay.run uses: swingminrr_vcp_entry_signal is None whenever
        # minervini_vcp_entry_signal is (rs=None). Memoised by MemoMain, so the off and live passes share it.
        def gate(sub):
            return bool(m.minervini_vcp_entry_signal(sub))
        return {t: ss.replay_symbol(m, df, t, specs[t], cost, "signal_close", gate, mode) for t in tags}
    return {t: ss.replay_symbol(m, df, t, specs[t], cost, "signal_close", None, mode) for t in tags}


def run():
    _load_mods()
    import main as real
    family = os.environ.get("FAMILY", "power_play")
    if family not in FAMILIES:
        raise SystemExit(f"bad family {family}")
    mode = bc.mode_from_env()
    modes = ["off"] + ([mode] if mode != "off" else [])
    shard, nshards = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    limit = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    cost = real.ROUND_TRIP_COST_PCT / 100.0
    m = bc.MemoMain(real, MEMO_FNS)
    tags = family_tags(real, family)
    frames = load(real, family, shard, nshards, limit)
    aggs = {md: {t: br.agg_new() for t in tags} for md in modes}
    for sym, df in frames.items():
        m.reset()
        for md in modes:
            try:
                res = replay(m, family, df, tags, cost, md)
            except Exception as ex:
                print("ERROR", sym, md, ex)
                continue
            for t, trs in res.items():
                br.agg_add(aggs[md][t], trs)
    out = {"family": family, "shard": shard, "nshards": nshards, "n_symbols": len(frames),
           "cost_round_trip_pct": real.ROUND_TRIP_COST_PCT, "synthetic": os.environ.get("SYNTHETIC") == "1",
           "modes": {md: {t: a for t, a in aggs[md].items()} for md in modes}}
    os.makedirs("out", exist_ok=True)
    path = f"out/bandcap_{family}_s{shard}.json"
    json.dump(out, open(path, "w"), indent=1)
    for md in modes:
        for t, a in aggs[md].items():
            mt = br.agg_metrics(a)
            print(md, bc.band_tag(t, md), "n", mt["n"], "pfnet", mt["pfnet"], "win", mt["win_pct"])
    print("wrote", path)


def _fmt(v, nd=3):
    return "NA" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def merge(d, out_path=None):
    _load_mods()
    pooled, fam_of, nsym = {}, {}, {}
    for f in sorted(glob.glob(os.path.join(d, "**", "bandcap_*_s*.json"), recursive=True)):
        r = json.load(open(f))
        for md, cells in r["modes"].items():
            for t, raw in cells.items():
                br.agg_merge(pooled.setdefault((t, md), br.agg_new()), raw)
                fam_of[t] = r["family"]
                if md == "off":
                    nsym[t] = nsym.get(t, 0) + r["n_symbols"]
    rows = []
    for t in sorted({t for t, _ in pooled}, key=lambda x: (fam_of[x], x)):
        live_modes = sorted(md for tt, md in pooled if tt == t and md != "off")
        off = br.agg_metrics(pooled[(t, "off")]) if (t, "off") in pooled else None
        for md in live_modes or [None]:
            live = br.agg_metrics(pooled[(t, md)]) if md else None
            rows.append({"tag": t, "family": fam_of[t], "band_cap": md, "band_tag": bc.band_tag(t, md or "off"),
                         "n_symbols": nsym.get(t, 0), "off": off, "live": live})
    res = {"backlog": "B-1417/B-1426", "cost_round_trip_pct": 0.8, "run_id": os.environ.get("GITHUB_RUN_ID"),
           "universe": "main._load_nse_universe_from_file() (full NSE)", "rows": rows}
    json.dump(res, open(out_path or os.path.join(d, "swing_bandcap_all.json"), "w"), indent=1)
    print("SUMMARY tag | n off/live | win% off/live | PFnet off/live | live tag")
    for r in rows:
        o, lv = r["off"] or {}, r["live"] or {}
        print(f"{r['tag']} | n {o.get('n')}/{lv.get('n')} | win {_fmt(o.get('win_pct'), 1)}/{_fmt(lv.get('win_pct'), 1)}"
              f" | PFnet {_fmt(o.get('pfnet'))}/{_fmt(lv.get('pfnet'))} | {r['band_tag']}")
    print("RESULTS_JSON: " + json.dumps(res, separators=(",", ":")))
    return res


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        print(json.dumps(plan()))
    else:
        run()
