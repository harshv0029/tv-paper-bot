"""O'Neil chart-pattern detectors (backlog B-461, B-462, B-463, B-464, B-465).

Pure-numpy, no look-ahead: a signal at bar t uses bars <= t only; entry is the next open (done by the caller,
scripts/oneil_research.py). Every detector returns (signal bool array, pivot price array). The SHORT mirror runs the
same detector on reciprocal prices (h'=1/l, l'=1/h, c'=1/c), i.e. an inverted cup / double-top breakdown.

Patterns (tag family `oneil_<pattern>`, variant `breakout`):
  cup_handle  B-462  cup span cupmin..cupmax bars, depth 12-33%, bottom in the middle half (U-shape), handle of
                     hmin..hmax bars in the upper half of the cup with <=15% drop; signal = close through handle high
  saucer      B-463  same handle rules but longer (>= saucer_min bars) and shallower (8-20%) cup
  cup_nohandle B-464 close through the left-lip high after a cup (no handle required); separate tag from the handle form
  double_bottom B-465 second low within 0-3% BELOW the first (shakeout), lows >= dbmin bars apart, close above the
                     middle peak
Base quality (B-461): `base_stage` counts prior bases of the symbol; a detection is `faulty` when stage >= 3 or the
base depth exceeds 33%; callers may use `quality_ok` as an entry filter (qual1) to test the rule as its own cell.
"""
import numpy as np

CUP_DEPTH = (0.12, 0.33)
SAUCER_DEPTH = (0.08, 0.20)
HANDLE_MAX_DROP = 0.15


def _w(cfg, key, default):
    return cfg.get(key, default)


def _cup_core(h, l, c, t, cupmin, cupmax, depth_rng):
    """Return (ip, P, B, ib) for a cup ending before t, or None. Left lip = highest high in the window."""
    lo = max(0, t - cupmax)
    seg_h = h[lo:t]
    if len(seg_h) < cupmin:
        return None
    ip = lo + int(np.argmax(seg_h))
    span = t - ip
    if span < cupmin:
        return None
    P = h[ip]
    seg_l = l[ip + 1:t]
    if len(seg_l) < 3:
        return None
    ib = ip + 1 + int(np.argmin(seg_l))
    B = l[ib]
    depth = (P - B) / P
    if not (depth_rng[0] <= depth <= depth_rng[1]):
        return None
    # U-shape: bottom in the middle half of the span (rejects V and one-sided slides)
    pos = (ib - ip) / span
    if not (0.25 <= pos <= 0.75):
        return None
    return ip, P, B, ib


def detect_cup(h, l, c, v, cfg, handle=True, saucer=False):
    n = len(c)
    sig = np.zeros(n, bool)
    piv = np.full(n, np.nan)
    cupmin = cfg["cupmin"]
    cupmax = cfg["cupmax"]
    depth_rng = SAUCER_DEPTH if saucer else CUP_DEPTH
    if saucer:
        cupmin = max(cupmin, cfg["saucer_min"])
    hmin, hmax = cfg["hmin"], cfg["hmax"]
    vavg = np.full(n, np.nan)
    k = cfg["vol"]
    cs = np.cumsum(np.nan_to_num(v))
    for t in range(k + 1, n):
        vavg[t] = (cs[t - 1] - cs[t - 1 - k]) / k
    for t in range(cupmin + hmin + 2, n):
        if not (v[t] >= 1.5 * vavg[t]):
            continue
        if handle:
            found = None
            for hl in range(hmin, hmax + 1):
                cup = _cup_core(h, l, c, t - hl, cupmin, cupmax, depth_rng)
                if cup is None:
                    continue
                ip, P, B, ib = cup
                hh = h[t - hl:t].max()
                hlow = l[t - hl:t].min()
                if hh > P * 1.0001 or hh < B + 0.5 * (P - B):  # handle stays under the lip, in upper half
                    continue
                if (hh - hlow) / hh > HANDLE_MAX_DROP or hlow < B + 0.5 * (P - B):
                    continue
                if c[t] > hh:
                    found = hh
                    break
            if found is not None:
                sig[t] = True
                piv[t] = found
        else:
            cup = _cup_core(h, l, c, t, cupmin, cupmax, depth_rng)
            if cup is None:
                continue
            ip, P, B, ib = cup
            if c[t] > P and c[t - 1] <= P:
                sig[t] = True
                piv[t] = P
    return sig, piv


def detect_double_bottom(h, l, c, v, cfg):
    n = len(c)
    sig = np.zeros(n, bool)
    piv = np.full(n, np.nan)
    dbmin, dbmax = cfg["dbmin"], cfg["dbmax"]
    vavg = np.full(n, np.nan)
    k = cfg["vol"]
    cs = np.cumsum(np.nan_to_num(v))
    for t in range(k + 1, n):
        vavg[t] = (cs[t - 1] - cs[t - 1 - k]) / k
    for t in range(dbmin + 15, n):
        if not (v[t] >= 1.5 * vavg[t]):
            continue
        lo = max(0, t - dbmax)
        seg = l[lo:t - 3]
        if len(seg) < dbmin:
            continue
        # second low = lowest low in the last 10 bars; first low = lowest low in the older part
        w2 = l[t - 10:t]
        i2 = t - 10 + int(np.argmin(w2))
        B2 = l[i2]
        older = l[lo:i2 - dbmin + 1] if i2 - dbmin + 1 > lo else None
        if older is None or len(older) == 0:
            continue
        i1 = lo + int(np.argmin(older))
        B1 = l[i1]
        if not (B1 * 0.97 <= B2 <= B1):  # undercut by 0-3%
            continue
        M = h[i1:i2].max()
        if (M - B1) / M < 0.10:  # middle peak must be a real rally off the first low
            continue
        if c[t] > M and c[t - 1] <= M:
            sig[t] = True
            piv[t] = M
    return sig, piv


def base_stage(sig):
    """Count of earlier distinct signal clusters (a cluster = signals closer than 20 bars); stage 1 = first base."""
    stage = np.zeros(len(sig), int)
    count, last = 0, -10 ** 9
    for t in np.flatnonzero(sig):
        if t - last > 20:
            count += 1
        stage[t] = count
        last = t
    return stage


def quality_ok(sig, depth_ok=True):
    """B-461: 1st/2nd base only (stage <= 2) -- 3rd/4th stage bases are 'faulty' per O'Neil."""
    return sig & (base_stage(sig) <= 2)


def pattern_signals(o, h, l, c, v, rs, cfg, chases, rs_filters):
    """{(family, variant, dir, chase, rsf): bool array} for all 4 patterns x 2 directions (+ qual1 for cup_handle)."""
    n = len(c)
    nxt_o = np.append(o[1:], np.nan)
    out = {}
    rsv = rs
    ok_l = {"none": np.ones(n, bool), "80": np.nan_to_num(rsv) >= 80, "qual1": np.ones(n, bool)}
    ok_s = {"none": np.ones(n, bool), "80": np.nan_to_num(rsv, nan=100) <= 30, "qual1": np.ones(n, bool)}
    with np.errstate(invalid="ignore", divide="ignore"):
        inv = (1.0 / l, 1.0 / h, 1.0 / c)
        dets = {
            "cup_handle": lambda hh, ll, cc: detect_cup(hh, ll, cc, v, cfg, handle=True),
            "saucer": lambda hh, ll, cc: detect_cup(hh, ll, cc, v, cfg, handle=True, saucer=True),
            "cup_nohandle": lambda hh, ll, cc: detect_cup(hh, ll, cc, v, cfg, handle=False),
            "double_bottom": lambda hh, ll, cc: detect_double_bottom(hh, ll, cc, v, cfg),
        }
        for fam, fn in dets.items():
            for d, (hh, ll, cc) in (("long", (h, l, c)), ("short", inv)):
                sg, pv = fn(hh, ll, cc)
                if not sg.any():
                    continue
                if d == "long":
                    chase_ok = lambda ch: (nxt_o / pv - 1) <= ch
                    ok = ok_l
                else:  # pv is a reciprocal-price pivot; the short entry sits below 1/pv
                    chase_ok = lambda ch: (1 - nxt_o * pv) <= ch
                    ok = ok_s
                for ch in chases:
                    cm = np.nan_to_num(chase_ok(ch).astype(float)).astype(bool)
                    for rsf in rs_filters:
                        out[("oneil_" + fam, "breakout", d, ch, rsf)] = sg & cm & ok[rsf]
                    if fam == "cup_handle":
                        out[("oneil_" + fam, "breakout", d, ch, "qual1")] = quality_ok(sg) & cm
    return {k: np.nan_to_num(np.asarray(m, float)).astype(bool) for k, m in out.items()}
