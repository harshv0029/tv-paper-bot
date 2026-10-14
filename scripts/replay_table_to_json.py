"""B-1230: parse a replay MERGE-job log into the docs/backtest_data rows[].metrics schema, without dropping any field.

Input lines (as printed by scripts/*_replay.py merge modes), optionally behind a GitHub Actions timestamp prefix
('2026-10-14T05:12:33.4567890Z '):
  <tag> n <N> pfnet <X> pfgross <Y> win <W> hold_h <H> {<exit-reason breakdown dict>}
  <tag> n <N> pfnet <X> pfgross <Y> win <W> hold_bars <H> {<exit-reason breakdown dict>}
hold_h -> metrics.avg_held_hours, hold_bars -> metrics.avg_held_bars (never converted or guessed). Output:
{"source", "run_id", "cost_round_trip_pct", "note", "rows": [{"tag", "metrics": {n, pfnet, pfgross, win_pct, avg_held_*,
exit_reasons}}]}. exit_reasons is kept verbatim (every reason, every sub-field, parsed with ast.literal_eval).
A line that mentions ' pfnet ' but does not match the full format, has an unparsable dict/number, or repeats a tag is a
LOUD error (ValueError / exit code 2 with the 1-based line number); lines without ' pfnet ' are log noise and are only
counted. Numbers 'None' become null; 'inf'/'nan' are kept as floats (written as Infinity/NaN, which json.load reads back).
Usage: python3 scripts/replay_table_to_json.py LOG OUT.json [--run-id ID] [--cost-pct 0.8] [--expect-rows N]
"""
import argparse
import ast
import json
import math
import re
import sys

TS = re.compile(r"^﻿?\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s?")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LINE = re.compile(
    r"^(?P<tag>[A-Za-z0-9_.\-]+) n (?P<n>\d+) pfnet (?P<pfnet>\S+) pfgross (?P<pfgross>\S+) win (?P<win>\S+) "
    r"(?P<hk>hold_h|hold_bars) (?P<hv>\S+) (?P<reasons>\{.*\})$")


def _num(tok, what, lineno):
    if tok == "None":
        return None
    try:
        return float(tok)
    except ValueError:
        raise ValueError(f"line {lineno}: cannot parse {what} {tok!r}")


def clean(raw):
    s = ANSI.sub("", raw.rstrip("\n").rstrip("\r"))
    s = TS.sub("", s)
    return s.strip()


def parse_log(text):
    """-> (rows, noise_line_count). Raises ValueError on any malformed table line."""
    rows, seen, noise = [], {}, 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        s = clean(raw)
        if " pfnet " not in s:
            noise += 1
            continue
        m = LINE.match(s)
        if not m:
            raise ValueError(f"line {lineno}: table-like line does not match '<tag> n N pfnet X pfgross Y win W hold_h|hold_bars H "
                             f"{{reasons}}': {s[:200]!r}")
        tag = m.group("tag")
        if tag in seen:
            raise ValueError(f"line {lineno}: duplicate tag {tag!r} (first on line {seen[tag]}); merge logs must have one row per tag")
        try:
            reasons = ast.literal_eval(m.group("reasons"))
        except (ValueError, SyntaxError) as ex:
            raise ValueError(f"line {lineno}: exit-reason dict not parseable ({ex}): {m.group('reasons')[:200]!r}")
        if not isinstance(reasons, dict):
            raise ValueError(f"line {lineno}: exit reasons must be a dict")
        hold_key = "avg_held_hours" if m.group("hk") == "hold_h" else "avg_held_bars"
        metrics = {"n": int(m.group("n")), "pfnet": _num(m.group("pfnet"), "pfnet", lineno),
                   "pfgross": _num(m.group("pfgross"), "pfgross", lineno),
                   "win_pct": _num(m.group("win"), "win", lineno),
                   hold_key: _num(m.group("hv"), m.group("hk"), lineno), "exit_reasons": reasons}
        for k in ("pfnet", "win_pct", hold_key):
            if metrics[k] is None:
                raise ValueError(f"line {lineno}: {k} is None (refusing to store a row with a missing core metric)")
        seen[tag] = lineno
        rows.append({"tag": tag, "metrics": metrics})
    return rows, noise


def build(text, source, run_id=None, cost_pct=None, expect_rows=None):
    rows, noise = parse_log(text)
    if not rows:
        raise ValueError("no table lines found in the log (is this the merge job's log?)")
    if expect_rows is not None and len(rows) != expect_rows:
        raise ValueError(f"expected {expect_rows} rows, parsed {len(rows)}")
    return {"source": source, "run_id": run_id, "cost_round_trip_pct": cost_pct,
            "note": f"parsed from a merge-job log by scripts/replay_table_to_json.py ({len(rows)} rows, {noise} non-table lines ignored)",
            "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("log")
    ap.add_argument("out")
    ap.add_argument("--run-id")
    ap.add_argument("--cost-pct", type=float)
    ap.add_argument("--expect-rows", type=int)
    a = ap.parse_args(argv)
    try:
        out = build(open(a.log, encoding="utf-8", errors="strict").read(), a.log, a.run_id, a.cost_pct, a.expect_rows)
    except ValueError as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 2
    json.dump(out, open(a.out, "w"), indent=1)
    bad = [r["tag"] for r in out["rows"] if any(isinstance(v, float) and not math.isfinite(v) for v in r["metrics"].values())]
    print(f"wrote {a.out}: {len(out['rows'])} rows" + (f"; non-finite metrics on {len(bad)} tags (kept as-is)" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
