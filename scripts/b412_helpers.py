"""B-412 pure helpers (no yfinance, no main import): tags, metrics, breakeven ratchet,
lab-variant exit simulator with exit reasons. Used by scripts/b412_replay.py and tests."""
import numpy as np


def fmt_param(x):
    """Naming grammar: decimal point is 'd' (1.5 -> 1d5, 1.0 -> 1d0)."""
    return str(x).replace(".", "d")


def be_tag(family, variant, direction, be_r):
    return f"{family}__{variant}__{direction}__1d__be{fmt_param(float(be_r))}r__v1"


def lab_tag(variant, maxh=60):
    """Tag the lab registered (immutable)."""
    return f"minervini_vcp__{variant}__long__1d__h{maxh}__v1"


def lab_tag_replay(variant, maxh=60):
    """Re-run result tag (same variant, same params; v2 = replayed with per-trade exit reasons)."""
    return f"minervini_vcp__{variant}__long__1d__h{maxh}__v2"


def ratcheted_stop(entry, stop0, running_extreme, be_r, direction="long"):
    """Breakeven-at-R stop. Long: once peak close >= entry + be_r*R the stop is max(stop0, entry).
    Short: once trough close <= entry - be_r*R the stop is min(stop0, entry). R = |entry - stop0|."""
    r = abs(entry - stop0)
    if r <= 0:
        return stop0
    if direction == "long":
        return max(stop0, entry) if running_extreme >= entry + be_r * r else stop0
    return min(stop0, entry) if running_extreme <= entry - be_r * r else stop0


def _pf(vals):
    v = np.asarray(vals, float)
    w, l = v[v > 0].sum(), -v[v <= 0].sum()
    return float(w / l) if l > 0 else None  # None = no losses (JSON-safe, not inf)


def metrics(trades):
    """trades: dicts with gross, net (fractions), held (bars), reason. Emits every field,
    including the per-exit-reason breakdown. Nothing is trimmed."""
    if not trades:
        return {"n": 0, "win_pct": 0.0, "pfnet": None, "pfgross": None, "avg_net_pct": 0.0,
                "avg_gross_pct": 0.0, "avg_held_bars": 0.0, "exit_reasons": {}}
    net = [t["net"] for t in trades]
    gross = [t["gross"] for t in trades]
    by = {}
    for t in trades:
        by.setdefault(t["reason"], []).append(t)
    return {
        "n": len(trades),
        "win_pct": round(100.0 * sum(1 for x in net if x > 0) / len(net), 2),
        "pfnet": _pf(net), "pfgross": _pf(gross),
        "avg_net_pct": round(100.0 * float(np.mean(net)), 4),
        "avg_gross_pct": round(100.0 * float(np.mean(gross)), 4),
        "avg_held_bars": round(float(np.mean([t["held"] for t in trades])), 2),
        "exit_reasons": {k: {"n": len(v), "pfnet": _pf([x["net"] for x in v]),
                             "win_pct": round(100.0 * sum(1 for x in v if x["net"] > 0) / len(v), 2),
                             "avg_held_bars": round(float(np.mean([x["held"] for x in v])), 2)}
                         for k, v in by.items()},
    }


def parse_lab_variant(v):
    """'pct8_hard_f_ext_le5_on' -> ('pct8_hard', 'ext_le5', 'on'); 'rr3' -> ('rr3', None, None)."""
    if "_f_" in v:
        ex, rest = v.split("_f_", 1)
        feat, flag = rest.rsplit("_", 1)
        return ex, feat, flag
    return v, None, None


def sma(x, n):
    out = np.full(len(x), np.nan)
    c = np.cumsum(np.insert(np.asarray(x, float), 0, 0.0))
    if len(x) >= n:
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def simulate_lab_exit(name, o, h, l, c, sig, cost, maxh=60):
    """Faithful port of scripts/minervini_lab.run_variant (regime variants excluded) that also
    returns the exit reason. sig=(i, entry, stop0, atr). Returns (ret, held, reason) or None."""
    ma20, ma50, ma200 = sma(c, 20), sma(c, 50), sma(c, 200)
    i, _entry, stop0, atr = sig
    n = len(c)
    e = i + 1
    if e >= n:
        return None
    ent = o[e]
    if not ent or np.isnan(ent) or stop0 >= ent:
        return None
    stop = stop0
    peak = c[i]
    if name == "pct8_hard":
        stop = ent * 0.92
    elif name == "cap10_struct":
        stop = max(stop0, ent * 0.90)
    elif name == "cap15_struct":
        stop = max(stop0, ent * 0.85)
    R = ent - stop
    for j in range(e, min(e + maxh, n)):
        if l[j] <= stop:
            return (min(stop, o[j]) / ent - 1 - cost, j - e + 1, "stop_hit")
        cj = c[j]
        held = j - e + 1
        peak = max(peak, cj)
        if name in ("base", "cap10_struct", "cap15_struct"):
            stop = max(stop, peak - 2.0 * atr)
        if name == "ma20_fail" and held >= 3 and cj < ma20[j]:
            return (cj / ent - 1 - cost, held, "ma20_fail")
        if name == "ma50_trail" and cj < ma50[j]:
            return (cj / ent - 1 - cost, held, "ma50_break")
        if name == "ma200_break" and cj < ma200[j]:
            return (cj / ent - 1 - cost, held, "ma200_break")
        if name in ("rr2", "rr3"):
            tgt = ent + (2 if name == "rr2" else 3) * R
            if h[j] >= tgt:
                return (tgt / ent - 1 - cost, held, "target_hit")
        if name == "timestop10" and held == 10 and cj < ent * 1.02:
            return (cj / ent - 1 - cost, held, "time_stop")
        if name == "climax_sell" and cj / c[j - 1] - 1 >= 0.07 and cj > 1.25 * ma50[j]:
            return (cj / ent - 1 - cost, held, "climax_sell")
        if name == "breakeven_after_1r" and cj >= ent + R:
            stop = max(stop, ent)
        if name == "gap_dn_exit" and o[j] < c[j - 1] * 0.95:
            return (o[j] / ent - 1 - cost, held, "gap_down_exit")
    j = min(e + maxh, n) - 1
    return (c[j] / ent - 1 - cost, j - e + 1, "max_hold_timeout")
