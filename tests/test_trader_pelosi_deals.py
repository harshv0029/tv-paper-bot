"""Offline tests for .claude/skills/trader-pelosi/deals.py historical (week / date-range) deals."""
import argparse
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "trader-pelosi", "deals.py")
_spec = importlib.util.spec_from_file_location("trader_pelosi_deals", _PATH)
deals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deals)

HIST_BULK = {"data": [
    {"BD_DT_DATE": "20-OCT-2026", "BD_SYMBOL": "reliance", "BD_SCRIP_NAME": "Reliance Industries Ltd",
     "BD_CLIENT_NAME": "ABC FUND", "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 1000000, "BD_TP_WATP": 2500.5,
     "BD_REMARKS": "-"},
    {"date": "22-Oct-2026", "symbol": "TCS", "name": "TCS Ltd", "clientName": "XYZ LLP", "buySell": "SELL",
     "qty": "2,00,000", "watp": "4000"},
]}
HIST_BLOCK = {"data": [
    {"BD_DT_DATE": "22-OCT-2026", "BD_SYMBOL": "INFY", "BD_SCRIP_NAME": "Infosys", "BD_CLIENT_NAME": "PQR",
     "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 100000, "BD_TP_WATP": 1500},
]}


def test_parse_hist_deals_fields_and_alt_keys():
    rows = deals.parse_hist_deals(HIST_BULK, "bulk")
    assert len(rows) == 2
    a, b = rows
    assert (a["kind"], a["symbol"], a["side"], a["who"], a["date"]) == ("bulk", "RELIANCE", "buy", "ABC FUND",
                                                                         "20-OCT-2026")
    assert a["company"] == "Reliance Industries Ltd" and a["value_cr"] == round(1000000 * 2500.5 / 1e7, 2)
    assert (b["symbol"], b["side"], b["qty"], b["price"]) == ("TCS", "sell", 200000.0, 4000.0)
    assert deals.parse_hist_deals({}, "bulk") == [] and deals.parse_hist_deals({"data": None}, "block") == []


def test_hist_id_matches_snapshot_id_for_same_deal():
    snap = {"BULK_DEALS_DATA": [{"date": "22-Oct-2026", "symbol": "TCS", "name": "TCS Ltd", "clientName": "XYZ LLP",
                                 "buySell": "SELL", "qty": "2,00,000", "watp": "4000"}]}
    assert deals.parse_large_deals(snap)[0]["id"] == deals.parse_hist_deals(HIST_BULK, "bulk")[1]["id"]


def _ns(**kw):
    base = dict(week=False, frm=None, to=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_week_and_range_date_math():
    fri = dt.date(2026, 10, 23)
    assert deals.date_range(_ns(week=True), fri) == (dt.date(2026, 10, 19), fri)
    mon = dt.date(2026, 10, 19)
    assert deals.date_range(_ns(week=True), mon) == (mon, mon)
    assert deals.date_range(_ns(frm="2026-10-01", to="2026-10-10"), fri) == (dt.date(2026, 10, 1),
                                                                            dt.date(2026, 10, 10))
    assert deals.date_range(_ns(), fri) is None


def test_offline_week_end_to_end(tmp_path):
    (tmp_path / "hist_bulk.json").write_text(json.dumps(HIST_BULK))
    (tmp_path / "hist_block.json").write_text(json.dumps(HIST_BLOCK))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = deals.main(["check", "--week", "--offline", str(tmp_path), "--today", "2026-10-23", "--dry-run",
                         "--json", "--no-insider", "--state", str(tmp_path / "state.json"),
                         "--portfolio", str(tmp_path / "nope.json"), "--watchlist", str(tmp_path / "nope.json")])
    out = json.loads(buf.getvalue())
    assert rc == 0 and out["notes"] == [] and out["range"] == "2026-10-19..2026-10-23"
    assert [r["symbol"] for r in out["new"]] == ["TCS", "INFY", "RELIANCE"]  # date desc, then value desc
    assert {r["kind"] for r in out["new"]} == {"bulk", "block"}
    assert not (tmp_path / "state.json").exists()


def test_offline_range_missing_file_is_note_not_crash(tmp_path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = deals.main(["check", "--from", "2026-10-01", "--to", "2026-10-05", "--offline", str(tmp_path),
                         "--dry-run", "--json", "--no-insider", "--today", "2026-10-23"])
    out = json.loads(buf.getvalue())
    assert rc == 1 and out["new"] == [] and len(out["notes"]) == 2
