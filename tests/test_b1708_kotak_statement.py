"""B-1708: the Kotak P&L statement (docs/kotak_pnl_statement.json) is the realised-P&L ground truth on View 4; ledger
trades that exit after the statement's as_of day are added on top. Run: pytest tests/test_b1708_kotak_statement.py"""
import datetime as dt
import json
import os

import roc_kpis
import main

ROOT = os.path.join(os.path.dirname(__file__), "..")
ST = {"period_from": "2026-09-01", "as_of": "2026-11-24", "gross_pnl_inr": -268.63, "charges_inr": 175.04,
      "net_pnl_inr": -443.67, "qty": 1324}


def _t(exit_day, gross, charges, net):
    return {"exit_day": exit_day, "gross_pnl_inr": gross, "charges_inr": charges, "net_pnl_inr": net}


def test_statement_file_is_consistent_and_has_no_identifiers():
    d = json.load(open(os.path.join(ROOT, "docs", "kotak_pnl_statement.json")))
    assert round(d["gross_pnl_inr"] - d["charges_inr"], 2) == d["net_pnl_inr"] == -443.67
    assert d["as_of"] == "2026-11-24" and d["period_from"] == "2026-09-01"
    txt = json.dumps(d).lower()
    for bad in ("pan", "client", "demat", "ucc", "dp id", "dpid"):
        assert f'"{bad}' not in txt


def test_ledger_trades_after_as_of_are_added_on_top():
    closed = [_t("2026-11-23", 10, 1, 9), _t("2026-11-24", 5, 1, 4), _t("2026-11-25", 20, 2, 18)]
    b = roc_kpis.statement_block(ST, closed)
    assert b["ledger_after_trades"] == 1 and b["ledger_after_net_inr"] == 18
    assert b["realised_net_inr"] == round(-443.67 + 18, 2)
    assert b["realised_gross_inr"] == round(-268.63 + 20, 2) and b["realised_charges_inr"] == round(175.04 + 2, 2)
    assert b["dp_in_charges"] is False


def test_no_statement_returns_none():
    assert roc_kpis.statement_block(None, []) is None
    assert roc_kpis.statement_block({"as_of": "2026-11-24"}, []) is None


def test_payload_and_running_use_statement(monkeypatch):
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd)
    monkeypatch.setattr(main, "DB_PATH", p); monkeypatch.setattr(main, "UPSTASH_REDIS_REST_URL", ""); main.init_db()
    monkeypatch.setattr(main, "_roc_running_block", lambda out: {"open_lots": 0, "unrealised_gross_inr": -110.19,
                                                                  "unrealised_charges_inr": 31.82})
    out = main._roc_kpis_payload(today=dt.date(2026, 11, 24))
    ks = out["kotak_statement"]
    assert "closed_trades_all" not in out
    assert ks["net_pnl_inr"] == -443.67 and ks["realised_net_inr"] == -443.67
    assert out["running"]["statement_total_mtm_inr"] == round(-443.67 - 110.19, 2)
    assert out["running"]["statement_total_net_inr"] == round(-443.67 - 110.19 - 31.82, 2)


def test_card_shows_statement_lines():
    html = open(os.path.join(ROOT, "static", "trade-view4.html")).read()
    assert 'id="stmtLine"' in html and "kotak_statement" in html
    assert "Kotak P&amp;L statement" in html and "statement_total_mtm_inr" in html
