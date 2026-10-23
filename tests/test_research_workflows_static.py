"""Static audit (B-606/B-740/B-742/B-778/B-784): each research workflow invokes an existing script with flags that
script accepts, uploads artifacts, keeps the matrix <= 40 jobs, and the scripts take the universe from
main._load_nse_universe_from_file() (never main.NSE_FULL_UNIVERSE)."""
import os
import re

R = os.path.join(os.path.dirname(__file__), "..")
WF = ("elder-stop-offset-research", "elder-invalidation-research", "elder-pyramid-research", "gap-fade-confirm",
      "oneil-replay", "oneil-research", "oneil-ext-research", "chan-ext-research")
SCRIPTS = ("elder_stop_offset_research", "elder_invalidation_research", "elder_pyramid_research", "elder_lab_driver",
           "gap_fade_confirm", "oneil_replay", "oneil_research", "oneil_ext_research", "chan_ext_research",
           "chan_research")


def _read(path):
    return open(os.path.join(R, path)).read()


def _jobs(txt):
    total = 0
    for job in re.split(r"\n  (?=[a-z]+:\n    (?:runs-on|needs))", txt)[1:]:
        dims = re.findall(r"^\s{8}[a-z]+: \[(.*?)\]", job, re.M)
        n = 1
        for d in dims:
            n *= len([x for x in d.split(",") if x.strip()])
        total += n
    return total


def test_workflows_reference_real_scripts_flags_and_artifacts():
    for wf in WF:
        txt = _read(f".github/workflows/{wf}.yml")
        assert "workflow_dispatch" in txt and "upload-artifact" in txt, wf
        for sc in re.findall(r"scripts/([a-z_0-9]+\.py)", txt):
            src = _read(f"scripts/{sc}")
            for flag in re.findall(r"\s(--[a-z]+)\s", txt.split(sc, 1)[1].split("\n      - ")[0] + " "):
                assert flag in src or flag in _read("scripts/elder_lab_driver.py") or flag == "--merge", (wf, flag)
        assert _jobs(txt) <= 40, wf


def test_universe_source_never_nse_full_universe():
    for sc in SCRIPTS:
        src = _read(f"scripts/{sc}.py")
        for ln in _read(f"scripts/{sc}.py").splitlines():
            code = ln.split("#")[0]
            assert "NSE_FULL_UNIVERSE" not in code or "never" in code, (sc, ln)
    for sc in ("elder_lab_driver", "gap_fade_confirm", "oneil_replay", "oneil_research", "oneil_ext_research",
               "chan_ext_research", "chan_research"):
        assert "_load_nse_universe_from_file()" in _read(f"scripts/{sc}.py"), sc


# B-420: legacy replays behind registry tags with no avg hold must emit a market-bar hold + machine-readable summary.
B420_WF = ("universal-score-validation-replay", "universal-score-entry-floor-validation-replay",
           "range-short-validation-replay", "rsi-overbought-short-research", "trend-short-validation-replay",
           "gap-up-fade-short-validation-replay")


def test_b420_workflows_emit_avg_held_bars_summary():
    import ast
    import yaml
    src = _read("scripts/research_hold_summary.py")
    for col in ("n", "win_pct", "pfnet", "pfgross", "avg_held_bars", "avg_held_hrs", "exit_reasons", "universe", "run_id"):
        assert f'"{col}"' in src, col
    for wf in B420_WF:
        txt = _read(f".github/workflows/{wf}.yml")
        doc = yaml.safe_load(txt)
        assert "held_bars" in txt and "_hs.write_summary(" in txt and "b420-hold-summary" in txt, wf
        assert "b420_out/" in txt and "upload-artifact" in txt, wf
        for job in doc["jobs"].values():
            for step in job["steps"]:
                body = step.get("run", "")
                if "PYEOF" in body:
                    code = body.split("<<'PYEOF'\n", 1)[1].rsplit("PYEOF", 1)[0]
                    ast.parse(code)
                    if "_hs." in code:
                        assert "research_hold_summary" in code, wf
                        # a job importing the helper needs the repo checked out
                        assert any("actions/checkout" in s.get("uses", "") for s in job["steps"]), wf
        assert _jobs(txt) <= 40, wf
