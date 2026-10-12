import importlib.util
import pathlib

R = pathlib.Path(__file__).resolve().parent.parent


def _gen():
    spec = importlib.util.spec_from_file_location("g", R / "scripts" / "gen_strategy_results_log.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


class M:
    def __init__(self, pfnet, win):
        self.pfnet, self.win_rate_pct = pfnet, win


def test_expectancy_value_and_blanks():
    g = _gen()
    assert g._expectancy(None) == ""
    assert g._expectancy(M(1.0, 50.0)) == "0.000"
    assert float(g._expectancy(M(2.0, 40.0))) > 0
    assert float(g._expectancy(M(0.5, 40.0))) < 0
    assert g._expectancy(M(1.2, 0.0)) == ""


def test_header_and_rows_have_matching_columns():
    g = _gen()
    text = g.render()
    assert "Expectancy (per avg loss)" in text
    lines = [ln for ln in text.splitlines() if ln.startswith("| ")]
    assert len({ln.count(" | ") for ln in lines[:50]}) == 1
    assert "Expectancy (per avg loss)" in g.render_gt1()
