"""B-1563: View 4 Active positions table has a 'Close now (at live SL)' column = (Kotak SL - entry) x qty, shorts mirrored."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1].joinpath("static", "trade-view4.html").read_text()


def test_header_present_and_colspans_match():
    assert "Close now (at live SL)" in SRC
    assert 'colspan="15"' not in SRC.split('id="slBox"')[1].split("</table>")[0]
    assert SRC.count('colspan="16" class="dim">') >= 2


def test_formula_uses_kotak_sl_and_mirrors_shorts():
    assert "(isShort ? en - slp : slp - en) * q" in SRC
    assert "p.kotak_sl_trigger" in SRC
    assert 'p.category === "swing_short"' in SRC
    assert "no live Kotak SL" in SRC


def test_header_count_matches_row_cells():
    head = SRC.split('id="slBox"')[1].split("</thead>")[0]
    assert head.count("<th>") + head.count("<th ") == 16
