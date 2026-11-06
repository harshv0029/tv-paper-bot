"""B-1507: a fired swing signal is never dropped by PAPER sizing; the real order sizes itself from Kotak Net."""
import sqlite3
import main


def test_paper_size_floor_is_one_share_when_capital_is_starved(monkeypatch):
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 3976.0)   # paper-only rows (live 2026-11-06 IST)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: False)
    # Net Rs5,904, 1% risk on Rs1,929 usable = Rs19 vs a Rs45 stop distance -> formula says 0 shares
    assert main._swing_position_size(None, 5904.53, 1.0, 300.0, 255.0) == 1


def test_paper_size_unchanged_when_formula_gives_shares(monkeypatch):
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 0.0)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: False)
    assert main._swing_position_size(None, 100000.0, 1.0, 100.0, 95.0) == 100   # 500 risk / 5


def test_paper_size_still_zero_without_capital_or_valid_stop(monkeypatch):
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 0.0)
    monkeypatch.setattr(main, "_swing_stopout_cluster", lambda conn: False)
    assert main._swing_position_size(None, 0.0, 1.0, 100.0, 95.0) == 0
    assert main._swing_position_size(None, 5000.0, 1.0, 100.0, 105.0) == 0   # stop above entry
