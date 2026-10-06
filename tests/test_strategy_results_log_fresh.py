import importlib.util
import pathlib

R = pathlib.Path(__file__).resolve().parent.parent


def test_strategy_results_log_is_current():
    spec = importlib.util.spec_from_file_location("g", R / "scripts" / "gen_strategy_results_log.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    assert (R / "docs" / "STRATEGY_RESULTS_LOG.md").read_text() == g.render(), \
        "stale: run python3 scripts/gen_strategy_results_log.py"
