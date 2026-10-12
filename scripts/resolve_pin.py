"""Resolve a universe pin file from a downloaded artifact directory (B-841 / B-851).

Usage: python3 scripts/resolve_pin.py <dir_or_json> <out.json>
Scans <dir> recursively for *.json holding a non-empty "fetched_symbols" list (the merged result of an earlier
pin-aware run) and writes the sorted symbol list to <out.json>, which is then passed as PIN_FILE. Exits 1 and
writes nothing when no usable file exists, so a pinned dispatch never silently runs unpinned.
"""
import glob
import json
import os
import sys


def find_pin(path):
    files = [path] if os.path.isfile(path) else sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True))
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        syms = d.get("fetched_symbols") if isinstance(d, dict) else None
        if isinstance(syms, list) and syms:
            return sorted(set(syms)), f
    return None, None


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 2:
        print(__doc__)
        return 2
    syms, src = find_pin(a[0])
    if not syms:
        print(f"ERROR: no fetched_symbols found under {a[0]} (the source run predates pinning?)", file=sys.stderr)
        return 1
    json.dump(syms, open(a[1], "w"))
    print(f"pin: {len(syms)} symbols from {src} -> {a[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
