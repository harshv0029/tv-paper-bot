"""B-1231: READ-ONLY report of strategy tags present in saved docs/backtest_data/*.json but missing from
strategy_registry.REGISTRY (so the registration backlog is visible). Writes nothing to the repo unless --json is given.

A tag is collected from a saved file when it is (a) the value of a 'tag' / 'name' / 'strategy' key, or (b) any dict key, and it
matches the naming grammar <family>__<variant>__<dir>__... (lowercase [a-z0-9_], at least three '__' separated fields and a
trailing '__v<N>'). Legacy tags (no __v<N>) are not guessed at. Files that are not JSON are listed as skipped, never silently
dropped. REGISTRY names come from the real strategy_registry import (the extension modules it loads are included).
Usage: python3 scripts/missing_registry_tags.py [--data-dir docs/backtest_data] [--json OUT.json] [--fail-on-missing] [--top N]
"""
import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TAG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*(?:__[a-z0-9]+(?:_[a-z0-9]+)*){2,}__v\d+$")
NAME_KEYS = ("tag", "name", "strategy")


def collect_tags(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and TAG.match(k):
                out.add(k)
            if k in NAME_KEYS and isinstance(v, str) and TAG.match(v):
                out.add(v)
            collect_tags(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_tags(v, out)
    return out


def scan(data_dir, registry_names):
    per_file, skipped = {}, []
    for f in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        try:
            tags = collect_tags(json.load(open(f)))
        except (ValueError, OSError) as ex:
            skipped.append({"file": os.path.basename(f), "reason": str(ex)[:120]})
            continue
        per_file[os.path.basename(f)] = {"tags": len(tags), "missing": sorted(t for t in tags if t not in registry_names)}
    return per_file, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "docs", "backtest_data"))
    ap.add_argument("--json")
    ap.add_argument("--fail-on-missing", action="store_true")
    ap.add_argument("--top", type=int, default=5, help="sample of missing tags to print per file")
    a = ap.parse_args(argv)
    import strategy_registry as sr
    names = {s.name for s in sr.REGISTRY}
    per_file, skipped = scan(a.data_dir, names)
    uniq = sorted({t for v in per_file.values() for t in v["missing"]})
    print(f"registry tags: {len(names)}; files scanned: {len(per_file)}; skipped (not JSON): {len(skipped)}")
    for f, v in per_file.items():
        if v["missing"]:
            print(f"{f}: {len(v['missing'])} of {v['tags']} tags missing, e.g. {', '.join(v['missing'][:a.top])}")
    print(f"unique missing tags across files: {len(uniq)}")
    if a.json:
        json.dump({"registry_tags": len(names), "per_file": per_file, "skipped": skipped, "unique_missing": uniq},
                  open(a.json, "w"), indent=1)
        print("wrote", a.json)
    return 1 if (a.fail_on_missing and uniq) else 0


if __name__ == "__main__":
    sys.exit(main())
