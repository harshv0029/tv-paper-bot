"""B-804: completes missing gross PFnet (Metrics.pfgross) of viable registry rows from raw run artifacts kept in docs/backtest_data/.
A row is filled ONLY on an exact reproduction: same tag, same n_trades, PFnet within 0.011, and every matching artifact record agrees on
pfgross (within 0.011).  Stored values are never overwritten (only None/0 pfgross is completed); unmatched rows are left alone.
Audit 2026-10-12 IST against docs/backtest_data + branch data/run-artifacts: 0 of the 371 viable rows lacking pfgross had an exact
reproduction among them (5 non-viable rows - dirsys cross_dullgate x3, macdh diverge short x2 - do reproduce exactly and are filled); artifacts carry the same tags but from later/different samples: n differs by 1-3 for oneil/elder gaps, by thousands for
minervini lab vs replay, 651 vs 659 for sector_rotation; pattern_lab/mcx/combo_lab/intermarket/breadth have no raw artifact in git;
exit_family has an empty gross column).  The module is therefore a no-op today and fills automatically if an exact artifact is added."""
import csv
import dataclasses
import json
import os
from collections import defaultdict

import strategy_registry as sr

_D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def _num(x):
    try:
        return None if x in (None, "", "NA", "None") else float(x)
    except Exception:
        return None


def _walk(o, f, out):
    if isinstance(o, dict):
        for tk in ("tag", "tag_lab_v1", "tag_replay_v2", "name"):
            t = o.get(tk)
            if isinstance(t, str):
                m = o.get("metrics", o)
                if isinstance(m, dict):
                    n = _num(m.get("n"))
                    pn = _num(m.get("pfnet", m.get("pfnet_net")))
                    pg = _num(m.get("pfgross", m.get("pf_gross", m.get("pfnet_gross"))))
                    if n is not None and pn is not None and pg:
                        out[t].append((n, pn, pg, f))
        for k, v in o.items():
            if isinstance(v, dict) and isinstance(k, str) and "__" in k:
                n = _num(v.get("n"))
                pn = _num(v.get("pfnet"))
                pg = _num(v.get("pfgross", v.get("pf_gross")))
                if n is not None and pn is not None and pg:
                    out[k].append((n, pn, pg, f))
            _walk(v, f, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, f, out)


def _collect(directory=_D):
    out = defaultdict(list)
    try:
        names = sorted(os.listdir(directory))
    except Exception:
        return out
    for fn in names:
        p = os.path.join(directory, fn)
        try:
            if fn.endswith(".json"):
                _walk(json.load(open(p)), fn, out)
            elif fn.endswith(".tsv"):
                for r in csv.DictReader(open(p), delimiter="\t"):
                    t = r.get("tag")
                    pg = _num(r.get("pfgross", r.get("pfnet_gross", r.get("pf_gross"))))
                    pn = _num(r.get("pfnet", r.get("pfnet_net")))
                    n = _num(r.get("n"))
                    if t and pg and pn is not None and n is not None:
                        out[t].append((n, pn, pg, fn))
        except Exception:
            continue
    return out


def apply(directory=_D):
    cands = _collect(directory)
    filled = 0
    for i, s in enumerate(sr.REGISTRY):
        try:
            m = s.metrics
            if not m or m.pfgross or s.name not in cands:
                continue
            good = [c for c in cands[s.name] if int(c[0]) == m.n_trades and abs(c[1] - m.pfnet) <= 0.011]
            if not good or max(c[2] for c in good) - min(c[2] for c in good) > 0.011:
                continue
            files = ",".join(sorted({c[3] for c in good}))
            sr.REGISTRY[i] = dataclasses.replace(s, metrics=dataclasses.replace(
                m, pfgross=float(good[0][2]),
                run_ref=f"{m.run_ref}; pfgross completed from {files} (exact reproduction, B-804)"))
            filled += 1
        except Exception:
            continue
    return filled
