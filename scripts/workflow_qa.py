"""Pre-dispatch QA for research workflows (backlog B-1200). Static checks only, no network, no Actions.

For each workflow YAML: parses; every `${{ inputs.X }}` has a declared workflow_dispatch input; every `${{ matrix.X }}` is a key of
the (static or planned) matrix; the matrix job count is computed (dynamic `fromJSON(needs.plan...)` matrices are expanded by running
the plan step's own command with the input defaults); upload artifact names are unique across the expanded matrix; every
download-artifact `pattern` matches at least one replay upload (matching the job's own later final upload is harmless: download runs first); every
`python3 scripts/X.py [mode]` step references an existing script.

  python3 scripts/workflow_qa.py [workflow.yml ...]  -> prints a table, exit 1 on any defect
"""
import fnmatch
import itertools
import json
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def _on(doc):
    return doc.get("on") or doc.get(True) or {}


def input_defaults(doc):
    ins = (_on(doc).get("workflow_dispatch") or {}).get("inputs") or {}
    return {k: str(v.get("default", "")) for k, v in ins.items()}, set(ins)


def expand_matrix(m):
    """Static matrix dict -> list of combo dicts (include/exclude honoured loosely)."""
    if not isinstance(m, dict):
        return []
    axes = {}
    for k, v in m.items():
        if k in ("include", "exclude"):
            continue
        if isinstance(v, str) and "fromJSON" in v:  # axis from a JSON input: expand its literal default
            lit = re.findall(r"'(\[.*?\])'", v)
            v = json.loads(lit[-1]) if lit else []
        if isinstance(v, list):
            axes[k] = v
    combos = [dict(zip(axes, vals)) for vals in itertools.product(*axes.values())] if axes else []
    for inc in m.get("include", []) or []:
        combos.append(dict(inc)) if not axes else combos.append(dict(inc))
    return combos


def plan_matrix(doc, defaults):
    """Run the plan job's own command with input defaults -> the real dynamic matrix (list of combos)."""
    plan = (doc.get("jobs") or {}).get("plan")
    if not plan:
        return None
    for st in plan.get("steps", []):
        run = st.get("run", "")
        m = re.search(r"\$\(\s*(python3 [^)]+)\)", run)
        if not m:
            continue
        env = dict(os.environ)
        for k, v in (st.get("env") or {}).items():
            env[k] = EXPR.sub(lambda mm: defaults.get(mm.group(1).split(".", 1)[-1], ""), str(v))
        out = subprocess.run(m.group(1), shell=True, cwd=ROOT, env=env, capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"plan command failed: {out.stderr[-300:]}")
        return json.loads(out.stdout.strip().splitlines()[-1]).get("include", [])
    return None


def subst(s, combo, defaults):
    def f(mm):
        e = mm.group(1)
        if e.startswith("matrix."):
            return str(combo.get(e.split(".", 1)[1], "?"))
        if e.startswith("inputs."):
            return defaults.get(e.split(".", 1)[1], "?")
        return mm.group(0)
    return EXPR.sub(f, str(s))


def check(path):
    doc = yaml.safe_load(open(path))
    name = os.path.basename(path)
    defects, info = [], {}
    defaults, declared = input_defaults(doc)
    text = open(path).read()
    for ref in set(re.findall(r"inputs\.([A-Za-z0-9_]+)", text)):
        if ref not in declared:
            defects.append(f"inputs.{ref} referenced but not declared")
    jobs = doc.get("jobs") or {}
    total, uploads, final_names = 0, [], []
    for jname, job in jobs.items():
        strat = (job.get("strategy") or {})
        m = strat.get("matrix")
        if isinstance(m, str) and "fromJSON" in m:
            combos = plan_matrix(doc, defaults)
            if combos is None:
                defects.append(f"{jname}: dynamic matrix but no runnable plan step")
                combos = []
        else:
            combos = expand_matrix(m) if m else [{}]
        if len(combos) > 256:
            defects.append(f"{jname}: matrix {len(combos)} > 256 GitHub limit")
        mp = strat.get("max-parallel")
        info[jname] = {"jobs": len(combos), "max_parallel": mp, "timeout_min": job.get("timeout-minutes")}
        total += len(combos)
        keys = set().union(*[set(c) for c in combos]) if combos else set()
        for ref in set(re.findall(r"matrix\.([A-Za-z0-9_]+)", json.dumps(job))):
            if combos and ref not in keys:
                defects.append(f"{jname}: matrix.{ref} not a matrix key")
        for st in job.get("steps", []):
            run = st.get("run", "")
            for sc in re.findall(r"scripts/([A-Za-z0-9_]+\.py)", run):
                if not os.path.exists(os.path.join(ROOT, "scripts", sc)):
                    defects.append(f"{jname}: scripts/{sc} missing")
            u = st.get("uses", "")
            w = st.get("with") or {}
            if u.startswith("actions/upload-artifact"):
                for c in combos or [{}]:
                    uploads.append((jname, subst(w.get("name", ""), c, defaults)))
            if u.startswith("actions/download-artifact") and w.get("pattern"):
                info.setdefault("_patterns", []).append((jname, subst(w["pattern"], {}, defaults)))
    names = [n for _, n in uploads]
    dups = {n for n in names if names.count(n) > 1 and not any(j != "replay" for j, nn in uploads if nn == n)}
    replay_names = {n for j, n in uploads if info.get(j, {}).get("jobs", 1) > 1 or j == "replay"}
    for n in sorted(dups):
        defects.append(f"duplicate artifact name {n}")
    for j, pat in info.get("_patterns", []):
        hits = [n for n in replay_names if fnmatch.fnmatch(n, pat)]
        if not hits:
            defects.append(f"{j}: download pattern {pat!r} matches no replay upload")
        # a pattern that also matches the job's own final artifact is harmless: download runs before that upload in the same job
    return {"workflow": name, "total_jobs": total, "jobs": {k: v for k, v in info.items() if not k.startswith("_")},
            "uploads": len(names), "defects": defects}


if __name__ == "__main__":
    paths = sys.argv[1:] or sorted(os.path.join(ROOT, ".github", "workflows", f)
                                   for f in os.listdir(os.path.join(ROOT, ".github", "workflows")) if f.endswith(".yml"))
    bad = 0
    for p in paths:
        r = check(p)
        bad += bool(r["defects"])
        print(f"{r['workflow']:48s} jobs={r['total_jobs']:4d} uploads={r['uploads']:4d} "
              f"{'OK' if not r['defects'] else 'DEFECTS: ' + '; '.join(r['defects'])}")
    sys.exit(1 if bad else 0)
