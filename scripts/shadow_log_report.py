"""B-547 (Mark Douglas, Trading in the Zone): skipped-vs-taken signal report from signal_shadow_log.

Rows come from the shadow log (strategy_tag, symbol, direction, taken, reason, hard_gate, day). Optional
`outcomes` maps (strategy_tag, symbol, day) -> net return fraction (after 0.8% costs) from a replay or the
Kotak trade book. Report per (strategy, direction): taken vs skipped counts, skips split into hard-gate
(allowed) and discretionary (the "execute every signal" violation), and PFnet of each group when
outcomes exist. Offline analysis only; never touches trading."""
import sqlite3
import sys


def pfnet(rets):
    if not rets:
        return None
    g = sum(r for r in rets if r > 0)
    l = -sum(r for r in rets if r < 0)
    return g / l if l > 0 else float("inf")


def build_report(rows, outcomes=None):
    outcomes = outcomes or {}
    agg = {}
    for r in rows:
        k = (r["strategy_tag"], r["direction"])
        a = agg.setdefault(k, {"taken": [], "hard_skip": [], "disc_skip": [], "reasons": {}})
        grp = "taken" if r["taken"] else ("hard_skip" if r["hard_gate"] else "disc_skip")
        a[grp].append(outcomes.get((r["strategy_tag"], r["symbol"], r["day"])))
        a["reasons"][r["reason"]] = a["reasons"].get(r["reason"], 0) + 1
    out = []
    for (tag, d), a in sorted(agg.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        row = {"strategy_tag": tag, "direction": d, "reasons": a["reasons"]}
        for g in ("taken", "hard_skip", "disc_skip"):
            known = [x for x in a[g] if x is not None]
            row[g] = {"n": len(a[g]), "n_with_outcome": len(known), "pfnet": pfnet(known)}
        row["discretionary_skips"] = row["disc_skip"]["n"]
        out.append(row)
    return out


def load_rows(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute(
        "SELECT strategy_tag, symbol, direction, taken, reason, hard_gate, day FROM signal_shadow_log")]


if __name__ == "__main__":
    for r in build_report(load_rows(sys.argv[1])):
        print(r)
