#!/usr/bin/env python3
"""Run the full pytest suite as N parallel shards (default 4 = this container's CPUs), balanced by file run time.

Thumb rule (docs/TEST_SUITE_THUMB_RULES.md, user 2026-10-28 "to save time"): the pre-push suite always runs this way.
Each shard runs in its own tar copy of the repo, so shards never share paper_trades.db or other files on disk.
Per-file times from the last run are kept in scripts/test_file_times.json (falls back to file size for new files).
Exit code 0 only when every shard passed. Usage: python3 scripts/run_tests_parallel.py [-n 4] [--out DIR]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMES = os.path.join(ROOT, "scripts", "test_file_times.json")


def _shards(files, n, times):
    cost = {f: times.get(f, os.path.getsize(os.path.join(ROOT, f)) / 2000.0) for f in files}
    bins = [[0.0, []] for _ in range(n)]
    for f in sorted(files, key=lambda f: -cost[f]):  # greedy longest-first into the lightest shard
        b = min(bins, key=lambda b: b[0])
        b[0] += cost[f]
        b[1].append(f)
    for b in bins:
        b[1].sort()  # alphabetical inside a shard, the order the suite has always run in
    return bins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--out", default=tempfile.gettempdir())
    a = ap.parse_args()
    files = sorted("tests/" + f for f in os.listdir(os.path.join(ROOT, "tests")) if f.startswith("test_") and f.endswith(".py"))
    try:
        times = json.load(open(TIMES))
    except Exception:
        times = {}
    bins = _shards(files, a.n, times)
    work = tempfile.mkdtemp(prefix="suite_", dir=a.out)
    procs = []
    t0 = time.time()
    for i, (_c, fs) in enumerate(bins):
        d = os.path.join(work, f"s{i}")
        os.makedirs(d)
        subprocess.run(f"tar --exclude=.git --exclude=.claude/worktrees --exclude=paper_trades.db -cf - . | tar -xf - -C {d}",
                       shell=True, cwd=ROOT, check=True)
        log = open(os.path.join(a.out, f"shard{i}.log"), "w")
        procs.append((i, d, log, subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={d}/junit.xml", *fs],
            cwd=d, stdout=log, stderr=subprocess.STDOUT)))
    ok = True
    new_times = dict(times)
    for i, d, log, p in procs:
        rc = p.wait()
        log.close()
        tail = open(log.name).read().strip().splitlines()[-1:] or ["(no output)"]
        print(f"shard {i}: rc={rc} {tail[0]}")
        ok = ok and rc == 0
        try:
            per = {}
            for tc in ET.parse(os.path.join(d, "junit.xml")).iter("testcase"):
                f = "tests/" + tc.get("classname", "").split(".")[1] + ".py" if tc.get("classname", "").startswith("tests.") else None
                if f:
                    per[f] = per.get(f, 0.0) + float(tc.get("time") or 0)
            new_times.update({k: round(v, 2) for k, v in per.items()})
        except Exception:
            pass
    print(f"wall time {time.time() - t0:.0f}s, logs in {a.out}/shard*.log -> {'ALL PASSED' if ok else 'FAILED'}")
    json.dump({k: new_times[k] for k in sorted(new_times) if k in files}, open(TIMES, "w"), indent=0)
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
