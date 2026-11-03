"""B-1452: a chan_gap entry that mirrors to Kotak must not have its paper qty floored to 0 by paper-only notional."""
import main


class _Conn:
    pass


def test_real_mirrored_ignores_paper_only_notional(monkeypatch):
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 9_500.0)
    assert main._chan_gap_paper_usable(_Conn(), 10_000.0, real_mirrored=True) == 10_000.0 / main.CAPITAL_TRANCHES


def test_paper_only_keeps_shared_capital_cap(monkeypatch):
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 9_500.0)
    assert main._chan_gap_paper_usable(_Conn(), 10_000.0, real_mirrored=False) == 500.0
    monkeypatch.setattr(main, "deployed_notional", lambda conn: 20_000.0)
    assert main._chan_gap_paper_usable(_Conn(), 10_000.0, real_mirrored=False) == 0.0


def test_both_chan_gap_sites_use_helper():
    import inspect
    assert "_chan_gap_paper_usable" in inspect.getsource(main._chan_gap_long_try_entry)
    src = inspect.getsource(main)
    i = src.index("def _chan_gap_short_candidates")
    assert "_chan_gap_paper_usable(conn, capital, real_mirrored=True)" in src[i:i + 8000]
