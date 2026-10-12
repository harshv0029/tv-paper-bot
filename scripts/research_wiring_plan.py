#!/usr/bin/env python3
"""B-779(b): ranked plan to wire research-only viable registry strategies. Offline, reads strategy_registry only.

Viability is DERIVED at read time (is_viable()), never stored. A candidate must be viable, not LIVE, and not already
a value in main._STRATEGY_TAG_TO_REGISTRY_NAME. Rank = PFnet per trading-day held (faster-turnover rule), gated by
n >= MIN_N and hold <= 30 trading days. Excluded with a reason (listed, never dropped silently): avg1 (never-average-
down negative control), atrnone (backtest had no stop; wire only with an always-on stop), hold unknown.
Every wiring still needs a main.py-calling replay (B-776) before real money.
Usage: python3 scripts/research_wiring_plan.py [out.md]   (default docs/WIRING_PLAN_RESEARCH_VIABLES.md)
"""
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
MIN_N = 300
MAX_HOLD_DAYS = 30.0
HRS_PER_DAY = 6.25


def wired_registry_names(main_text):
    m = re.search(r"^_STRATEGY_TAG_TO_REGISTRY_NAME\s*=\s*\{(.*?)^\}", main_text, re.S | re.M)
    return set(re.findall(r':\s*"([^"]+)"', m.group(1))) if m else set()


def classify(s):
    mt = s.metrics
    if mt is None:
        return "excluded", "no metrics"
    if "avg1" in s.name:
        return "excluded", "avg1 negative control (never average down)"
    if "atrnone" in s.name:
        return "excluded", "backtest had no stop; wire only with an always-on protective stop"
    if mt.avg_held_hrs is None:
        return "excluded", "hold unknown; cannot rank on turnover"
    days = mt.avg_held_hrs / HRS_PER_DAY
    if days > MAX_HOLD_DAYS:
        return "excluded", "hold above 30 trading days"
    if mt.n_trades < MIN_N:
        return "excluded", f"n below {MIN_N}"
    return "candidate", ""


def build(registry, wired):
    rows, ex = [], []
    for s in registry:
        if s.is_viable() is not True or str(s.status).endswith("LIVE") or s.name in wired:
            continue
        b, why = classify(s)
        if b == "excluded":
            ex.append((s.name, why))
            continue
        mt = s.metrics
        days = max(mt.avg_held_hrs / HRS_PER_DAY, 0.1)
        rows.append((mt.pfnet / days, s.name, mt.pfnet, mt.win_rate_pct, mt.n_trades, days,
                     [c.value for c in s.categories]))
    rows.sort(reverse=True)
    return rows, ex


def render(rows, ex, top=40):
    out = ["# Wiring plan: research-only viable strategies (B-779b)", "",
           "Derived from `strategy_registry.REGISTRY`; regenerate with `python3 scripts/research_wiring_plan.py`.",
           f"Gate: viable (PFnet >= floor), n >= {MIN_N}, hold <= {MAX_HOLD_DAYS:.0f} trading days. Rank = PFnet per day held.",
           "Each needs a main.py-calling replay (B-776) and a live entry path that always attaches a stop before any real order.",
           "", f"Candidates: {len(rows)}; excluded (reason kept): {len(ex)}", "",
           "| # | tag | PFnet | win % | n | hold d | PFnet/day | categories |", "|---|---|---|---|---|---|---|---|"]
    for i, (sc, n, p, w, cnt, d, cats) in enumerate(rows[:top], 1):
        out.append(f"| {i} | `{n}` | {p:.3f} | {w if w is not None else '-'} | {cnt} | {d:.1f} | {sc:.2f} | {','.join(cats)} |")
    out += ["", "## Excluded (reason counts)", ""]
    for k, v in Counter(r for _, r in ex).most_common():
        out.append(f"- {k}: {v}")
    ot = oneil_replay_tags(rows)
    out += ["", "## O'Neil tags for oneil-replay.yml `tags` input (B-776; avg1 cells excluded, short-hold h8/h12/h20 first)", "",
            "```", ",".join(ot), "```"]
    return "\n".join(out) + "\n"


def oneil_replay_tags(rows, limit=24):
    """Candidate O'Neil tags for the B-776 main-free replay: short holds (h8/h12/h20) first, then by PFnet/day."""
    on = [r for r in rows if r[1].startswith("oneil_")]
    short = [r for r in on if re.search(r"_h(8|12|20)(_|$)", r[1])]
    rest = [r for r in on if r not in short]
    return [r[1] for r in (short + rest)[:limit]]


def main():
    import strategy_registry as sr
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        wired = wired_registry_names(f.read())
    rows, ex = build(sr.REGISTRY, wired)
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "WIRING_PLAN_RESEARCH_VIABLES.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(rows, ex))
    print(f"{len(rows)} candidates, {len(ex)} excluded -> {path}")


if __name__ == "__main__":
    main()
