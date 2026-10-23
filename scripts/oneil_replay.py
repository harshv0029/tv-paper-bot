"""O'Neil weekly/daily setup REPLAY harness (backlog B-776).

Purpose: independently re-derive and replay named O'Neil registry tags (flat-base / pivot / new-high) on the FULL NSE
universe so a suspicious research number (e.g. oneil_flatbase__breakout__long__1w__atr3_avg1_chase10_h26_rsnone__v1,
PFnet 5.165 n=116) can be confirmed or refuted by a second implementation.

B-1070 UPDATE: main.py now has additive, unwired oneil_* functions (oneil_signal_at, oneil_atr14, oneil_stop_price,
oneil_trail_stop, oneil_exit_bar). The default run (USE_MAIN=1) calls them and writes NEW v2 tags; USE_MAIN=0 keeps the
original independent v1 implementation below (v1 results untouched). Parity of the two is unit-tested.
ORIGINAL PORT NOTICE (v1): main.py had NO O'Neil function, so this file was a faithful PORT of the detector rules of scripts/oneil_research.py (entry_signals + simulate), but
written independently as a bar-by-bar WALK-FORWARD (every decision at bar t uses only bars <= t; no vectorised shifts),
so a look-ahead or off-by-one bug in the vectorised research code cannot be reproduced here by copy. Shared with main:
the universe (main._load_nse_universe_from_file(), never main.NSE_FULL_UNIVERSE) and the cost
(main.ROUND_TRIP_COST_PCT = 0.8%). Constants come from oneil_research.CFG (same bar-count meanings per candle size).

Rules replayed (signal at close of t -> entry at open of t+1; a stop on EVERY trade; non-overlapping per symbol):
  flatbase  : prior `flat` bars range <=12%, advance >=30% (short: decline) over `adv_lb` bars before the flat, close
              through the flat high (short: low) on >=1.5x the prior `vol`-bar mean volume; no-chase <= chase%.
  pivot     : close through prior `base`-bar high (short: low), >=1.5x vol, close above (short: below) the `smalt` MA,
              base depth <=35%, no-chase.
  newhigh   : close above the prior `yr`-bar max close (short: below min close) on >=1.5x vol.
Exit params (parsed from the tag): atr<k> initial stop k*ATR14 below entry (above for shorts); avg1 = negative-control
add of a 2nd unit 1.5 ATR against (NEVER live: engine invariant is never average down); trl1 = swing-low trailing stop;
pct<k> percentage stop; tgt<k> = 8% stop + k% target; h<N> max hold in bars. Gaps through a stop fill at the open.

Honesty extras (so a thin n=116 PFnet can be judged): PFnet gross AND net, win%, n, avg hold bars, exit-reason
breakdown, universe size, symbols that traded, PFnet excluding the 5 best trades, top-5 share of total net gain,
optional adverse stop slippage (env SLIP_PCT, default 0). Optional cross-check (CROSSCHECK=1) runs
oneil_research.simulate on the same signals and prints any trade-count / PFnet disagreement.

Usage:
  TAGS="tag1,tag2" SHARD=0 NSHARDS=4 python3 scripts/oneil_replay.py            # writes docs/oneil_replay_s<shard>.json
  python3 scripts/oneil_replay.py --merge docs/oneil_replay_s*.json             # pools shards, prints the full table
Env: TAGS (comma list, default DEFAULT_TAGS), SHARD, NSHARDS, MAXSYM (debug), SLIP_PCT, CROSSCHECK,
INTERVAL (1d|1w: re-tag every spec to that candle size, B-786), PERIOD (yfinance period override, B-786).
RS rank (rs80 filters) is the 12-month return percentile across the symbols loaded in the shard (as in the research).
"""
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
import oneil_research as orx  # noqa: E402  (CFG constants, clean_bars, rs matrix, optional cross-check only)

CFG = orx.CFG
VOL_MULT, FLAT_RANGE, ADV_MIN, DEPTH_MAX = orx.VOL_MULT, orx.FLAT_RANGE, orx.ADV_MIN, orx.DEPTH_MAX
COST_FALLBACK = 0.008

DEFAULT_TAGS = (
    "oneil_flatbase__breakout__long__1w__atr3_avg1_chase10_h26_rsnone__v1",   # the suspicious one (avg-down control)
    "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone__v1",        # same without the average-down add
    "oneil_flatbase__breakout__long__1w__atr3_avg1_chase10_h12_rsnone__v1",
    "oneil_flatbase__breakout__long__1w__atr3_chase10_h26_rsnone_trl1__v1",
    "oneil_flatbase__breakout__short__1w__atr3_chase10_h26_rsnone__v1",       # short mirror, thumb rule
    "oneil_pivot__breakout__long__1w__atr3_chase10_h26_rsnone__v1",
    "oneil_newhigh__first__long__1w__atr3_h26_rsnone__v1",
)


# ---------- tag parsing ----------
def parse_tag(tag):
    """family__variant__dir__tf__params__v1 -> spec dict. Params: key letters + value ('d' = decimal point)."""
    parts = tag.split("__")
    if len(parts) != 6 or not parts[5].startswith("v"):
        raise ValueError(f"not a grammar tag: {tag}")
    fam, var, d, tf, pstr, _ = parts
    if d not in ("long", "short") or tf not in CFG:
        raise ValueError(f"unsupported dir/tf in {tag}")
    p = {}
    for tok in pstr.split("_"):
        m = re.fullmatch(r"([a-z]+)(.*)", tok)
        if not m:
            raise ValueError(f"bad param token {tok!r} in {tag}")
        k, v = m.group(1), m.group(2)
        if k == "rs":
            p["rs"] = v
        else:
            p[k] = float(v.replace("d", ".")) if v else 1.0
    if "h" not in p:
        raise ValueError(f"no hold (h<N>) in {tag}")
    if "atr" in p and "trl" in p:
        mode = "trl"
    elif "tgt" in p:
        if p.get("pct", 8.0) != 8.0 or "mh" in p:  # B-489/B-491 stoptgt sweep tags: replay v1 only knows pct8_tgt
            raise ValueError(f"replay v1 supports only pct8_tgt<k> (no mh); unsupported: {tag}")
        mode = "tgt"
    elif "pct" in p:
        mode = "pct"
    elif "avg" in p:
        mode = "avg"
    else:
        mode = "atr"
    val = p.get("tgt", p.get("pct", p.get("atr", 0.0))) if mode in ("tgt", "pct") else p.get("atr", 0.0)
    if mode in ("atr", "avg", "trl") and val <= 0:
        raise ValueError(f"no atr multiple in {tag}")
    return dict(tag=tag, family=fam, variant=var, dir=d, tf=tf, hold=int(p["h"]), mode=mode, val=float(val),
                chase=(p["chase"] / 100.0 if "chase" in p else None), rs=p.get("rs", "none"))


def retag_tf(tag, tf):
    """B-786: the same rule at another candle size is a NEW tag (naming grammar): swap the tf field only."""
    parts = tag.split("__")
    if len(parts) != 6:
        raise ValueError(f"not a grammar tag: {tag}")
    if tf not in CFG:
        raise ValueError(f"O'Neil replay supports only {sorted(CFG)} (bar-count constants are weeks/days), got {tf}")
    parts[3] = tf
    return "__".join(parts)


# ---------- walk-forward detector ----------
def atr14(h, l, c):
    """ATR(14) simple mean of true range, using only bars <= t (NaN until 14 TRs exist)."""
    n = len(c)
    tr = np.full(n, np.nan)
    for t in range(1, n):
        tr[t] = max(h[t] - l[t], abs(h[t] - c[t - 1]), abs(l[t] - c[t - 1]))
    out = np.full(n, np.nan)
    for t in range(14, n):
        out[t] = tr[t - 13:t + 1].mean()
    return out


def signal_at(spec, t, o, h, l, c, v, rs, cfg):
    """True if the setup fires at the CLOSE of bar t. Uses bars <= t only (o[t+1] only for the chase test, i.e. the
    live 'is the next open still near the pivot' check made at the next open)."""
    side = 1 if spec["dir"] == "long" else -1
    vol_n, fam = cfg["vol"], spec["family"]
    if t < vol_n + 1 or t + 1 >= len(c):
        return False
    vavg = float(np.mean(v[t - vol_n:t]))
    if not vavg > 0 or not v[t] >= VOL_MULT * vavg:
        return False
    nxt = o[t + 1]
    rsf = spec["rs"]
    if rsf not in ("none", ""):
        thr = float(rsf)
        if np.isnan(rs[t]) or (rs[t] < thr if side == 1 else rs[t] > 30.0):
            return False
    ch = spec["chase"]
    if fam == "oneil_flatbase":
        fb, adv_lb = cfg["flat"], cfg["adv_lb"]
        if t < fb + adv_lb + 1:
            return False
        hh, ll = float(np.max(h[t - fb:t])), float(np.min(l[t - fb:t]))
        if (hh - ll) / hh > FLAT_RANGE:
            return False
        adv = c[t - fb] / c[t - fb - adv_lb]
        if side == 1:
            return bool(adv >= 1 + ADV_MIN and c[t] > hh and (ch is None or nxt / hh - 1 <= ch))
        return bool(adv <= 1 - ADV_MIN and c[t] < ll and (ch is None or 1 - nxt / ll <= ch))
    if fam == "oneil_pivot":
        base, smalt = cfg["base"], cfg["smalt"]
        if t < max(base, smalt) + 1:
            return False
        hh, ll = float(np.max(h[t - base:t])), float(np.min(l[t - base:t]))
        ma = float(np.mean(c[t - smalt + 1:t + 1]))
        if (hh - ll) / hh > DEPTH_MAX:
            return False
        if side == 1:
            return bool(c[t] > hh and c[t] > ma and (ch is None or nxt / hh - 1 <= ch))
        return bool(c[t] < ll and c[t] < ma and (ch is None or 1 - nxt / ll <= ch))
    if fam == "oneil_newhigh":
        yr = cfg["yr"]
        if t < yr + 1:
            return False
        return bool(c[t] > np.max(c[t - yr:t]) if side == 1 else c[t] < np.min(c[t - yr:t]))
    raise ValueError(f"unsupported family {fam}")


# ---------- walk-forward trade simulation (stop on every trade) ----------
def _main_app():
    import main as app   # B-1070: real main.py functions (oneil_signal_at / oneil_stop_price / oneil_exit_bar ...)
    return app


def replay_symbol(df, rs_series, spec, cost, slip=0.0, use_main=False):
    """use_main=True (B-1070) routes detector, ATR, stop, trailing ratchet and exit through main.py's oneil_* functions
    (avg-down add stays here: negative control, never live). Returns list of dict(net, gross, held, reason, entry_bar). Non-overlapping, hold fully available only."""
    cfg = CFG[spec["tf"]]
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float)
    rs = (rs_series.reindex(df.index).to_numpy(float) if rs_series is not None else np.full(len(c), np.nan))
    app = _main_app() if use_main else None
    atr = app.oneil_atr14(h, l, c) if use_main else atr14(h, l, c)
    side = 1 if spec["dir"] == "long" else -1
    hold, mode, val = spec["hold"], spec["mode"], spec["val"]
    sw = cfg["swing"]
    rs_thr = None if spec["rs"] in ("none", "") else spec["rs"]
    out, t, n = [], 0, len(c)
    while t < n - 1:
        if np.isnan(atr[t]) or atr[t] <= 0:
            t += 1
            continue
        fired = (app.oneil_signal_at(spec["family"], spec["dir"], spec["tf"], t, o, h, l, c, v, rs, spec["chase"], rs_thr)
                 if use_main else signal_at(spec, t, o, h, l, c, v, rs, cfg))
        if not fired:
            t += 1
            continue
        e = t + 1
        ent = o[e]
        last = min(e + hold - 1, n - 1)
        if not ent or np.isnan(ent) or last - e + 1 < hold:
            t += 1
            continue
        if use_main:
            stop = app.oneil_stop_price(ent, atr[t], spec["dir"], "atr" if mode in ("trl", "avg") else mode, val)
        elif mode == "pct":
            stop = ent * (1 - side * val / 100.0)
        elif mode == "tgt":
            stop = ent * (1 - side * 0.08)
        else:
            stop = ent - side * val * atr[t]
        init_stop = stop
        target = ent * (1 + side * val / 100.0) if mode == "tgt" else None
        add_px = ent - side * 1.5 * atr[t] if mode == "avg" else None
        add_done = False
        exitp, jx, reason = c[last], last, "timeout"
        for j in range(e, last + 1):
            if use_main:
                if mode == "trl":
                    stop = app.oneil_trail_stop(spec["dir"], h, l, e, j, sw, stop)
                hit = app.oneil_exit_bar(spec["dir"], o[j], h[j], l[j], c[j], j, last, stop, init_stop, target)
                if hit is not None and hit[0] != "timeout":
                    exitp, reason = hit[1], hit[0]
                    exitp = exitp * (1 - slip) if side == 1 and reason.endswith("stop") else (
                        exitp * (1 + slip) if side == -1 and reason.endswith("stop") else exitp)
                    jx = j
                    break
                if add_px is not None and not add_done and j > e:
                    if (side == 1 and l[j] <= add_px) or (side == -1 and h[j] >= add_px):
                        add_done = True
                continue
            if mode == "trl":
                k = j - 1 - sw
                if k - sw >= e:
                    if side == 1 and l[k] == np.min(l[k - sw:k + sw + 1]):
                        stop = max(stop, l[k])
                    elif side == -1 and h[k] == np.max(h[k - sw:k + sw + 1]):
                        stop = min(stop, h[k])
            if side == 1 and l[j] <= stop:
                exitp, jx = min(stop, o[j]) * (1 - slip), j
                reason = "trail_stop" if stop > init_stop else "stop"
                break
            if side == -1 and h[j] >= stop:
                exitp, jx = max(stop, o[j]) * (1 + slip), j
                reason = "trail_stop" if stop < init_stop else "stop"
                break
            if target is not None:
                if side == 1 and h[j] >= target:
                    exitp, jx, reason = max(target, o[j]), j, "target"
                    break
                if side == -1 and l[j] <= target:
                    exitp, jx, reason = min(target, o[j]), j, "target"
                    break
            if add_px is not None and not add_done and j > e:
                if (side == 1 and l[j] <= add_px) or (side == -1 and h[j] >= add_px):
                    add_done = True
        g = (exitp / ent - 1) * side
        if add_done:
            g = (g + (exitp / add_px - 1) * side) / 2.0
            reason += "+avgdown"
        out.append(dict(net=g - cost, gross=g, held=jx - e + 1, reason=reason, entry_bar=e))
        t = jx + 1
    return out


# ---------- aggregation (additive across shards) ----------
def new_cell():
    return dict(gain=0.0, loss=0.0, gain_g=0.0, loss_g=0.0, n=0, wins=0, held=0, reasons={}, top=[], syms=0)


def add_trades(cell, trades):
    if trades:
        cell["syms"] += 1
    for tr in trades:
        net, g = tr["net"], tr["gross"]
        if net > 0:
            cell["gain"] += net
        else:
            cell["loss"] -= net
        if g > 0:
            cell["gain_g"] += g
        else:
            cell["loss_g"] -= g
        cell["n"] += 1
        cell["wins"] += int(net > 0)
        cell["held"] += tr["held"]
        r = cell["reasons"].setdefault(tr["reason"], [0, 0.0])
        r[0] += 1
        r[1] += net
        cell["top"] = sorted(cell["top"] + [net], reverse=True)[:5]


def merge_cells(parts):
    tot = {}
    for p in parts:
        for tag, c in p.items():
            t = tot.setdefault(tag, new_cell())
            for k in ("gain", "loss", "gain_g", "loss_g", "n", "wins", "held", "syms"):
                t[k] += c[k]
            for rk, (rn, rs_) in c["reasons"].items():
                r = t["reasons"].setdefault(rk, [0, 0.0])
                r[0] += rn
                r[1] += rs_
            t["top"] = sorted(t["top"] + list(c["top"]), reverse=True)[:5]
    return tot


def _pf(g, l):
    return round(g / l, 3) if l > 0 else None


def finalize(cells, universe=None):
    res = {}
    for tag, c in cells.items():
        n = c["n"]
        if n == 0:
            res[tag] = dict(n=0, universe=universe)
            continue
        top_sum = sum(x for x in c["top"] if x > 0)
        gain_ex = c["gain"] - top_sum
        res[tag] = dict(
            n=n, win_pct=round(100.0 * c["wins"] / n, 1), avg_hold_bars=round(c["held"] / n, 2),
            pfnet=_pf(c["gain"], c["loss"]), pfgross=_pf(c["gain_g"], c["loss_g"]),
            pfnet_ex_top5=_pf(gain_ex, c["loss"]), top5_share_of_gain=round(top_sum / c["gain"], 3) if c["gain"] > 0 else None,
            avg_net_pct=round(100.0 * (c["gain"] - c["loss"]) / n, 3), symbols_traded=c["syms"], universe=universe,
            exit_reasons={k: dict(n=r[0], avg_net_pct=round(100.0 * r[1] / r[0], 3)) for k, r in sorted(c["reasons"].items())})
    return res


def format_table(res):
    hdr = "tag\tn\twin_pct\tavg_hold_bars\tpfnet\tpfgross\tpfnet_ex_top5\ttop5_share\tsyms_traded\tuniverse\texit_reasons"
    rows = [hdr]
    for tag, m in sorted(res.items()):
        if not m.get("n"):
            rows.append(f"{tag}\t0\tNA\tNA\tNA\tNA\tNA\tNA\t0\t{m.get('universe')}\t-")
            continue
        ex = ";".join(f"{k}:{v['n']}@{v['avg_net_pct']}" for k, v in m["exit_reasons"].items())
        rows.append("\t".join(str(x) for x in (tag, m["n"], m["win_pct"], m["avg_hold_bars"], m["pfnet"], m["pfgross"],
                                               m["pfnet_ex_top5"], m["top5_share_of_gain"], m["symbols_traded"],
                                               m["universe"], ex)))
    return "\n".join(rows)


# ---------- data + run ----------
def load_data(syms, tf, cfg):
    import yfinance as yf
    data = {}
    for b0 in range(0, len(syms), 100):
        batch = syms[b0:b0 + 100]
        try:
            d = yf.download(batch, period=cfg["period"], interval="1wk" if tf == "1w" else "1d", group_by="ticker",
                            auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("batch fail", b0, e, flush=True)
            continue
        for s in batch:
            try:
                df = d[s].dropna(subset=["Close"]) if len(batch) > 1 else d.dropna(subset=["Close"])
                df = orx.clean_bars(df[["Open", "High", "Low", "Close", "Volume"]].dropna())
            except Exception:
                continue
            if len(df) >= cfg["min_bars"]:
                data[s] = df
        print("downloaded", b0, "kept", len(data), flush=True)
    return data


def run_specs(specs, data, cost, slip=0.0, crosscheck=False, use_main=False):
    """Replay every spec on every symbol of one timeframe. Returns (cells, crosscheck_notes)."""
    cells = {s["tag"]: new_cell() for s in specs}
    notes = []
    if not data:
        return cells, notes
    tf = specs[0]["tf"]
    closes = pd.DataFrame({s: df["Close"] for s, df in data.items()})
    rs_all = orx.rs_rank_matrix(closes, CFG[tf]["rs_lb"])
    for i, (sym, df) in enumerate(data.items()):
        for sp in specs:
            trades = replay_symbol(df, rs_all[sym], sp, cost, slip, use_main)
            add_trades(cells[sp["tag"]], trades)
            if crosscheck and trades:
                notes.extend(_crosscheck(sp, sym, df, rs_all[sym], cost, trades))
        if i % 100 == 0:
            print("processed", i, flush=True)
    return cells, notes


def _crosscheck(sp, sym, df, rs_series, cost, trades):
    """Compare against oneil_research's vectorised simulate on its own signals (slip must be 0)."""
    cfg = CFG[sp["tf"]]
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    v = df["Volume"].to_numpy(float)
    rs = rs_series.reindex(df.index).to_numpy(float)
    atr = orx.atr_arr(h, l, c)
    key = (sp["family"].replace("oneil_", "oneil_"), sp["variant"], sp["dir"], sp["chase"],
           sp["rs"] if sp["rs"] in ("none",) else str(int(float(sp["rs"]))))
    sig = orx.entry_signals(o, h, l, c, v, rs, cfg).get(key)
    if sig is None:
        return [f"{sp['tag']} {sym}: research has no signal key {key}"]
    side = 1 if sp["dir"] == "long" else -1
    ref = orx.simulate(sig, o, h, l, c, atr, sp["hold"], sp["mode"], sp["val"], side, cost, cfg["swing"])
    if len(ref) != len(trades) or any(abs(a[0] - b["net"]) > 1e-9 for a, b in zip(ref, trades)):
        return [f"{sp['tag']} {sym}: research n={len(ref)} vs replay n={len(trades)}"]
    return []


def main_run():
    import main as app
    tags = [t.strip() for t in os.environ.get("TAGS", "").split(",") if t.strip()] or list(DEFAULT_TAGS)
    interval = (os.environ.get("INTERVAL") or "").strip()
    if interval:   # B-786: replay the same rules at another candle size, each its own tag; bar counts mean BARS
        tags = [retag_tf(t, interval) for t in tags]
    use_main = os.environ.get("USE_MAIN", "1") != "0"
    if use_main:   # B-1070: the main.py-calling run is a NEW tag set (v1 -> v2); v1 results stay untouched
        tags = [re.sub(r"__v1$", "__v2", t) for t in tags]
    specs = [parse_tag(t) for t in tags]
    period_override = (os.environ.get("PERIOD") or "").strip()
    shard, nsh = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
    cost = app.ROUND_TRIP_COST_PCT / 100.0
    slip = float(os.environ.get("SLIP_PCT", "0") or 0) / 100.0
    universe = sorted(app._load_nse_universe_from_file())  # NOT main.NSE_FULL_UNIVERSE (NIFTY-200 after import)
    syms = universe[shard::nsh]
    cap = int(os.environ.get("MAXSYM", "0") or 0)
    if cap:
        syms = syms[:cap]
    cells_all, notes_all, loaded = {}, [], {}
    for tf in sorted({s["tf"] for s in specs}):
        data = load_data(syms, tf, dict(CFG[tf], period=period_override) if period_override else CFG[tf])
        loaded[tf] = len(data)
        cells, notes = run_specs([s for s in specs if s["tf"] == tf], data, cost, slip, os.environ.get("CROSSCHECK") == "1", use_main)
        cells_all.update(cells)
        notes_all += notes
    out = os.path.join(ROOT, "docs", f"oneil_replay_s{shard}.json")
    json.dump(dict(shard=shard, nshards=nsh, universe_total=len(universe), loaded=loaded, cost=cost, slip=slip,
                   crosscheck_notes=notes_all, cells=cells_all), open(out, "w"))
    print("wrote", out, "universe", len(universe), "loaded", loaded, "crosscheck diffs", len(notes_all))


def merge_run(paths):
    parts = [json.load(open(p)) for p in paths]
    cells = merge_cells([p["cells"] for p in parts])
    loaded = {}
    for p in parts:
        for tf, k in p["loaded"].items():
            loaded[tf] = loaded.get(tf, 0) + k
    uni = f"{parts[0]['universe_total']} listed; loaded {loaded}; cost {parts[0]['cost'] * 100:g}%; slip {parts[0]['slip'] * 100:g}%"
    res = finalize(cells, uni)
    json.dump(dict(results=res), open(os.path.join(ROOT, "docs", "oneil_replay_results.json"), "w"), indent=0)
    print(format_table(res))
    notes = [x for p in parts for x in p.get("crosscheck_notes", [])]
    print(f"crosscheck diffs: {len(notes)}")
    for x in notes[:30]:
        print(" ", x)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        merge_run(sys.argv[2:])
    else:
        main_run()
