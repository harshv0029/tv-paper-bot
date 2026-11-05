"""B-1471: sector rotation momentum n200 L=5 / L=3 cells wired on the pooled bar (one cell per entry signal)."""
import main
import strategy_registry as sr


def test_cells_registered_pooled_and_ordered():
    by = {d.name: d for d in sr.REGISTRY}
    cells = list(main.SECTOR_ROT_CELLS)
    assert cells[-2:] == [main.SECTOR_ROT_L5_TAG, main.SECTOR_ROT_L3_TAG]
    for t, L in ((main.SECTOR_ROT_L5_TAG, 5), (main.SECTOR_ROT_L3_TAG, 3)):
        assert main.SECTOR_ROT_CELL_L[t] == L and f"_l{L}_n5__" in t and "n200" in t
        m = by[t].metrics
        assert m.pfnet > 1.0 and m.n_trades >= 30
        assert main._STRATEGY_TAG_TO_REGISTRY_NAME[t] == t
        assert main._strategy_hold_spec(t) == (20, "1d")


def test_cell_passes_its_own_lookback(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "sector_rotation_picks", lambda dfs, L=None, N=None: seen.append((L, N)) or [])
    monkeypatch.setattr(main, "_scan_visit", lambda syms: syms)
    main._run_sector_rotation_entries(None, {}, 1e5, "2026-11-05")
    assert seen == [(1, 3), (1, 5), (5, 5), (3, 5)]
