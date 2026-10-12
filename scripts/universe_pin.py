"""Shared universe pinning for research runs (B-841 / B-851).

Problem: yfinance fetch flakiness changes which symbols end up in a full-universe run (7049 vs 7059
fetched), and one extra symbol moved a huge-n cell's PFnet 0.648 -> 0.412. A PFnet difference between
two runs must reflect logic, not universe drift.

Usage in a shard:
    syms = universe_pin.select_universe(full_syms, pin_file)      # before sharding
    ... fetch loop collecting `got` (list of symbols that produced data) ...
    meta = universe_pin.shard_meta(syms, got, pin_file, tolerance)  # raises PinDriftError past tolerance
    json.dump({..., **meta}, ...)
At merge: `universe_pin.merge_fetched(parts)` -> sorted union, store as "fetched_symbols"; that merged
JSON (or a plain JSON list) is the pin file for the next run (pass --pin-file / env PIN_FILE).
Only the symbol SET is pinned; yfinance bar content can still differ between runs.
"""
from __future__ import annotations

import json
import os

DEFAULT_TOLERANCE = 0.002  # fraction of pinned symbols allowed to fail to fetch on a pinned rerun


class PinDriftError(RuntimeError):
    pass


def load_pin(path):
    """Pinned symbol list from a JSON list or a dict with fetched_symbols / symbols; None if no path."""
    if not path:
        return None
    with open(path) as f:
        d = json.load(f)
    if isinstance(d, dict):
        d = d.get("fetched_symbols") or d.get("symbols")
    if not isinstance(d, list) or not d:
        raise PinDriftError(f"pin file {path} holds no symbol list")
    return sorted(set(d))


def select_universe(full_syms, pin_file=None):
    """Symbols to iterate (pre-sharding): the pinned list if given, else the sorted full universe."""
    pin = load_pin(pin_file)
    return pin if pin is not None else sorted(set(full_syms))


def check_drift(attempted, got, pinned, tolerance=DEFAULT_TOLERANCE):
    missing = sorted(set(attempted) - set(got))
    drift = len(missing) / len(attempted) if attempted else 0.0
    if pinned and drift > tolerance:
        raise PinDriftError(f"universe drift {drift:.4%} > tolerance {tolerance:.4%}: "
                            f"{len(missing)}/{len(attempted)} pinned symbols not fetched (first: {missing[:10]})")
    return drift, missing


def shard_meta(attempted, got, pin_file=None, tolerance=DEFAULT_TOLERANCE):
    """Fields to add to a shard's output JSON; fails loudly on a pinned run past tolerance."""
    pinned = bool(pin_file)
    drift, missing = check_drift(attempted, got, pinned, tolerance)
    return {"fetched_symbols": sorted(set(got)), "pinned": pinned, "pin_drift": round(drift, 6),
            "pin_missing": missing}


def merge_fetched(parts):
    """Sorted union of fetched_symbols across shard dicts (empty if shards predate pinning)."""
    out = set()
    for d in parts:
        out.update(d.get("fetched_symbols", []))
    return sorted(out)


def env_args():
    return os.environ.get("PIN_FILE") or None, float(os.environ.get("PIN_TOLERANCE", DEFAULT_TOLERANCE))


def add_args(ap):
    ap.add_argument("--pin-file", default=os.environ.get("PIN_FILE", ""),
                    help="JSON list / merged output with fetched_symbols: rerun on exactly this universe")
    ap.add_argument("--pin-tolerance", type=float, default=float(os.environ.get("PIN_TOLERANCE", DEFAULT_TOLERANCE)),
                    help="max fraction of pinned symbols allowed to fail fetching before the run aborts")
