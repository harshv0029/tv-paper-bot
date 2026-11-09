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


# 2026-11-09 follow-up: the 2026-11-06 rule "paper sizing never drops a fired signal" - a real-mirrored chan entry
# whose risk formula rounds to 0 shares (or sits under the Rs100 paper minimum) still writes a 1-share paper row,
# because that row is the only gateway to the real order (which sizes itself from Kotak Net).
def test_real_mirrored_paper_qty_floors_at_one_share():
    assert main._chan_gap_paper_qty(0.4, 383.0, 9_621.0, True) == 1.0
    assert main._chan_gap_paper_qty(0.0, 50.0, 9_621.0, True) == 1.0  # under Rs100 notional: kept when mirrored
    assert main._chan_gap_paper_qty(2.7, 383.0, 9_621.0, True) == 2.0  # never raises a qty that already sizes
    assert main._chan_gap_paper_qty(0.4, 383.0, 0.0, True) == 0.0  # no known capital: nothing to size against


def test_paper_only_keeps_zero_and_min_notional():
    assert main._chan_gap_paper_qty(0.4, 383.0, 9_621.0, False) == 0.0
    assert main._chan_gap_paper_qty(1.9, 50.0, 9_621.0, False) == 0.0  # Rs50 < Rs100 paper minimum
    assert main._chan_gap_paper_qty(3.2, 50.0, 9_621.0, False) == 3.0


def test_every_chan_entry_site_uses_the_floor():
    import inspect
    for fn in (main._chan_long_try_entry, main._chan_gap_long_try_entry, main._chan_short_try_entry):
        src = inspect.getsource(fn)
        assert "_chan_gap_paper_qty(" in src and "_chan_gap_paper_usable(" in src, fn.__name__
        assert "qty * unit_inr < 100.0" not in src, fn.__name__
    src = inspect.getsource(main)
    i = src.index("def _chan_gap_short_candidates")
    assert "_chan_gap_paper_qty(" in src[i:i + 9000]
