"""B-1692: print only the named keys from the JSON body in a diag-curl runner log (token discipline).
usage: python3 scripts/diag_json.py <log> key [key.sub ...]   (no keys -> top-level key list)"""
import json
import sys


def body(text):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                d, _ = dec.raw_decode(text[i:])
            except ValueError:
                continue
            if isinstance(d, dict) and len(d) > 1:
                return d
    return {}


def get(d, path):
    for p in path.split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


if __name__ == "__main__":
    d = body(open(sys.argv[1], errors="replace").read())
    if len(sys.argv) < 3:
        print(sorted(d))
    for k in sys.argv[2:]:
        v = get(d, k)
        print(f"{k}: {json.dumps(v)[:400]}")
