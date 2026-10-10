"""2026-10-10: SI=F booked +Rs 65 crore paper P&L when a Kotak MCX tick
(Rs 225,820/kg) was used as the exit price against a COMEX $61/oz entry."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "main.py"


def test_both_paper_paths_reject_wild_live_ticks():
    src = SRC.read_text()
    assert src.count("not (0.5 < live_price / last_close < 2.0)") == 1
    assert src.count("not (0.5 < float(live_price) / last_close < 2.0)") == 1
