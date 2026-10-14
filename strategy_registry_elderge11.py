"""Registers the Elder gap-fade (exhaust/common) and MACD hist_exhaust cells of elder-macd-dirgap-research.yml run 38208431466
(2026-10-12 IST, 1d, cost 0.8%, 7059 fetched summed over families) as their OWN research-only tags (B-850 / B-852).

Why new tags: the same cells (v1, no rerun key) are already registered from run 38145684388 / 38177547622 with pfgross 0.0 and
different numbers (macd hist_exhaust long atr3_zf1: 0.929 there vs 1.157 here on n 96049 vs 96207, i.e. 158 extra trades moved PFnet 0.23,
a glitch-bar signature; B-864 guard postdates both). Never-overwrite rule: a new run is a new tag, so these carry the extra param
`rr1` (rerun of 38208431466), keys alphabetical (atr, nb, rr / atr, rr, zf), same logic version v1. All raw fields kept: PFnet net/gross,
win %, n, avg hold bars, avg net %, exit reasons. Raw data: docs/backtest_data/elder_macd_dirgap_38208431466_results.json.
Research-only (entry_fn=None). Viability is derived at read time from PFnet vs PFNET_LIVE_FLOOR and is NOT sufficient for wiring:
OOS n>=30, ex-top5/trim and a bad-bar-guarded rerun are owed (elder-ge11-validate.yml, B-850)."""
import json
import os
import re

import strategy_registry as sr

_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data",
                   "elder_macd_dirgap_38208431466_results.json")
_REF = "elder-macd-dirgap-research.yml run 38208431466 (2026-10-12 IST, 1d, cost 0.8%, 7059 fetched summed over families)"
_WANT = re.compile(r"^(gaps__(exhaust_fade|common_fade)__|macd__hist_exhaust__)")


def rr_tag(tag):
    """Insert the rerun key `rr1` into the params field in alphabetical position."""
    p = tag.split("__")
    toks = p[4].split("_")
    toks.append("rr1")
    toks.sort(key=lambda t: re.match(r"[a-z]+", t).group(0))
    p[4] = "_".join(toks)
    return "__".join(p)


def build():
    out, seen = [], {x.name for x in sr.REGISTRY}
    try:
        rows = json.load(open(_FN))["rows"]
    except Exception:
        return out
    for r in rows:
        try:
            if not _WANT.match(r["tag"]) or r.get("pfnet") is None:
                continue
            tag = rr_tag(r["tag"])
            if tag in seen:
                continue
            seen.add(tag)
            cat = sr.TradeCategory.SHORT_SELL if "__short__" in tag else sr.TradeCategory.SWING
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(cat,), timeframe="1d",
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(
                    pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                    n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                    universe="7059 fetched summed over families (broad NSE+ETF harness universe)", run_ref=_REF),
                source="scripts/elder_macd_dirgap_research.py",
                evidence=f"{_REF}: PFnet {r['pfnet']} (gross {r.get('pf_gross')}), win {r['win_pct']}%, n={r['n']}, "
                         f"avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; "
                         f"exits {json.dumps(r.get('exit_reasons'), separators=(',', ':'))}; rerun of {r['tag']} (rr1 = run 38208431466)",
                notes="Rerun tag of a v1 cell (B-850/B-852). One position per symbol by construction (er.simulate skips signals before its previous exit). "
                      "Not validated: no OOS split, no ex-top5/trim, run predates the B-864 bad-bar guard. Research-only; "
                      "viability derived from PFnet vs PFNET_LIVE_FLOOR; wiring owed (always-attached SL, swing engine only)."))
        except Exception:
            continue
    return out
