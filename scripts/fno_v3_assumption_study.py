"""B-1725: evidence study for the View 6 fast-plan (v3) entry and exit assumptions.

Data: the repo's own 5-min cash cache docs/intraday/5m/*.csv.gz (Yahoo .NS bars, IST bar start).
Index proxies: NIFTYBEES (NIFTY 50), BANKBEES (NIFTY BANK), FINIETF (NIFTY FIN SERVICE; thinner, ~9% zero-volume
bars). Breadth: the NIFTY 50 constituents present in the cache, each vs its previous close.
India VIX is not in the cache (and Yahoo is unreachable here), so the CE VIX veto is not replayed.

Part A tests the index signals on the next 15 min of the index itself (no option model needed).
Part B replays the whole plan on SYNTHETIC option premiums: Black-Scholes (main._bs_price) on the index path with a
fixed IV, ATM strike, real days to expiry (NIFTY weekly Tuesday, BANKNIFTY/FINNIFTY monthly last Tuesday). It shows how
the exits behave on index noise; it cannot test IV, OI or real spreads. Cost: 0.8% of premium round trip.
"""
import csv
import datetime as dt
import glob
import gzip
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DISABLE_SCHEDULER", "1")
import main  # noqa: E402

PROXY = {"NIFTY": "NIFTYBEES.NS", "BANKNIFTY": "BANKBEES.NS", "FINNIFTY": "FINIETF.NS"}
LEVEL = {"NIFTY": 25850.0, "BANKNIFTY": 59000.0, "FINNIFTY": 29000.0}  # approx levels, only for the Rs20 floor
IV = {"NIFTY": 0.12, "BANKNIFTY": 0.14, "FINNIFTY": 0.13}
N50 = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL CIPLA "
       "COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK INDIGO INFY "
       "ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE SBIN "
       "SHRIRAMFIN SUNPHARMA TATACONSUM TMPV TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO").split()
COST = 0.8
WIN_LO, WIN_HI = 9 * 60 + 30, 14 * 60 + 30


def load():
    days = {}
    want = set(PROXY.values()) | {s + ".NS" for s in N50}
    for f in sorted(glob.glob("docs/intraday/5m/*.csv.gz")):
        d = os.path.basename(f)[:10]
        bars = {}
        for r in csv.DictReader(gzip.open(f, "rt")):
            if r["sym"] in want:
                t = r["ts"][11:16]
                bars.setdefault(r["sym"], {})[int(t[:2]) * 60 + int(t[3:]) + 5] = (
                    float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]))  # key = bar CLOSE minute
        days[d] = bars
    return days


def expiry_days(u, d, mins):
    day = dt.date.fromisoformat(d)
    if u == "NIFTY":
        e = day + dt.timedelta(days=(1 - day.weekday()) % 7)
    else:
        def last_tue(y, m):
            nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
            x = nxt - dt.timedelta(days=1)
            return x - dt.timedelta(days=(x.weekday() - 1) % 7)
        e = last_tue(day.year, day.month)
        if e < day:
            e = last_tue(day.year + (day.month == 12), day.month % 12 + 1)
    return max((e - day).days + (15 * 60 + 30 - mins) / 375.0, 0.02) / 365.0


def build(days):
    """Per day: minute -> {u: (o,h,l,c,dayp,open)}, nifty breadth (adv, dec)."""
    out, prev = {}, {}
    for d in sorted(days):
        b = days[d]
        rows = {}
        for m in range(9 * 60 + 20, 15 * 60 + 31, 5):
            snap, adv, dec = {}, 0, 0
            for s in N50:
                x = b.get(s + ".NS", {}).get(m)
                pc = prev.get(s + ".NS")
                if x and pc:
                    adv += x[3] > pc
                    dec += x[3] < pc
            for u, s in PROXY.items():
                x, pc, op = b.get(s, {}).get(m), prev.get(s), b.get(s, {}).get(9 * 60 + 20)
                if x and pc and op:
                    snap[u] = (x, (x[3] / pc - 1) * 100, op[0])
            rows[m] = (snap, adv, dec)
        out[d] = rows
        for s, bb in b.items():
            if bb:
                prev[s] = bb[max(bb)][3]
    return out


def strict(ot, u, snap, adv, dec, need_breadth=True):
    if u not in snap or "NIFTY" not in snap or adv + dec <= 0:
        return None
    x, ip, op = snap[u]
    npct = snap["NIFTY"][1]
    br_ok = (adv >= main.FNO_MOMO_STRICT_BREADTH * max(dec, 1)) if ot == "CE" else \
        (dec >= main.FNO_MOMO_STRICT_BREADTH * max(adv, 1))
    k = main.FNO_MOMO_STRICT_MIN_PCT
    if ot == "CE":
        return ip >= k and npct >= k and x[3] > op and (br_ok or not need_breadth)
    return ip <= -k and npct <= -k and x[3] < op and (br_ok or not need_breadth)


def loose(ot, u, snap):
    if u not in snap or "NIFTY" not in snap:
        return None
    return main._fno_momo_sentiment(ot, snap[u][1], snap["NIFTY"][1])


def part_a(B):
    """Next-15-min index return (signed in the trade direction) for each signal, bar by bar, 09:30-14:30."""
    buckets = {}

    def add(key, r):
        a = buckets.setdefault(key, [0, 0.0, 0, 0.0])
        a[0] += 1
        a[1] += r
        a[2] += r > 0
        a[3] += abs(r)

    for d, rows in B.items():
        for m, (snap, adv, dec) in rows.items():
            if not (WIN_LO <= m <= WIN_HI) or m - 5 not in rows or m + 15 not in rows:
                continue
            zone = "a_0930_1115" if m <= 11 * 60 + 15 else ("b_1115_1315" if m < 13 * 60 + 15 else "c_1315_1430")
            for u in PROXY:
                if u not in snap or u not in rows[m - 5][0] or u not in rows[m + 15][0]:
                    continue
                c, c5, c15 = snap[u][0][3], rows[m - 5][0][u][0][3], rows[m + 15][0][u][0][3]
                i5 = (c / c5 - 1) * 100
                f15 = (c15 / c - 1) * 100
                for ot, sg in (("CE", 1), ("PE", -1)):
                    r = sg * f15
                    s = strict(ot, u, snap, adv, dec)
                    mv = sg * i5 >= main.FNO_V3_IDX_MOVE_MIN_PCT
                    add(("all", "any", zone), r)
                    if s:
                        add(("strict", ot, zone), r)
                    if mv:
                        add(("move5", ot, zone), r)
                    if s and mv:
                        add(("strict+move5", ot, zone), r)
                    if s is False and mv:
                        add(("move5_not_strict", ot, zone), r)
                    if strict(ot, u, snap, adv, dec, need_breadth=False) and mv:
                        add(("strict_nobreadth+move5", ot, zone), r)
                    if loose(ot, u, snap) and mv:
                        add(("loose+move5", ot, zone), r)
    res = {}
    for (sig, ot, zone), (n, s, w, ab) in buckets.items():
        for k in ((sig, ot, zone), (sig, ot, "all_zones"), (sig, "both", "all_zones")):
            a = res.setdefault("|".join(k), [0, 0.0, 0, 0.0])
            if k[1] == "both" and ot == "both":
                continue
            a[0] += n
            a[1] += s
            a[2] += w
            a[3] += ab
    return {k: {"n": n, "mean_fwd15_pct": round(s / n, 4), "hit_pct": round(100 * w / n, 1),
                "mean_abs_fwd15_pct": round(ab / n, 4)} for k, (n, s, w, ab) in sorted(res.items()) if n}


def prem(u, S, K, d, m, ot):
    return main._bs_price(S, K, expiry_days(u, d, m), IV[u], ot)


def part_b(B, trail, hold_min, flt, target=None, mode="momentum"):
    """flt: dict of switches. One position at a time (like the live variant); best chg5 wins."""
    trades = []
    for d, rows in sorted(B.items()):
        pos = None
        for m in sorted(rows):
            snap, adv, dec = rows[m]
            if pos:
                u, ot, K, sc = pos["u"], pos["ot"], pos["K"], LEVEL[pos["u"]]
                if u not in snap:
                    continue
                x = snap[u][0]
                worst = x[2] if ot == "CE" else x[1]
                best = x[1] if ot == "CE" else x[2]
                p_worst = prem(u, worst * sc, K, d, m, ot)
                p_best = prem(u, best * sc, K, d, m, ot)
                p_c = prem(u, x[3] * sc, K, d, m, ot)
                p_o = prem(u, x[0] * sc, K, d, m, ot)  # bar open: a gap through the stop fills at the open
                reason, fill = None, p_c
                if m >= main.FNO_MOMO_FORCE_EXIT_MIN:
                    reason = "forced_1515"
                elif trail is not None and p_worst <= pos["stop"]:
                    reason, fill = "trail", min(pos["stop"], p_o)  # stop checked first when both touch in one bar (conservative)
                elif target is not None and p_best >= pos["px"] * (1 + target):
                    reason, fill = "target", pos["px"] * (1 + target)
                elif hold_min is not None and m - pos["m"] >= hold_min:
                    reason = "time"
                elif flt.get("loose_exit", True) and loose(ot, u, snap) is False:
                    reason = "senti_flip"
                elif flt.get("strict_exit") and strict(ot, u, snap, adv, dec) is False:
                    reason = "strict_flip"
                if reason:
                    gross = (fill / pos["px"] - 1) * 100
                    trades.append({"d": d, "u": u, "ot": ot, "m": pos["m"], "net": gross - COST, "why": reason,
                                   "held": m - pos["m"], "mfe": (pos["peak"] / pos["px"] - 1) * 100})
                    pos = None
                    continue
                pos["peak"] = max(pos["peak"], p_best, p_c)
                if trail is not None:
                    pos["stop"] = max(pos["stop"], pos["peak"] * (1 - trail))
                continue
            if not (WIN_LO <= m <= WIN_HI) or m - 5 not in rows or m - 15 not in rows:
                continue
            if flt.get("windows", True) and not any(a <= m <= b for a, b in main.FNO_V3_WINDOWS):
                continue
            best_c = None
            for u in PROXY:
                if u not in snap or u not in rows[m - 5][0] or u not in rows[m - 15][0]:
                    continue
                c, c5, c15 = snap[u][0][3], rows[m - 5][0][u][0][3], rows[m - 15][0][u][0][3]
                sc = LEVEL[u]
                K = round(c * sc / 100.0) * 100.0
                for ot, sg in (("CE", 1), ("PE", -1)):
                    if flt.get("strict", True) and not strict(ot, u, snap, adv, dec, flt.get("breadth", True)):
                        continue
                    if flt.get("loose_entry") and not loose(ot, u, snap):
                        continue
                    mv = sg * (c / c5 - 1) * 100
                    if mode == "pullback":  # B-1727: trend day (strict gate) + the last 5 min moved AGAINST it
                        if mv > -main.FNO_V3_IDX_MOVE_MIN_PCT:
                            continue
                    elif flt.get("move5", True) and mv < main.FNO_V3_IDX_MOVE_MIN_PCT:
                        continue
                    p, p5, p15 = (prem(u, v * sc, K, d, mm, ot) for v, mm in ((c, m), (c5, m - 5), (c15, m - 15)))
                    ch5, ch15 = (p / p5 - 1) * 100, (p / p15 - 1) * 100
                    if mode == "momentum" and flt.get("chg", True) and not (0 < ch5 <= main.FNO_V3_CHG5_MAX and ch15 <= main.FNO_V3_CHG15_MAX):
                        continue
                    if p < main.FNO_V3_MIN_PREMIUM:
                        continue
                    if best_c is None or ch5 > best_c[0]:
                        best_c = (ch5, u, ot, K, p)
            if best_c:
                _, u, ot, K, p = best_c
                pos = {"u": u, "ot": ot, "K": K, "px": p, "peak": p, "m": m,
                       "stop": p * (1 - trail) if trail is not None else 0.0}
    return trades


def summ(tr):
    if not tr:
        return {"n": 0}
    nets = [t["net"] for t in tr]
    w = [x for x in nets if x > 0]
    lo = [-x for x in nets if x <= 0]
    days = len({t["d"] for t in tr})
    why = {}
    for t in tr:
        why[t["why"]] = why.get(t["why"], 0) + 1
    return {"n": len(tr), "win_pct": round(100 * len(w) / len(tr), 1), "avg_net_pct": round(sum(nets) / len(tr), 3),
            "sum_net_pct": round(sum(nets), 1), "pf": round(sum(w) / sum(lo), 3) if lo else None,
            "avg_win": round(sum(w) / len(w), 2) if w else 0, "avg_loss": round(-sum(lo) / len(lo), 2) if lo else 0,
            "avg_mfe_pct": round(sum(t["mfe"] for t in tr) / len(tr), 2), "trade_days": days, "exits": why}


if __name__ == "__main__":
    B = build(load())
    out = {"days": len(B), "first": min(B), "last": max(B), "part_a": part_a(B), "part_b": {}}
    base = {}
    for tr in (0.02, 0.05, 0.10, 0.15, 0.25, None):
        for hold in (15, 30, 60, None):
            out["part_b"][f"live_filters|trail={tr}|hold={hold}"] = summ(part_b(B, tr, hold, base))
    for name, flt in (("no_windows", {"windows": False}), ("no_strict", {"strict": False}),
                      ("no_strict_loose_entry", {"strict": False, "loose_entry": True}),
                      ("no_breadth", {"breadth": False}), ("no_move5", {"move5": False}),
                      ("no_chg", {"chg": False}), ("strict_exit", {"strict_exit": True}),
                      ("no_senti_exit", {"loose_exit": False})):
        for tr, hold in ((0.02, 15), (0.05, 15), (0.15, 60), (None, 30)):
            out["part_b"][f"{name}|trail={tr}|hold={hold}"] = summ(part_b(B, tr, hold, flt))
    # B-1727 (user 2026-11-25 "pick short movement only, quick entry, quick exit, single leg"): holds <= 15 min.
    for mode, flt in (("momentum", {}), ("momentum_nomove5", {"move5": False}), ("pullback", {})):
        for hold in (5, 10, 15):
            for tr in (0.02, 0.05, 0.08, 0.12):
                for tg in (None, 0.03, 0.05, 0.08, 0.12):
                    out["part_b"][f"short|{mode}|hold={hold}|trail={tr}|target={tg}"] = summ(
                        part_b(B, tr, hold, flt, tg, "pullback" if mode == "pullback" else "momentum"))
    json.dump(out, open("docs/fno_v3_assumption_study.json", "w"), indent=1)
    print("ok", out["days"], out["first"], out["last"])
