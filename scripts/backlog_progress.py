#!/usr/bin/env python3
"""Generate docs/BACKLOG_PROGRESS.md from docs/ACTIONABLES_BACKLOG.md (read-only on the backlog).

Rows start '| B-'. The table header says ID|Item|Status|Priority|Notes, but many rows have
shifted cells, so status/priority are located by CONTENT (priority token P0-P3/High/Medium/Low,
status = the status-looking cell next to it), falling back to the header positions.
Usage: python3 scripts/backlog_progress.py [--out docs/BACKLOG_PROGRESS.md]
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "ACTIONABLES_BACKLOG.md")
OUT = os.path.join(ROOT, "docs", "BACKLOG_PROGRESS.md")

PRIO = {"P0": "P0", "P1": "P1", "P2": "P2", "P3": "P3", "HIGH": "P1", "MEDIUM": "P2", "LOW": "P3", "INFO": "Info"}
STATUS_RE = re.compile(
    r"^(DONE|OPEN|CLOSED|TODO|PARTIAL|MERGED|PARKED|BLOCKED|PENDING|HARNESS|IN-PROGRESS|BUILT|OWNER|WAITING|"
    r"RESEARCH|NEEDS|DEFERRED|SUPERSEDED|WONTFIX|IN PROGRESS)", re.I)
OWED_WORDS = ["owed", "remaining", "open:", "blocked", "pending", "verify", "needs", "unverified",
              "owner", "not merged", "todo", "follow-up", "awaiting", "waiting"]


def prio_of(cell):
    return PRIO.get(cell.strip().upper())


def split_row(line):
    return [c.strip() for c in line.rstrip().split("|")[1:-1]]


def parse_row(line, header_cols):
    c = split_row(line)
    if not c:
        return None
    rid = c[0]
    cells = c[1:]
    pi = next((i for i, x in enumerate(cells[:6]) if prio_of(x)), None)
    status = item = None
    prio = "P?"
    if pi is not None:
        prio = prio_of(cells[pi])
        for j in (pi - 1, pi + 1):
            if 0 <= j < len(cells) and STATUS_RE.match(cells[j]) and prio_of(cells[j]) is None:
                status = cells[j]
                break
    if status is None:
        hs = header_cols.get("status", 2) - 1
        status = cells[hs] if 0 <= hs < len(cells) else "UNKNOWN"
        if prio == "P?":
            hp = header_cols.get("priority", 3) - 1
            if 0 <= hp < len(cells):
                prio = prio_of(cells[hp]) or "P?"
    if prio == "P?":
        prio = next((prio_of(x) for x in cells[:8] if prio_of(x)), "P?")
    for i, x in enumerate(cells):
        if i == pi or x == status or (STATUS_RE.match(x) and len(x) < 80):
            continue
        item = x
        break
    if item is None:
        item = cells[0] if cells else ""
    return {"id": rid, "status": status, "prio": prio, "item": item, "text": " ".join(cells)}


def norm_status(s):
    u = s.upper().replace("_", "-")
    head = u[:70]
    if u.startswith("RENDER") or u.startswith("OWNER"):
        return "OWNER-ACTION"
    if "NOT MERGED" in head or "UNMERGED" in head or "ON BRANCH" in head:
        return "BUILT-ON-BRANCH"
    if u.startswith("DONE-PENDING") or "PENDING-VERIFY" in head:
        return "DONE-PENDING-VERIFY"
    if u.startswith("CLOSED-AS-EXPLAINED"):
        return "CLOSED-AS-EXPLAINED"
    if u.startswith("HARNESS-BUILT") or u.startswith("HARNESS-RUN-DONE"):
        return re.match(r"[A-Z][A-Z0-9-]*", u).group(0)
    if u.startswith("CLOSED"):
        return "CLOSED"
    if re.search(r"/ (OPEN|TODO)", head):
        return "PARTIAL"
    if u.startswith("DONE-MERGED") or u.startswith("MERGED"):
        return "DONE-MERGED"
    m = re.match(r"[A-Z][A-Z0-9-]*", u)
    return m.group(0) if m else "UNKNOWN"


CLOSED = {"DONE", "CLOSED", "CLOSED-AS-EXPLAINED", "DONE-MERGED", "HARNESS-RUN-DONE", "SUPERSEDED", "WONTFIX"}


def short_title(item, n=110):
    t = re.sub(r"\*\*|`", "", item)
    t = re.split(r"\s+Decision \d{4}-\d\d-\d\d|\s+\d{4}-\d\d-\d\d IST closure", t)[0]
    t = re.split(r"(?<=[a-z\)])\.\s", t)[0].strip()
    return (t[: n - 3] + "...") if len(t) > n else t


def owed_keywords(text):
    low = text.lower()
    return [w for w in OWED_WORDS if w in low]


def group_of(r):
    low = r["text"].lower()
    st = r["ns"]
    if st == "OWNER-ACTION" or "owner-action" in low or "owner action" in low or "only the user" in low \
            or "user must" in low or "render dashboard" in low or "credentials" in low:
        return "needs-owner"
    if st in ("DONE-PENDING-VERIFY", "BUILT-ON-BRANCH", "BLOCKED-ON-RUN", "BLOCKED", "PENDING") \
            or st.startswith("HARNESS-BUILT") or "blocked-on-run" in low or "run pending" in low:
        return "waiting-on-workflow/deploy"
    if re.search(r"backtest|replay|sweep|research|pfnet|indicator|full-universe", r["item"].lower()):
        return "research-queue"
    return "ready-to-build"


def main(out=OUT):
    lines = open(SRC, encoding="utf-8").read().splitlines()
    hdr = {}
    for l in lines:
        if l.startswith("| ID"):
            for i, h in enumerate(split_row(l)):
                hl = h.lower()
                for k in ("status", "priority"):
                    if hl.startswith(k):
                        hdr[k] = i
            break
    rows = []
    for l in lines:
        if l.startswith("| B-"):
            r = parse_row(l, hdr)
            if r:
                r["ns"] = norm_status(r["status"])
                r["closed"] = r["ns"] in CLOSED
                rows.append(r)
    sc = collections.Counter(r["ns"] for r in rows)
    pc = collections.Counter(r["prio"] for r in rows)
    openr = [r for r in rows if not r["closed"]]
    porder = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Info": 4, "P?": 5}

    def key(r):
        m = re.search(r"\d+", r["id"])
        return (porder.get(r["prio"], 9), int(m.group(0)) if m else 0)

    o = ["# Backlog progress", "",
         "Generated by `scripts/backlog_progress.py` from `docs/ACTIONABLES_BACKLOG.md` (read-only; do not edit by hand).", "",
         f"Total rows: {len(rows)} | closed: {len(rows) - len(openr)} | not closed: {len(openr)}", "",
         "## Counts by status", "", "| Status | Count |", "|---|---|"]
    o += [f"| {s} | {n} |" for s, n in sc.most_common()]
    o += ["", "## Counts by priority (all rows / not closed)", "", "| Priority | All | Not closed |", "|---|---|---|"]
    oc = collections.Counter(r["prio"] for r in openr)
    o += [f"| {p} | {pc[p]} | {oc[p]} |" for p in sorted(pc, key=lambda p: porder.get(p, 9))]
    groups = collections.OrderedDict((g, []) for g in
                                     ["needs-owner", "waiting-on-workflow/deploy", "ready-to-build", "research-queue"])
    for r in sorted(openr, key=key):
        groups[group_of(r)].append(r)
    for g, rs in groups.items():
        o += ["", f"## {g} ({len(rs)})", "", "| ID | Pri | Status | Title | Owed keywords |", "|---|---|---|---|---|"]
        for r in rs:
            t = short_title(r["item"]).replace("|", "/")
            o.append(f"| {r['id']} | {r['prio']} | {r['ns']} | {t} | {', '.join(owed_keywords(r['text']))} |")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(o) + "\n")
    return rows, groups


if __name__ == "__main__":
    dest = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else OUT
    rs, g = main(dest)
    print(f"{len(rs)} rows; " + ", ".join(f"{k}={len(v)}" for k, v in g.items()))
