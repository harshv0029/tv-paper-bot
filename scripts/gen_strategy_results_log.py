"""Regenerate docs/STRATEGY_RESULTS_LOG.md from strategy_registry.REGISTRY (the single
source of truth). One row per registered strategy tag: name, family/variant/dir/tf/params
parsed from the naming grammar (legacy tags shown as-is), PFnet, win %, n, held hrs,
universe, run ref. Usage: python3 scripts/gen_strategy_results_log.py [--check]"""
import pathlib
import sys

sys.path.insert(0, ".")
import strategy_registry as sr  # noqa: E402

OUT = pathlib.Path("docs/STRATEGY_RESULTS_LOG.md")


def _cell(x):
    return str(x).replace("|", "/").replace("\n", " ")


def render():
    head = ("# Strategy results log (PFnet, win %, variant details)\n\n"
            "AUTO-GENERATED from `strategy_registry.REGISTRY` by "
            "`scripts/gen_strategy_results_log.py` - do not hand-edit; edit the registry "
            "and regenerate (a test fails if this file is stale). Every tag is its own row, "
            "never pooled. Naming grammar: `<family>__<variant>__<dir>__<tf>__<params>__v<N>`. "
            f"Viability floor PFnet >= {sr.PFNET_LIVE_FLOOR}. Blank metrics = not measured yet "
            "(never guessed).\n\n"
            "| Strategy tag | Family | Variant | Dir | TF | Params | Categories | PFnet | Win % | "
            "Trades | Avg held hrs | Viable | Universe | Run ref |\n|" + "---|" * 14 + "\n")
    rows = []
    for s in sorted(sr.REGISTRY, key=lambda d: d.name):
        p = s.name.split("__")
        g = len(p) >= 6
        m = s.metrics
        v = s.is_viable()
        rows.append("| " + " | ".join(_cell(x) for x in (
            s.name, p[0] if g else "(legacy)", p[1] if g else "", p[2] if g else "",
            p[3] if g else s.timeframe, p[4] if g else "",
            ",".join(getattr(c, "value", str(c)) for c in s.categories),
            f"{m.pfnet:.3f}" if m and m.pfnet is not None else "",
            f"{m.win_rate_pct:.1f}" if m and m.win_rate_pct is not None else "",
            m.n_trades if m else "", m.avg_held_hrs if m and m.avg_held_hrs is not None else "",
            "n/a" if v is None else ("yes" if v else "no"),
            m.universe if m else "", m.run_ref if m else "")) + " |")
    return head + "\n".join(rows) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == text else 1)
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(sr.REGISTRY)} strategies)")
