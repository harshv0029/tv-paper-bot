"""Update backlog rows in place: python scripts/backlog_close.py decisions.json
decisions.json = {"B-150": ["CLOSED-AS-EXPLAINED", "reason"], ...}. Replaces the row's status cell and
appends the dated decision to the description cell. Never deletes a row."""
import json, re, sys
STAT = re.compile(r"^(DONE|MERGED|CLOSED|OPEN|TODO|PENDING|IN[- ]|NOTE|FIX|CODE|BUILT|PARKED|BLOCKED|WAIT|RESEARCH|MONITOR|RULE|\(a\))")
path = "docs/ACTIONABLES_BACKLOG.md"
dec = json.load(open(sys.argv[1]))
out, hit = [], set()
for line in open(path):
    m = re.match(r"\| *(B-\d+) *\|", line)
    if m and m.group(1) in dec:
        bid = m.group(1)
        cells = line.rstrip("\n").split("|")
        inner = cells[1:-1]
        si = next((i for i in range(1, min(4, len(inner))) if STAT.match(inner[i].strip())), None)
        if si is None:
            si = 2
        di = max((i for i in range(1, min(4, len(inner)))), key=lambda i: len(inner[i]) if i != si else -1)
        status, note = dec[bid]
        inner[si] = f" {status} "
        inner[di] = inner[di].rstrip() + f" **Decision 2026-10-10 IST:** {note} "
        line = "|" + "|".join(inner) + "|\n"
        hit.add(bid)
    out.append(line)
open(path, "w").write("".join(out))
print("updated", len(hit), "missing", sorted(set(dec) - hit))
