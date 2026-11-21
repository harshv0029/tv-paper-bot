"""B-1598 (2026-11-21 IST): registers the 4h (1h resampled per NSE session, 730d, cost 0.8%) re-runs of three harnesses
whose own registry modules hardcode their 1d filenames:
  portfolio-overlay-research run 44928192937 (docs/backtest_data/pfovl_4h_run_44928192937.json; the script stamped
    __1d__ in tags for this run, so tags were re-stamped __4h__ and the printed name kept in printed_as; script fixed),
  tri-desc-main-replay run 44928195720 (docs/backtest_data/tridesc_main_replay_4h_run_44928195720.json; main.py functions),
  island-validation run 44928797980 (docs/backtest_data/island_oos_4h_run_44928797980.json; segis/segoos/nonovl cells).
Every tag pass or fail, research-only (entry_fn=None), nothing wired. Viability is derived from raw metrics at read time."""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")
_SRC = (
    ("pfovl_4h_run_44928192937.json", "portfolio-overlay-research.yml run 44928192937 (2026-11-21 IST, 4h, 730d, 2455 of 2763 with data)",
     "scripts/portfolio_overlay_research.py",
     "Portfolio overlay/sizing cell at 4h. Bar-count and calendar constants (month/year windows) were built for 1d; read with care."),
    ("tridesc_main_replay_4h_run_44928195720.json", "tri-desc-main-replay.yml run 44928195720 (2026-11-21 IST, 4h, 730d, 2586 fetched)",
     "scripts/tri_desc_main_replay.py (B-1598 4h)",
     "Descending-triangle replay on real main.py functions at 4h; thin n (42-162)."),
    ("island_oos_4h_run_44928797980.json", "island-validation.yml run 44928797980 (2026-11-21 IST, 4h, 730d, 2455 of 2763 with data)",
     "scripts/island_validation.py",
     "Island-reversal cell at 4h (segis/segoos = entry-date split; nonovl = one position per symbol)."),
)


def _iter(d):
    rows = d.get("rows")
    if rows is None:
        rows = [dict(v, tag=k) for k, v in (d.get("cells") or {}).items()]
    return rows


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    for fn, ref, src, note in _SRC:
        try:
            d = json.load(open(os.path.join(_DIR, fn)))
        except Exception:
            continue
        for r in _iter(d):
            try:
                tag = r["tag"]
                if tag in seen or "__4h__" not in tag or r.get("pfnet") is None:
                    continue
                seen.add(tag)
                pf = float(r["pfnet"])
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.EQUITY_SWING,
                    categories=(sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING,), timeframe="4h",
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=pf, pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r.get("win_pct") or 0.0),
                                       n_trades=int(r["n"]), avg_held_bars=float(r.get("avg_hold_bars") or 0.0),
                                       avg_held_hrs=float(r.get("avg_hold_bars") or 0.0) * 4.0,
                                       universe="NSE full universe file (2763 symbols)", run_ref=ref),
                    source=src,
                    evidence=(f"{ref}; raw docs/backtest_data/{fn}: PFnet {r['pfnet']}, gross {r.get('pf_gross')}, win {r.get('win_pct')}%, "
                              f"n={r['n']}, avg_hold {r.get('avg_hold_bars')} bars, ex-top5 {r.get('pfnet_ex_top5')}; "
                              f"exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}"),
                    notes=(note + (" PFnet>1.00 at 4h: main.py port/replay + user review owed before wiring (B-1668)."
                                   if pf > 1.0 else " Fails PFnet>1.00 after 0.8% cost; not wired."))))
            except Exception:
                continue
    return out
