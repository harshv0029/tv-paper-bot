"""B-1232: registers the tags that scripts/missing_registry_tags.py found in saved docs/backtest_data/*.json but not in the registry.
Each tag is its OWN row with its real metrics, pass or fail (never pooled, no existing row edited). Research-only (entry_fn=None); viability
is derived at read time from PFnet vs PFNET_LIVE_FLOOR and is not sufficient for wiring. Per-file decisions (also in the backlog row):

 elder_ge11_1h_run_38272885846.json  210  Elder gap-fade/MACD 1h, v3, IS/OOS/bull/bear segments, all with PFnet/trim1/trim5 -> registered (1h).
 pfoos_run_38187692191.json           54  brk20 portfolio-overlay in/out-of-sample windows (full / is60 / oos60) -> registered (1d).
 swing_min_rr_results_1d.json         12  Minervini-gate swing min-RR cells skipped earlier for n<30 -> registered with their real thin n.
 elder_batch3_merged_run_38169625565   9  osc reversal short / breadth nhnl_turn, n 1-2, PFnet undefined (no loser): stored PFnet 0.0 (fails
                                         closed, NOT a real zero), evidence says so (same precedent as strategy_registry_elderb3r2).
 index_option_trigger_results_*.json  81  index-option trigger cells skipped by the OOS n>=30 rule of strategy_registry_idxopt: registered with
                                         the ALL-sample 0.8% numbers as headline (OOS n<30 on every one); the universe field says so, the OOS/IS
                                         blocks stay in evidence. A different basis than the idxopt OOS headline: never compare across them.
Deliberately NOT registered: the 10 `sizing__*` rows of elder_batch3 (account-level position-sizing simulations: geo-mean equity, drawdown,
ruin %, no PFnet/win/trade metrics) and the 56 index-option cells with zero trades whose key has no `__v` grammar suffix (n=0; grammar-tagged zero-trade cells ARE kept with zeros). Raw data stays in the JSONs.
"""
import json
import os

import strategy_registry as sr

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "backtest_data")


def _load(fn):
    try:
        return json.load(open(os.path.join(_DIR, fn)))
    except Exception:
        return None


def _cat(tag, swing_default=sr.TradeCategory.SWING):
    return sr.TradeCategory.SHORT_SELL if "__short__" in tag else swing_default


def _ex(r):
    return json.dumps(r.get("exit_reasons"), separators=(",", ":"))


def _ge11(seen):
    d = _load("elder_ge11_1h_run_38272885846.json")
    out = []
    ref = "elder-ge11-validate.yml run 38272885846 (1h, cost 0.8%, 2026-10-12 IST)"
    for r in (d or {}).get("rows", []):
        tag = r["tag"]
        if tag in seen or r.get("pfnet") is None:
            continue
        seen.add(tag)
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_INTRADAY, categories=(_cat(tag, sr.TradeCategory.BUY),), timeframe="1h",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                               avg_held_hrs=float(r["avg_hold_bars"]) * sr.market_hours_per_bar("1h"), avg_held_raw_unit="1h bars",
                               universe=f"NSE full universe ({d.get('symbols_fetched')} fetched)", run_ref=ref),
            source="scripts/elder_ge11_validate.py",
            evidence=(f"{ref}: PFnet {r['pfnet']} (trim1 {r.get('pfnet_trim1')}, trim5 {r.get('pfnet_trim5')}), gross {r.get('pf_gross')}, win {r['win_pct']}%, "
                      f"n={r['n']} (raw_n {r.get('raw_n')}), avg_hold {r['avg_hold_bars']} 1h bars, avg_net {r.get('avg_net_ret_pct')}%, "
                      f"max_trade {r.get('max_trade_net_ret_pct')}%; exits {_ex(r)}"),
            notes="Elder gap-fade/MACD 1h validation cell (own tag per segment: pooled / segis / segoos / segbull / segbear). B-1232 registration of a "
                  "previously unregistered result. Viability derived from PFnet vs PFNET_LIVE_FLOOR; nothing wired."))
    return out


def _pfoos(seen):
    d = _load("pfoos_run_38187692191.json")
    out = []
    ref = "portfolio-overlay-oos.yml run 38187692191 (1d, cost 0.8%, entry-date split IS 60%)"
    for r in (d or {}).get("rows", []):
        tag = r["tag"]
        if tag in seen or r.get("pfnet") is None:
            continue
        seen.add(tag)
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(_cat(tag),), timeframe="1d",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                               avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY, avg_held_raw_unit="1d bars",
                               universe=f"NSE full universe ({d.get('symbols_fetched')} of {d.get('universe_size')} fetched)", run_ref=ref),
            source="scripts/portfolio_overlay_oos.py",
            evidence=(f"{ref}: overlay {r.get('overlay')} window {r.get('window')}: PFnet {r['pfnet']}, gross {r.get('pf_gross')}, win {r['win_pct']}%, n={r['n']}, "
                      f"avg_hold {r['avg_hold_bars']} bars, expectancy {r.get('expectancy_pct')}%, avg_win {r.get('avg_win_pct')}%, avg_loss {r.get('avg_loss_pct')}%, "
                      f"W/L {r.get('win_loss_ratio')}, split_ts {r.get('split_ts')}; exits {_ex(r)}"),
            notes="brk20 portfolio overlay in/out-of-sample window (full / is60 / oos60), each its own tag. B-1232 registration. The in-sample "
                  "windows are selection-biased by construction; read the oos60 tag. Nothing wired."))
    return out


def _swingminrr(seen):
    d = _load("swing_min_rr_results_1d.json")
    out = []
    ref = "swing min-RR 1d (B-842, run 38245172228; docs/backtest_data/swing_min_rr_results_1d.json, cost 0.008)"
    uni = f"full NSE universe file, {(d or {}).get('symbols_fetched')} of {(d or {}).get('universe_size')} symbols fetched with data"
    for r in (d or {}).get("rows", []):
        tag = r["tag"]
        if tag in seen or r.get("pfnet") is None or not r.get("n"):
            continue
        seen.add(tag)
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(_cat(tag),), timeframe="1d",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=float(r["pfnet"]), pfgross=float(r.get("pf_gross") or 0.0), win_rate_pct=float(r["win_pct"]),
                               n_trades=int(r["n"]), avg_held_bars=float(r["avg_hold_bars"]),
                               avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY, avg_held_raw_unit="1d bars",
                               universe=uni, run_ref=ref),
            source="scripts/swing_min_rr_research (B-842)",
            evidence=(f"{ref}: THIN SAMPLE n={r['n']} (<30, skipped by the earlier loader): pfnet={r['pfnet']} pfgross={r.get('pf_gross')} "
                      f"ex_top5={r.get('pfnet_ex_top5')} win={r['win_pct']}% avg_hold={r['avg_hold_bars']}bars; exits={_ex(r)}; "
                      f"top5={json.dumps(r.get('top5'), separators=(',', ':'))}"),
            notes="Minervini-gate swing min-RR cell with n<30: not evidence of an edge (quality-viable tables require n>=30). Registered so no result is dropped (B-1232)."))
    return out


def _batch3(seen):
    d = _load("elder_batch3_merged_run_38169625565.json")
    out = []
    ref = "elder-batch3-research.yml run 38169625565 (2026-10-11 IST, 1d, cost 0.8%, NIFTY200+ETF slots, not full NSE)"
    for r in (d or {}).get("rows", []):
        tag = r["tag"]
        if tag in seen or r.get("pfnet") is not None or not r.get("n"):
            continue  # rows WITH a PFnet were registered by strategy_registry_elderb3
        seen.add(tag)
        out.append(sr.StrategyDef(
            name=tag, asset_class=sr.AssetClass.EQUITY_SWING, categories=(_cat(tag),), timeframe="1d",
            status=sr.StrategyStatus.RESEARCH, entry_fn=None,
            metrics=sr.Metrics(pfnet=0.0, pfgross=0.0, win_rate_pct=float(r["win_pct"]), n_trades=int(r["n"]),
                               avg_held_bars=float(r["avg_hold_bars"]), avg_held_hrs=float(r["avg_hold_bars"]) * sr.TRADING_HOURS_PER_DAY,
                               avg_held_raw_unit="1d bars", universe="NIFTY200-restricted + ETF slots, not full NSE", run_ref=ref),
            source="scripts/elder_batch3_research.py",
            evidence=(f"{ref}: PFnet UNDEFINED in raw (no losing trade; n={r['n']}), stored 0.0 so it fails closed, NOT a real zero; "
                      f"win {r['win_pct']}%, avg_hold {r['avg_hold_bars']} bars, avg_net {r.get('avg_net_ret_pct')}%; exits {_ex(r)}"),
            notes="n=1-2: not evidence. Registered so the cell is on record (B-1232)."))
    return out


def _idxopt(seen):
    import glob
    out = []
    ref = "index-option trigger run 38218867644 (2026-10-12 IST, cost 0.8%, ALL-sample headline because OOS n<30)"
    hrs = {"5m": 5 / 60, "15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": sr.TRADING_HOURS_PER_DAY}
    for fn in sorted(glob.glob(os.path.join(_DIR, "index_option_trigger_results_*.json"))):
        try:
            d = json.load(open(fn))
        except Exception:
            continue
        for tag, c in d.get("cells", {}).items():
            a = c.get("pooled", {}).get("all", {})
            if tag in seen or not tag.endswith("__v1"):
                continue
            if a.get("n", 0) < 1 or "net_by_cost_pct" not in a:  # zero-trade cell: kept with zeros (island_gap05 precedent), not evidence
                seen.add(tag)
                out.append(sr.StrategyDef(
                    name=tag, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe=d["interval"],
                    status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                    metrics=sr.Metrics(pfnet=0.0, pfgross=0.0, win_rate_pct=0.0, n_trades=0,
                                       universe="3 indices (^NSEI, ^NSEBANK, ^BSESN), underlying-move trigger proxy: ZERO trades", run_ref=ref),
                    source="scripts/index_option_trigger_research (run 38218867644)",
                    evidence=f"{ref}: leg={c.get('option_leg')} atr_mult={c.get('atr_mult')} interval={d['interval']}: the cell produced no trades (n=0); zeros are placeholders, not a measured PFnet.",
                    notes="Zero-trade index-option cell (the trigger never fired on these indices/candles). Kept so no result is dropped (B-1232); n=0 is not evidence of an edge."))
                continue
            seen.add(tag)
            x = a["net_by_cost_pct"]["0.8"]
            o, i = c["pooled"].get("oos", {}), c["pooled"].get("is", {})

            def blk(b):
                if not b.get("n"):
                    return f"n={b.get('n', 0)}"
                y = b["net_by_cost_pct"]["0.8"]
                return f"n={b['n']} pfnet={y['pfnet']:.3f} win={y['win_pct']:.1f}% hold={b['avg_hold_bars']:.1f}bars"
            short = c["direction"] == "short"
            out.append(sr.StrategyDef(
                name=tag, asset_class=sr.AssetClass.OPTIONS, categories=(sr.TradeCategory.OPTIONS,), timeframe=d["interval"],
                status=sr.StrategyStatus.RESEARCH, entry_fn=None,
                metrics=sr.Metrics(pfnet=float(x["pfnet"]), pfgross=float(a["pfnet_gross"]), win_rate_pct=float(x["win_pct"]),
                                   n_trades=int(a["n"]), avg_held_bars=float(a["avg_hold_bars"]),
                                   avg_held_hrs=float(a["avg_hold_bars"]) * hrs[d["interval"]], avg_held_raw_unit=f"{d['interval']} bars",
                                   universe="3 indices (^NSEI, ^NSEBANK, ^BSESN), underlying-move trigger proxy, ALL-sample (OOS n<30)", run_ref=ref),
                source="scripts/index_option_trigger_research (run 38218867644)",
                evidence=(f"{ref}: leg={c['option_leg']} atr_mult={c['atr_mult']} interval={d['interval']}; ALL[{blk(a)} pfgross={a['pfnet_gross']:.3f} "
                          f"exits={json.dumps(a['exit_reasons'], separators=(',', ':'))}]; IS[{blk(i)}]; OOS[{blk(o)}]; "
                          f"ALL@0.1%cost pfnet={a['net_by_cost_pct']['0.1']['pfnet']:.3f}"),
                notes=("Index-option research cell (" + ("buy_put" if short else "buy_call") + ") skipped by the idxopt loader for OOS n<30; headline here is "
                       "the ALL-sample 0.8% figure, a different basis from the OOS headline of the other idxopt rows. Underlying-move test, not option premium "
                       "P&L. Any wiring needs a TRAILING SL on the premium and an always-attached SL/SLM. Nothing wired (B-1232).")))
    return out


def build():
    seen = {x.name for x in sr.REGISTRY}
    out = []
    for fn in (_ge11, _pfoos, _swingminrr, _batch3, _idxopt):
        try:
            out.extend(fn(seen))
        except Exception:
            continue
    return out
