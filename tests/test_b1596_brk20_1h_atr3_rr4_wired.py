"""B-1596: brk20 1h long atr3_rr4 (main.py replay 1.393, re-run 43696686802 1.379) is wired after atr4_rr4; the re-run rows are
their own `_b1596` tags; the be1 twin and failing cells are not wired."""
import pandas as pd

import main
import strategy_registry as sr

T = "brk20_min_rr__main_replay__long__1h__atr3_rr4__v1"


def test_cell_wired_after_atr4_with_own_params():
    cells = list(main.BRK20_1H_LONG_CELLS)
    assert cells[0] == main.BRK20_1H_LONG_TAG and cells[1] == T
    assert main.BRK20_1H_LONG_CELLS[T][:2] == (3.0, 4.0)
    assert main._STRATEGY_TAG_TO_REGISTRY_NAME[T] == T and T not in main.REPLAY_OWED_TAGS
    assert "brk20_min_rr__main_replay__long__1h__atr3_be1_rr4__v1" not in main.BRK20_1H_LONG_CELLS
    assert "brk20_min_rr__main_replay__long__1h__atr3_rr3__v1" not in main.BRK20_1H_LONG_CELLS


def test_entry_uses_cell_atr(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "brk20_min_rr_entry_signal",
                        lambda df, d, atr_mult, min_rr: seen.append((atr_mult, min_rr)) or
                        {"entry_price": 100.0, "stop_loss": 100.0 - 2 * atr_mult, "atr_at_entry": 2.0})
    sig = main.brk20_1h_long_entry_signal(pd.DataFrame({"Close": [1.0]}), T)
    assert seen == [(3.0, 4.0)] and sig["stop_loss"] == 94.0


def test_rerun_rows_registered_distinct():
    rows = [s for s in sr.REGISTRY if s.name.startswith("brk20_min_rr__main_replay_b1596__long__1h__")]
    assert len(rows) == 12
    assert {s.name for s in rows if s.metrics.pfnet > 1.0} == {
        "brk20_min_rr__main_replay_b1596__long__1h__atr3_rr4__v1", "brk20_min_rr__main_replay_b1596__long__1h__atr3_be1_rr4__v1"}
