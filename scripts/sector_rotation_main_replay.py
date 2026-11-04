"""B-1467: sector_rotation main.py-function replay, all four (variant, direction) combos, strict one position per symbol.

The ~100 viable-but-unwired sector_rotation__* registry cells were measured by scripts/sector_rotation_backtest.py (a
research harness: independent overlapping trades). This replay calls the REAL main functions for every decision:
  picks : main.sector_rotation_cell_picks(dfs_upto_t, variant, direction, L, N)  (strong side = sector_rotation_picks,
          weak side = sector_rotation_weak_picks), bars <= t only (walk-forward)
  ATR   : main._atr_series(df, 14) per symbol, read at the signal bar t
  stop  : main.sector_rotation_cell_stop(entry, atr_t, k, direction)  (None = no entry: SL on every trade; atrnone refused)
  exit  : main.sector_rotation_cell_exit_reason(bars_from_entry, stop, H, direction, fill)
The driver supplies only the bar loop: signal at the close of bar t, entry at bar t+1 open (ENTRY=next_open, the research
convention) or the signal close (ENTRY=signal_close, own `_ec1` tags), STRICT one open position per symbol per cell (a
signal while that symbol's previous trade is still open is skipped; next entry allowed the bar after the exit), both
directions for every (side, L, N) group a viable cell needs (so every cell also gets its mirror), three stop-fill models,
IS/OOS split by entry bar (first 70% of the panel = IS). Cost = main.ROUND_TRIP_COST_PCT/100 per trade (0.8%). Universe =
main._load_nse_universe_from_file() (never main.NSE_FULL_UNIVERSE), sector-mapped symbols only (docs/sector_map.json,
what main reads); UNI=n200 restricts to main.SWING_WATCHLIST like the research `_n200` variant. Vendor glitch bars are
dropped first (scripts/bar_hygiene.clean_frames).

New tags (naming grammar, never pooled with the research tags):
  sector_rotation__<variant>[_n200]_main1p__<dir>__<tf>__atr<k>[_ec1]_fl<stop|gap|close>_h<H>_l<L>_n<N>__v1
`main1p` = main.py-calling replay, one position per symbol. `source_tag` names the research cell it re-measures.

Modes (argv[1]):
  plan   -> JSON matrix {"include": [{tf, uni, groups}]}, derived from strategy_registry at dispatch time: viable now
            (is_viable()) AND not scan-wired (absent from main._STRATEGY_TAG_TO_REGISTRY_NAME values). Never a stored flag.
  run    env TF (1d|4h|1h|15m), UNI ("" | n200), SECTOR_GROUPS ("strong_l3_n1_h1-5-10,weak_l5_n5_h20"), ATRS
         ("1d5,2d5,4d0,6d0"), ENTRY, NAME, SYMBOL_LIMIT, SYNTHETIC=1 (offline smoke, NOT a result)
         -> out/sector_main_replay_<NAME>.json
  merge  DIR OUT.json -> one file {rows: [{tag, source_tag, metrics{n,pfnet,...,is,oos}}]}: the schema
         main._replay_verified_tags() reads (commit as docs/backtest_data/sector_rotation_main_replay_run_<id>.json).
"""
import glob
import json
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import b412_helpers as H  # noqa: E402

TAG_RE = re.compile(r"^sector_rotation__(?P<var>momentum|fade)(?P<uni>_n200)?__(?P<dir>long|short)__(?P<tf>1d|4h|1h|15m|5m)"
                    r"__atr(?P<atr>[a-z0-9]+)_h(?P<h>\d+)_l(?P<l>\d+)_n(?P<n>\d+)__v1$")
FILLS = ("stop", "gap_aware", "close")
FILL_TOK = {"stop": "stop", "gap_aware": "gap", "close": "close"}
DEFAULT_ATRS = ("1d5", "2d5", "4d0", "6d0")
BAR_HOURS = {"1d": 6.25, "4h": 3.5, "1h": 1.0, "15m": 0.25, "5m": 5 / 60}
PERIOD = {"1d": "5y", "1h": "730d", "15m": "60d", "5m": "60d"}
MIN_BARS = {"1d": 260, "4h": 400, "1h": 400, "15m": 400, "5m": 400}
IS_FRAC = 0.7
ENTRY_MODELS = ("next_open", "signal_close")


# ------------------------------------------------------------------ pure helpers
def parse_atr(tok):
    return None if tok == "none" else float(tok.replace("d", "."))


def parse_tag(tag):
    m = TAG_RE.match(tag)
    if not m:
        return None
    return {"var": m["var"], "uni": "n200" if m["uni"] else "", "dir": m["dir"], "tf": m["tf"], "atr_tok": m["atr"],
            "hold": int(m["h"]), "L": int(m["l"]), "N": int(m["n"])}


def side_of(var, direction):
    return "strong" if (var == "momentum") == (direction == "long") else "weak"


def new_tag(var, uni, direction, tf, atr_tok, fill, hold, L, N, entry="next_open"):
    ec = "_ec1" if entry == "signal_close" else ""
    v = var + ("_n200" if uni == "n200" else "")
    return f"sector_rotation__{v}_main1p__{direction}__{tf}__atr{atr_tok}{ec}_fl{FILL_TOK[fill]}_h{hold}_l{L}_n{N}__v1"


def research_tag(var, uni, direction, tf, atr_tok, hold, L, N):
    v = var + ("_n200" if uni == "n200" else "")
    return f"sector_rotation__{v}__{direction}__{tf}__atr{atr_tok}_h{hold}_l{L}_n{N}__v1"


def build_plan(registry, wired):
    """Jobs per (tf, uni); groups per (side, L, N) with the union of the viable cells' holds. Both directions of a group
    are replayed (mirror), with every stop multiple in DEFAULT_ATRS plus the cell's own; atrnone cells are replayed only
    with stops (listed in `stop_substituted`). Unparsable viable cells are listed in `skipped`, never dropped silently."""
    jobs, skipped, subst = {}, [], []
    for s in registry:
        if not s.name.startswith("sector_rotation__") or s.is_viable() is not True or s.name in wired:
            continue
        c = parse_tag(s.name)
        if c is None:
            skipped.append({"tag": s.name, "why": "tag outside the sector_rotation grammar this replay parses"})
            continue
        if c["atr_tok"] == "none":
            subst.append(s.name)
        j = jobs.setdefault((c["tf"], c["uni"]), {"groups": {}, "atrs": set(DEFAULT_ATRS)})
        if c["atr_tok"] != "none":
            j["atrs"].add(c["atr_tok"])
        j["groups"].setdefault((side_of(c["var"], c["dir"]), c["L"], c["N"]), set()).add(c["hold"])
    inc = []
    for (tf, uni), j in sorted(jobs.items()):
        groups = ",".join(f"{sd}_l{L}_n{N}_h{'-'.join(str(h) for h in sorted(hs))}" for (sd, L, N), hs in sorted(j["groups"].items()))
        inc.append({"tf": tf, "uni": uni, "name": f"{tf}{'_' + uni if uni else ''}", "groups": groups,
                    "atrs": ",".join(sorted(j["atrs"], key=parse_atr))})
    return {"include": inc, "skipped": skipped, "stop_substituted": subst}


def parse_groups(spec):
    out = []
    for tok in [t.strip() for t in spec.split(",") if t.strip()]:
        m = re.match(r"^(strong|weak)_l(\d+)_n(\d+)_h([\d-]+)$", tok)
        if not m:
            raise ValueError(f"bad group {tok!r}")
        out.append({"side": m[1], "L": int(m[2]), "N": int(m[3]), "holds": [int(h) for h in m[4].split("-")]})
    return out


class _Col:
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a

    def to_numpy(self, dtype=float):
        return self.a


class _View:
    """Prefix view (bars <= t) of one symbol's closes: the real pick functions only read len(df) and df['Close']."""
    __slots__ = ("c",)

    def __init__(self, c):
        self.c = c

    def __len__(self):
        return len(self.c)

    def __getitem__(self, k):
        assert k == "Close"
        return _Col(self.c)


def build_panel(m, frames):
    """Union-date panels (T x S) of O/H/L/C and ATR14 from the real main._atr_series per symbol."""
    syms = sorted(frames)
    dates = sorted(set().union(*[set(f["Date"].astype(str)) for f in frames.values()])) if frames else []
    ix = {d: i for i, d in enumerate(dates)}
    T, S = len(dates), len(syms)
    P = {k: np.full((T, S), np.nan) for k in ("O", "H", "L", "C", "ATR")}
    for j, s in enumerate(syms):
        f = frames[s]
        rows = np.array([ix[d] for d in f["Date"].astype(str)])
        for k, col in (("O", "Open"), ("H", "High"), ("L", "Low"), ("C", "Close")):
            P[k][rows, j] = f[col].to_numpy(float)
        P["ATR"][rows, j] = m._atr_series(f, 14).to_numpy(float)
    return syms, dates, P


def compute_signals(m, syms, C, groups):
    """{(side, L): [(t, j, rank)]} from the REAL main pick fns at N = max N of that (side, L) (top/bottom-N is a prefix
    of the sorted list, so smaller N are exact prefixes). Signal bars t in [L+15, T-3] (research range); main's own
    len(df) >= 20 check decides the earliest real signal."""
    T = C.shape[0]
    col = {s: j for j, s in enumerate(syms)}
    need = {}
    for g in groups:
        need[(g["side"], g["L"])] = max(need.get((g["side"], g["L"]), 0), g["N"])
    sigs = {k: [] for k in need}
    var_dir = {"strong": ("momentum", "long"), "weak": ("momentum", "short")}
    for t in range(min(L for _, L in need) + 15 if need else T, T - 2):
        dfs = None
        for (side, L), Nmax in need.items():
            if t < L + 15:
                continue
            if dfs is None:
                dfs = {s: _View(C[:t + 1, j]) for j, s in enumerate(syms)}
            v, d = var_dir[side]
            for r, s in enumerate(m.sector_rotation_cell_picks(dfs, v, d, L, Nmax)):
                sigs[(side, L)].append((t, col[s], r))
    return sigs


def simulate(m, P, sig_list, N, direction, atr_mult, hold, fill, cost, entry="next_open", one_position=True):
    """Trades for one cell. Research boundary kept: entry bar e = t+1 needs e + hold < T. Returns trade dicts with e."""
    O, H_, L_, C, ATR = P["O"], P["H"], P["L"], P["C"], P["ATR"]
    T = C.shape[0]
    busy = {}
    out = []
    for t, j, rank in sig_list:
        if rank >= N:
            continue
        e = t + 1
        if e + hold >= T:
            continue
        if one_position and busy.get(j, -1) >= e:
            continue
        ent = C[t, j] if entry == "signal_close" else O[e, j]
        a = ATR[t, j]
        if np.isnan(ent) or np.isnan(a) or ent <= 0:
            continue
        stop = m.sector_rotation_cell_stop(ent, a, atr_mult, direction)  # REAL; None = no entry (SL on every trade)
        if stop is None:
            continue
        win = {"Open": O[e:e + hold, j], "High": H_[e:e + hold, j], "Low": L_[e:e + hold, j], "Close": C[e:e + hold, j]}
        r = m.sector_rotation_cell_exit_reason(win, stop, hold, direction, fill)  # REAL exit
        if r is None:
            continue
        reason, px, held = r
        g = (px / ent - 1) if direction == "long" else (1 - px / ent)
        out.append({"gross": g, "net": g - cost, "held": held, "reason": reason, "e": e})
        busy[j] = e + held - 1  # last bar the position is open; next entry allowed from the bar after
    return out


def cell_metrics(trades, T, bar_hours):
    split = int(T * IS_FRAC)
    mt = H.metrics(trades)
    mt["avg_held_hours"] = round(mt["avg_held_bars"] * bar_hours, 2)
    for k, sel in (("is", [x for x in trades if x["e"] < split]), ("oos", [x for x in trades if x["e"] >= split])):
        sub = H.metrics(sel)
        sub["avg_held_hours"] = round(sub["avg_held_bars"] * bar_hours, 2)
        mt[k] = sub
    mt["is_oos_split_bar"] = split
    return mt


def run_cells(m, frames, groups, atrs, tf, uni="", entry="next_open", one_position=True, fills=FILLS):
    """Core (no I/O): rows for every (group, direction, atr, hold, fill)."""
    if entry not in ENTRY_MODELS:
        raise ValueError(f"entry must be one of {ENTRY_MODELS}")
    for a in atrs:
        if parse_atr(a) is None:
            raise ValueError("atrnone refused: no trade without SL")
    smap = m._sector_of_symbol()
    frames = {s: f for s, f in frames.items() if smap.get(s)}
    syms, dates, P = build_panel(m, frames)
    T = len(dates)
    cost = m.ROUND_TRIP_COST_PCT / 100.0
    sigs = compute_signals(m, syms, P["C"], groups)
    rows = []
    for g in groups:
        sl = sigs[(g["side"], g["L"])]
        for direction in ("long", "short"):
            var = "momentum" if side_of("momentum", direction) == g["side"] else "fade"
            for a in atrs:
                for hold in g["holds"]:
                    for fill in fills:
                        tr = simulate(m, P, sl, g["N"], direction, parse_atr(a), hold, fill, cost, entry, one_position)
                        rows.append({"tag": new_tag(var, uni, direction, tf, a, fill, hold, g["L"], g["N"], entry),
                                     "source_tag": research_tag(var, uni, direction, tf, a, hold, g["L"], g["N"]),
                                     "variant": var, "direction": direction, "tf": tf, "uni": uni or "full",
                                     "atr": a, "fill": fill, "hold_bars": hold, "L": g["L"], "N": g["N"], "entry": entry,
                                     "one_position_per_symbol": bool(one_position),
                                     "metrics": cell_metrics(tr, T, BAR_HOURS[tf])})
    return {"rows": rows, "universe_size": len(frames), "bars": T,
            "first_bar": dates[0] if dates else None, "last_bar": dates[-1] if dates else None}


# ------------------------------------------------------------------ data
def synthetic_frame(seed, n=500, tf="1d"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, n)))
    o = c * (1 + rng.normal(0, 0.004, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    d = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": hi, "Low": lo, "Close": c,
                         "Volume": rng.integers(1e5, 1e6, n).astype(float)})


def fetch_tf(m, sym, tf):
    if tf == "4h":
        import resample_4h as r4
        raw = m.fetch_ohlc(sym, "730d", "1h")
        if raw is None or len(raw) == 0:
            return None
        ix = raw.set_index(pd.DatetimeIndex(raw["Date"]))
        out = r4.resample_1h_to_4h(ix[["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in ix.columns else [])]).copy()
        out.insert(0, "Date", out.index)
        return out.reset_index(drop=True)
    return m.fetch_ohlc(sym, PERIOD[tf], tf)


def load_frames(m, tf, uni, limit=None):
    if os.environ.get("SYNTHETIC") == "1":
        smap = m._sector_of_symbol()
        syms = sorted(smap)[:limit or 40]
        return {s: synthetic_frame(k, 500) for k, s in enumerate(syms)}
    syms = sorted(set(m._load_nse_universe_from_file()))
    if uni == "n200":
        w = set(m.SWING_WATCHLIST)
        syms = [s for s in syms if s in w]
    smap = m._sector_of_symbol()
    syms = [s for s in syms if smap.get(s)]
    if limit:
        syms = syms[:limit]
    out = {}
    for s in syms:
        try:
            raw = fetch_tf(m, s, tf)
        except Exception:
            continue
        if raw is None or len(raw) < MIN_BARS[tf]:
            continue
        out[s] = raw.reset_index(drop=True)
    return out


def run():
    import main as m
    import bar_hygiene as bh
    tf, uni = os.environ.get("TF", "1d"), os.environ.get("UNI", "")
    if tf not in BAR_HOURS:
        raise SystemExit(f"tf {tf!r} unsupported")
    lim = int(os.environ["SYMBOL_LIMIT"]) if os.environ.get("SYMBOL_LIMIT") else None
    groups = parse_groups(os.environ["SECTOR_GROUPS"])
    atrs = [a.strip() for a in os.environ.get("ATRS", ",".join(DEFAULT_ATRS)).split(",") if a.strip()]
    entry = os.environ.get("ENTRY", "next_open") or "next_open"
    frames = load_frames(m, tf, uni, lim)
    frames, dropped = bh.clean_frames(frames)
    print(f"sector_main_replay tf={tf} uni={uni or 'full'}: {len(frames)} symbols", flush=True)
    res = run_cells(m, frames, groups, atrs, tf, uni, entry)
    res.update({"tf": tf, "uni": uni or "full", "entry": entry, "cost_round_trip_pct": m.ROUND_TRIP_COST_PCT,
                "synthetic": os.environ.get("SYNTHETIC") == "1", "bars_dropped_glitch": dropped,
                "universe_requested": "main._load_nse_universe_from_file()" + (" & main.SWING_WATCHLIST" if uni == "n200" else ""),
                "picks_source": "main.sector_rotation_cell_picks (real; strong=sector_rotation_picks, weak=sector_rotation_weak_picks)",
                "atr_source": "main._atr_series (real, 14 bars of this tf, read at signal bar t)",
                "exit_source": "main.sector_rotation_cell_stop + main.sector_rotation_cell_exit_reason (real)",
                "bar_count_note": "hold H and lookback L are in BARS of this tf"})
    os.makedirs("out", exist_ok=True)
    name = os.environ.get("NAME", f"{tf}{'_' + uni if uni else ''}")
    json.dump(res, open(f"out/sector_main_replay_{name}.json", "w"), indent=1, default=str)
    for r in res["rows"]:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "pfgross", mt["pfgross"], "win", mt["win_pct"],
              "oos_pfnet", mt["oos"]["pfnet"], "hold_h", mt["avg_held_hours"])


def merge(d, out_path):
    rows, meta = [], []
    for f in sorted(glob.glob(os.path.join(d, "**", "sector_main_replay_*.json"), recursive=True)):
        r = json.load(open(f))
        rows += r["rows"]
        meta.append({k: r.get(k) for k in ("tf", "uni", "entry", "universe_size", "bars", "first_bar", "last_bar",
                                           "cost_round_trip_pct", "synthetic", "bars_dropped_glitch")})
    try:
        import strategy_registry as sr
        reg = {s.name: s.metrics for s in sr.REGISTRY}
        for r in rows:
            mt = reg.get(r["source_tag"])
            r["research_pfnet"] = getattr(mt, "pfnet", None)
            r["research_n"] = getattr(mt, "n_trades", None)
    except Exception:
        pass
    out = {"note": "B-1467 sector_rotation main.py replay, one position per symbol; rows[].metrics read by main._replay_verified_tags",
           "jobs": meta, "rows": rows}
    json.dump(out, open(out_path, "w"), indent=1)
    for r in sorted(rows, key=lambda x: -(x["metrics"]["pfnet"] or 0))[:40]:
        mt = r["metrics"]
        print(r["tag"], "n", mt["n"], "pfnet", mt["pfnet"], "oos", mt["oos"]["pfnet"], "research", r.get("research_pfnet"))
    print(f"rows={len(rows)} jobs={len(meta)}")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "plan":
        import main as _m
        import strategy_registry as _r
        plan = build_plan(_r.REGISTRY, set(_m._STRATEGY_TAG_TO_REGISTRY_NAME.values()))
        print(json.dumps({"skipped": plan["skipped"], "stop_substituted": plan["stop_substituted"]}), file=sys.stderr)
        print(json.dumps({"include": plan["include"]}))
    elif cmd == "merge":
        merge(sys.argv[2], sys.argv[3])
    else:
        run()
