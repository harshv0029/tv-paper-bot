"""B-1387: the real swing buy is sized from Kotak's fresh Net with the risk formula, not capped by the paper qty
(which counts paper-only positions against real capital). NHPC 2026-10-27 IST numbers."""
import main


def _setup(monkeypatch, net, cluster=False):
    monkeypatch.setattr(main, "_refresh_real_capital_cache", lambda: None)
    monkeypatch.setattr(main, "get_scheduler_capital_inr", lambda: net)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: cluster)


def test_nhpc_numbers_give_nine(monkeypatch):
    _setup(monkeypatch, 8849.87)
    # usable 4,424.94; 1% risk 44.25; stop distance 4.45 -> 9.94 -> 9 (capital cap 4424.94/72.74 = 60)
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 72.74, 68.29) == 9


def test_cluster_halves(monkeypatch):
    _setup(monkeypatch, 8849.87, cluster=True)
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 72.74, 68.29) == 4


def test_capital_cap_binds(monkeypatch):
    _setup(monkeypatch, 1000.0)
    # usable 500 -> 500/400 = 1 share even though risk allows more
    assert main._real_swing_qty_by_risk(None, "X.NS", 400.0, 399.0) == 1


def test_short_uses_stop_above(monkeypatch):
    _setup(monkeypatch, 8849.87)
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 68.29, 72.74, short=True) == 9
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 72.74, 68.29, short=True) == 0


def test_bad_or_missing_stop_is_zero(monkeypatch):
    _setup(monkeypatch, 8849.87)
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 72.74, None) == 0
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 72.74, 90.0) == 0
    assert main._real_swing_qty_by_risk(None, "NHPC.NS", 72.74, "x") == 0


def test_entry_paths_do_not_cap_at_paper_qty():
    import inspect
    for fn in (main._maybe_place_real_swing_entry, main._maybe_place_real_swing_short_entry):
        src = inspect.getsource(fn)
        assert "_real_swing_qty_by_risk(" in src
        assert "min(paper_qty" not in src
