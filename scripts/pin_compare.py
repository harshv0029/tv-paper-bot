"""Compare two merged research results for reproducibility (B-841 / B-851).

Usage: python3 scripts/pin_compare.py <A dir|json> <B dir|json> [--tol 1e-6] [--floor 1.0] [--json out.json]
                                       [--require-identical]
Each side is a merged result JSON (or a directory holding one) with "rows" [{tag, n, pfnet, ...}] and, for
pin-aware runs, "fetched_symbols". Reports: symbol-set equality, tags only on one side, n differences, max/mean
|dPFnet|, and tags that cross the viability floor. Verdict IDENTICAL means same symbol set, same tag set, same n
and |dPFnet| <= tol for every tag. With --require-identical the exit code is 1 otherwise (B-841 close test).
"""
import argparse
import glob
import json
import os
import sys


def load_result(path):
    files = [path] if os.path.isfile(path) else sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True))
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("rows"), list) and d["rows"] and "tag" in d["rows"][0]:
            return d
    raise SystemExit(f"no merged result with rows[] under {path}")


def compare(a, b, tol=1e-6, floor=1.0):
    ra = {r["tag"]: r for r in a["rows"]}
    rb = {r["tag"]: r for r in b["rows"]}
    sa, sb = a.get("fetched_symbols"), b.get("fetched_symbols")
    sym = {"a_count": len(sa) if sa else None, "b_count": len(sb) if sb else None}
    if sa and sb:
        sym.update(equal=set(sa) == set(sb), only_a=sorted(set(sa) - set(sb))[:20], only_b=sorted(set(sb) - set(sa))[:20])
    else:
        sym["equal"] = None  # unknown: at least one run predates pinning
    common = sorted(set(ra) & set(rb))
    diffs, n_diff, crossed = [], [], []
    for t in common:
        pa, pb = ra[t].get("pfnet"), rb[t].get("pfnet")
        if ra[t].get("n") != rb[t].get("n"):
            n_diff.append({"tag": t, "n_a": ra[t].get("n"), "n_b": rb[t].get("n")})
        if pa is None or pb is None:
            if pa != pb:
                diffs.append((t, float("inf")))
            continue
        diffs.append((t, abs(pa - pb)))
        if (pa >= floor) != (pb >= floor):
            crossed.append({"tag": t, "pfnet_a": pa, "pfnet_b": pb})
    vals = [d for _, d in diffs]
    out = {"symbols": sym, "tags_common": len(common), "tags_only_a": sorted(set(ra) - set(rb))[:20],
           "tags_only_b": sorted(set(rb) - set(ra))[:20], "n_only_a": len(set(ra) - set(rb)),
           "n_only_b": len(set(rb) - set(ra)), "n_differs": len(n_diff), "n_diff_examples": n_diff[:10],
           "max_abs_dpfnet": max(vals) if vals else 0.0, "mean_abs_dpfnet": (sum(vals) / len(vals)) if vals else 0.0,
           "worst_tags": sorted(diffs, key=lambda x: -x[1])[:10], "crossed_floor": crossed, "floor": floor, "tol": tol}
    out["identical"] = bool(sym["equal"] is not False and not out["n_only_a"] and not out["n_only_b"]
                            and not n_diff and out["max_abs_dpfnet"] <= tol)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--tol", type=float, default=1e-6)
    ap.add_argument("--floor", type=float, default=1.0)
    ap.add_argument("--json")
    ap.add_argument("--require-identical", action="store_true")
    args = ap.parse_args(argv)
    res = compare(load_result(args.a), load_result(args.b), args.tol, args.floor)
    print(f"symbols: {res['symbols']}")
    print(f"tags common {res['tags_common']}, only A {res['n_only_a']}, only B {res['n_only_b']}, n differs {res['n_differs']}")
    print(f"max |dPFnet| {res['max_abs_dpfnet']:.4f}  mean {res['mean_abs_dpfnet']:.4f}  crossed {args.floor}: {len(res['crossed_floor'])}")
    for t, d in res["worst_tags"]:
        print(f"  {d:8.4f}  {t}")
    print("VERDICT:", "IDENTICAL" if res["identical"] else "DIFFERENT")
    if args.json:
        json.dump(res, open(args.json, "w"), indent=1)
    return 1 if args.require_identical and not res["identical"] else 0


if __name__ == "__main__":
    sys.exit(main())
