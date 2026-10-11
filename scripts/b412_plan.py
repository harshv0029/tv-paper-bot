"""Prints the B-412 job matrix as JSON: the viable minervini_vcp lab variants (derived from the
registry at dispatch time, never a stored flag) plus the breakeven-at-1R strategies. Capped at 40."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

BE_STRATS = ["minervini_long", "minervini_short", "ob_long", "vp_long", "gap_long", "gap_short"]


def lab_variants(registry):
    out = []
    for s in registry:
        n = s.name
        if n.startswith("minervini_vcp__") and n.endswith("__long__1d__h60__v1") and s.is_viable():
            v = n[len("minervini_vcp__"):-len("__long__1d__h60__v1")]
            out.append(v)
    return out


def build(registry):
    inc = [{"mode": "lab", "name": v} for v in lab_variants(registry)]
    inc += [{"mode": "be1r", "name": s} for s in BE_STRATS]
    if len(inc) > 40:
        raise SystemExit(f"matrix too large: {len(inc)}")
    return {"include": inc}


if __name__ == "__main__":
    import strategy_registry as r
    print(json.dumps(build(r.REGISTRY)))
