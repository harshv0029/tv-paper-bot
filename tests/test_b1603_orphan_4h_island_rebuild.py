"""B-1603: a real 4h island long holding whose signal_state_swing row was lost is rebuilt by the orphan 1h-state pass
with entry_day = the 4h signal bar (the last session-4h bar completed at the real fill), the key
_island_long_4h_exit replays from. No order is placed by the rebuild."""
import main
from tests.test_swing_paper_row_orphans import SYM, _fresh_db, _ist_epoch, _real_row, _rebuild

TAG4 = main.ISLAND_TFS_LONG_4H_TAGS[0]


def _state(opened):
    _fresh_db()
    with main.closing(main.get_db()) as c:
        _real_row(c, strategy=TAG4, opened_at=_ist_epoch(opened))
        out, _sync, ex, sl = _rebuild(c)
        st = c.execute("SELECT * FROM signal_state_swing WHERE symbol = ?", (SYM,)).fetchone()
    assert not ex.called and not sl.called
    return out, st


def test_4h_orphan_entry_day_is_bar0_signal_bar():
    out, st = _state("2026-10-16 13:20")
    assert out[0]["derived"] is True and st["strategy"] == TAG4
    assert st["entry_day"] == "2026-10-16 09:15"


def test_4h_orphan_late_fill_still_bar0_not_forming_bar1():
    _out, st = _state("2026-10-16 14:50")
    assert st["entry_day"] == "2026-10-16 09:15"


def test_swing_4h_entry_bar_none_without_bars():
    assert main._swing_4h_entry_bar(None, 1.0) is None
