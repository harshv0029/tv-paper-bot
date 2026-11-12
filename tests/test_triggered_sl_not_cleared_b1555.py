"""B-1555 (COCHINSHIP 2026-11-11 09:19 IST): a swing row's own SELL stop had triggered and was still working at Kotak
(no longer prcTp SL), so the align step cleared it as "no live SL" and the backfill sent a second SELL that Kotak's
RMS rejected (T1 Used 2 / Available 1) 30 s before the first one filled. A working stop must keep the row's id."""
from contextlib import closing

import pytest

import main


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    main.init_db()
    for n in ("_sync_real_positions_external", "_sync_real_positions_swing_external", "_sync_signal_state_swing_external"):
        monkeypatch.setattr(main, n, lambda c: None)
    with closing(main.get_db()) as c:
        c.execute("INSERT INTO real_positions_swing (symbol, kotak_trading_symbol, qty, entry_price, opened_at, day, "
                  "stop_loss, sl_order_id, sl_trigger_price, strategy) VALUES ('COCHINSHIP.NS','COCHINSHIP-EQ',1,"
                  "1204.3,0,'2026-11-10',1203.7,'261111000013683',1203.7,'order_block_delta')")
        c.commit()
    return tmp_path


def _row(st, prc="L", oid="261111000013683"):
    return {"nOrdNo": oid, "trdSym": "COCHINSHIP-EQ", "trnsTp": "S", "prcTp": prc, "ordSt": st, "trgPrc": "1203.70"}


def _sl_id():
    with closing(main.get_db()) as c:
        return c.execute("SELECT sl_order_id FROM real_positions_swing").fetchone()[0]


def test_triggered_and_working_stop_keeps_the_row_id(db):
    with closing(main.get_db()) as c:
        out = main._align_swing_sl_rows_to_kotak(c, [_row("open")])
    assert out == [] and _sl_id() == "261111000013683"


@pytest.mark.parametrize("st", ["complete", "rejected", "cancelled"])
def test_final_states_still_clear_the_row(db, st):
    with closing(main.get_db()) as c:
        out = main._align_swing_sl_rows_to_kotak(c, [_row(st)])
    assert out and out[0]["action"] == "cleared_no_live_sl_at_kotak" and _sl_id() is None


def test_some_other_open_sell_does_not_count_as_this_rows_stop(db):
    with closing(main.get_db()) as c:
        out = main._align_swing_sl_rows_to_kotak(c, [_row("open", oid="OTHER_TARGET")])
    assert out and out[0]["action"] == "cleared_no_live_sl_at_kotak"
