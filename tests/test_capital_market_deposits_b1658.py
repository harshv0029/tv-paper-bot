"""B-1658: View 4 capital card shows positions at market value and gain/loss against net deposits."""
import hashlib
import json
import pathlib
import re

import main


def test_market_value_and_net_deposits(monkeypatch):
    monkeypatch.setitem(main._real_capital_cache, "value", 1000.0)
    monkeypatch.setattr(main, "_real_fund_flows", lambda: {"deposits_inr": 3000.0, "payouts_inr": 500.0,
                                                           "net_deposited_inr": 2500.0, "last_date": "2026-11-17"})
    pos = [{"entry_price": 100, "qty": 5, "current_price": 110, "category": "swing"},
           {"entry_price": 200, "qty": 2, "current_price": 190, "category": "swing_short"},
           {"entry_price": 50, "qty": 2, "category": "buy"}]
    c = main._capital_split(pos)
    assert c["total_inr"] == 1000 + 500 + 400 + 100
    assert c["market_value_inr"] == 550 + (400 + 20) + 100  # short gains when price falls; unpriced at entry
    assert c["unpriced_positions"] == 1
    assert c["total_market_inr"] == 1000 + 1070
    assert c["gain_vs_deposits_inr"] == 2070 - 2500
    assert c["gain_vs_deposits_pct"] == round(100 * -430 / 2500, 2)


def test_fund_flows_file_sums_and_has_no_account_ids():
    raw = pathlib.Path(__file__).resolve().parents[1].joinpath("docs/real_fund_flows.json").read_text()
    rows = json.loads(raw)["flows"]
    assert all(r["type"] in ("deposit", "payout") and float(r["amount_inr"]) > 0 for r in rows)
    f = main._real_fund_flows()
    assert f["net_deposited_inr"] == round(f["deposits_inr"] - f["payouts_inr"], 2)
    # never the real 5-char account code (checked by hash prefix only, the code itself is never written)
    assert not any(hashlib.md5(t.encode()).hexdigest().startswith("3f413e") for t in re.findall(r"[A-Z]{5}", raw))


def test_view4_renders_market_total():
    html = pathlib.Path(__file__).resolve().parents[1].joinpath("static/trade-view4.html").read_text()
    assert "cp.total_market_inr" in html and "cp.net_deposited_inr" in html


def test_gain_unverified_flags_missing_deposit_b1673(monkeypatch):
    # 2026-11-23: a Rs 5,000 deposit missing from the flows file showed as Rs 5,443 gain on Rs 27,000 net deposited.
    monkeypatch.setitem(main._real_capital_cache, "value", 32443.56)
    flows = {"deposits_inr": 34849.12, "payouts_inr": 12849.12, "net_deposited_inr": 27000.0, "last_date": "2026-11-17"}
    monkeypatch.setattr(main, "_real_fund_flows", lambda: flows)
    c = main._capital_split([])
    assert c["gain_vs_deposits_inr"] == 5443.56 and c["gain_unverified"] is True
    flows.update(net_deposited_inr=32000.0, last_date="2026-11-23")
    c = main._capital_split([])
    assert c["gain_vs_deposits_inr"] == 443.56 and c["gain_unverified"] is False
    assert "check deposits" in pathlib.Path("static/trade-view4.html").read_text()
