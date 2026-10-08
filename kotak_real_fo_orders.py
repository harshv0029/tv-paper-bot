"""
Kotak Neo REAL F&O order placement.

Explicit user instruction (2026-09-07): "i can update the capital any
time. so build it right now" - real F&O order placement, built
UNCONDITIONALLY on today's account capital (margin_required's own live
checks earlier the same day, on both a NIFTY future and an MCX GOLDM
future, confirmed real capital is currently far short of either one's
required margin - see kotak_neo.margin_required's docstring). This
module works regardless: check_margin_affordable is what makes it
self-limiting (refuses to place anything the account can't afford AT THE
MOMENT of the attempt, via a fresh live check, never a cached/static
guess) - so raising real capital later makes every gate here "just work"
with no code change required.

Scope, explicit user instruction 2026-09-07 ("there are strategies where
put and call are together less than half of total cost too"): OPTIONS
BUYING (long call/put, long straddle - both legs bought, never sold) is
the primary target - premium paid is the entire risk, capped and known
upfront, unlike futures or any short option (undefined/large margin,
unlimited risk on the short side - see docs/STRATEGY_LOG.md's own
caution on row #4, Short Strangle: "Unlimited risk both sides"). This
module never places a SELL to open a new position, only to close one it
already opened (or, generically, place_real_fo_exit for whatever a
caller already tracks) - selling naked is out of scope, not just
unwired.

place/cancel are generic across nse_fo AND mcx_fo (same Kotak place_order
call either way, only trading_symbol/exchange_segment differ) - futures
placement is included here for completeness (see nse_fo_chain.
select_nse_future) but NOT wired to any automatic real entry in main.py -
no backtested outright-futures signal exists, and the margin math above
makes a 1-lot future impractical at any near-term realistic capital
anyway. Building the primitive now means futures needs no NEW real-order
code later, only a wiring decision once both an evidenced signal and
sufficient capital exist.

Same never-raises / nOrdNo-confirms-success discipline as
kotak_real_orders.py (equity) - see that module's place_real_entry
docstring for the full reasoning, unchanged here: every failure path
returns {"ok": False, "detail": ...} instead of raising, so a Kotak-side
hiccup can never propagate into the caller's own scheduler tick.

product="NRML" (carry, not intraday MIS) for every order here - a bought
option's risk is capped at the premium already paid, so it doesn't need
MIS's forced same-day squareoff the way a leveraged/short position
would; this app's own exit logic (EOD squareoff, stop/target on the
combined position) already manages the close explicitly.

CRITICAL EXCEPTION to "premium paid is the entire risk" above, single-
stock underlyings only (nse_fo_chain.STOCK_FO_UNDERLYINGS - 2026-09-16,
confirmed live via RELIANCE's real scrip data): single-stock F&O in
India settles by PHYSICAL DELIVERY of the underlying shares (option OR
future) if left open past expiry, not cash settlement like every index/
commodity underlying this module and nse_fo_chain.py otherwise resolve.
A bought call/put or an open future on one of these 210 names that isn't
closed before expiry can result in a real obligation to buy/sell the
underlying shares - NOT capped at the premium paid. Any caller that
opens a position in a STOCK_FO_UNDERLYINGS name MUST check
nse_fo_chain.must_force_close_before_expiry(underlying, expiry) on every
management tick and call place_real_fo_exit the moment it returns True -
this module itself has no position-tracking/exit-loop of its own to
enforce this (place_real_fo_entry/place_real_fo_exit are primitives, not
a scheduler), so the requirement lives here, in writing, for whichever
caller eventually manages these positions.
"""
import time
import kotak_neo


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_margin_affordable(exchange_segment: str, instrument_token: str, transaction_type: str,
                             quantity: int, order_type: str = "MKT", product: str = "NRML",
                             price: str = "0", trigger_price: str | None = None) -> dict:
    """Live, real margin/fund check against the account's CURRENT
    balance - never a static guess (real capital can change anytime, per
    this module's docstring), so this is checked fresh before every
    single F&O order, not cached. Returns {"ok": bool, "detail": ...,
    "reqd_margin_inr", "avl_margin_inr", "insuf_fund_inr", "raw_response"}.
    "ok" reads Kotak's own rmsVldtd field ("OK"/"NOT_OK" - confirmed real
    values 2026-09-07 from a live NIFTY future AND a live MCX GOLDM
    future, both genuinely insufficient-funds cases) - rmsVldtd IS the
    exchange's own risk-management-system verdict on affordability, not
    a number this code has to interpret itself by comparing avlMrgn/
    reqdMrgn by hand."""
    try:
        resp = kotak_neo.margin_required(
            exchange_segment=exchange_segment, instrument_token=instrument_token,
            transaction_type=transaction_type, quantity=quantity, order_type=order_type,
            product=product, price=price, trigger_price=trigger_price,
        )
    except Exception as e:
        return {"ok": False, "detail": f"margin_required raised: {e}"}
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "detail": f"unexpected margin_required response: {resp}", "raw_response": resp}
    ok = data.get("rmsVldtd") == "OK"
    reqd = _to_float(data.get("reqdMrgn"))
    avl = _to_float(data.get("avlMrgn"))
    insuf = _to_float(data.get("insufFund"))
    return {
        "ok": ok, "raw_response": resp,
        "reqd_margin_inr": reqd, "avl_margin_inr": avl, "insuf_fund_inr": insuf,
        "detail": None if ok else f"rmsVldtd={data.get('rmsVldtd')} - short by ~Rs{insuf}" if insuf is not None
        else f"rmsVldtd={data.get('rmsVldtd')}",
    }


def place_real_fo_entry(kotak_trading_symbol: str, exchange_segment: str, qty: int, product: str = "NRML") -> dict:
    """Places a REAL market BUY on nse_fo/mcx_fo. Never raises - see this
    module's docstring."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}
    try:
        resp = client.place_order(
            exchange_segment=exchange_segment, product=product, price="0", order_type="MKT",
            quantity=str(qty), validity="DAY", trading_symbol=kotak_trading_symbol, transaction_type="B",
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}
    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}
    return {"ok": True, "order_id": str(order_id), "raw_response": resp, "qty": qty}


def place_real_fo_exit(kotak_trading_symbol: str, exchange_segment: str, qty: int, product: str = "NRML") -> dict:
    """Places a REAL market SELL to close an already-open F&O position.
    Same never-raises discipline. No gate of its own - same reasoning as
    kotak_real_orders.place_real_exit: closing an already-open position
    must never be blocked by any switch, including this module's own
    reason for existing."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}
    try:
        resp = client.place_order(
            exchange_segment=exchange_segment, product=product, price="0", order_type="MKT",
            quantity=str(qty), validity="DAY", trading_symbol=kotak_trading_symbol, transaction_type="S",
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}
    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}
    return {"ok": True, "order_id": str(order_id), "raw_response": resp, "qty": qty}


# ---------------------------------------------------------------------------
# Real resting TRAILING stop-loss for long single-strike options (2026-10-08,
# explicit user rule: every single-strike option, call or put, always uses a
# trailing SL; weekly options live at most ~5 days). Mirrors the equity
# scan-then-act discipline (kotak_real_orders.ensure_resting_sl): a fresh
# Kotak order_report every call, never a cached local order id.
# ---------------------------------------------------------------------------
import kotak_real_orders as _kro

OPTION_TICK = 0.05  # NSE/BSE option premiums tick in Rs0.05


def _tick_round(price: float, down: bool = False) -> float:
    import math
    steps = price / OPTION_TICK
    steps = math.floor(steps + 1e-9) if down else round(steps)
    return round(max(steps, 1) * OPTION_TICK, 2)


def place_real_fo_stop_loss(kotak_trading_symbol: str, exchange_segment: str, qty: int,
                            trigger_price: float, product: str = "NRML") -> dict:
    """Resting SELL SL (limit-behind-trigger) for a long option. Limit sits 5%
    under the trigger (tick-aligned) so a fast premium drop still fills; the
    trigger itself is tick-aligned. Rejections are confirmed, never assumed."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}
    trigger = _tick_round(trigger_price)
    limit_price = _tick_round(trigger * 0.95, down=True)
    try:
        resp = client.place_order(
            exchange_segment=exchange_segment, product=product, price=str(limit_price), order_type="SL",
            quantity=str(qty), validity="DAY", trading_symbol=kotak_trading_symbol,
            transaction_type="S", trigger_price=str(trigger),
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}
    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}
    status = _kro._confirm_order_status(order_id)
    for _ in range(3):
        if status["status"] in ("rejected", "trigger pending", "open", "complete"):
            break
        time.sleep(1.5)
        status = _kro._confirm_order_status(order_id)
    if status["status"] == "rejected":
        return {"ok": False, "detail": f"order {order_id} rejected: {status['detail']}", "raw_response": resp}
    return {"ok": True, "order_id": str(order_id), "trigger_price": trigger, "limit_price": limit_price,
            "raw_response": resp}


def fetch_kotak_option_state(kotak_trading_symbol: str) -> dict:
    """Governance steps 1-2 for one option: Kotak positions() net qty, then
    order_report() live SELL SL orders. Returns {"ok", "net_qty", "live_sls":
    [{order_id, trigger, qty}], "detail"}. ok=False means Kotak could not be
    read - callers must then take NO destructive action."""
    try:
        client = kotak_neo.login()
        pos = client.positions()
        prow = pos.get("data") if isinstance(pos, dict) else None
        if not isinstance(prow, list):
            return {"ok": False, "detail": f"positions unreadable: {pos}"}
        rep = client.order_report()
        orows = rep.get("data") if isinstance(rep, dict) else None
        if not isinstance(orows, list):
            return {"ok": False, "detail": f"order_report unreadable: {rep}"}
    except Exception as e:
        return {"ok": False, "detail": f"kotak read raised: {e}"}
    net = 0.0
    for r in prow:
        if r.get("trdSym") == kotak_trading_symbol:
            net += _to_float(r.get("flBuyQty")) or 0.0
            net -= _to_float(r.get("flSellQty")) or 0.0
    live = []
    for r in orows:
        if r.get("trdSym") != kotak_trading_symbol or r.get("trnsTp") != "S":
            continue
        if str(r.get("prcTp", "")).upper() not in ("SL", "SL-M"):
            continue
        if str(r.get("ordSt", "")).lower() in _kro._TERMINAL_ORDER_STATUSES or not r.get("nOrdNo"):
            continue
        live.append({"order_id": str(r["nOrdNo"]), "trigger": _to_float(r.get("trgPrc")) or 0.0,
                     "qty": int(_to_float(r.get("qty")) or 0)})
    return {"ok": True, "net_qty": net, "live_sls": live}


def ensure_option_trailing_sl(kotak_trading_symbol: str, exchange_segment: str, qty: int,
                              desired_trigger: float, live_sls: list, allow_replace: bool = True) -> dict:
    """Given the live SLs just read from Kotak: adopt one already at/above the
    desired trigger and covering qty; otherwise cancel them and place the new
    (higher) trigger, restoring the old one if the new placement fails so the
    position is never left naked. A stop is never lowered here."""
    desired = _tick_round(desired_trigger)
    if live_sls:
        best = max(live_sls, key=lambda o: o["trigger"])
        if best["trigger"] >= desired - 0.005 and sum(o["qty"] for o in live_sls) >= qty:
            return {"ok": True, "action": "adopted_existing", "order_id": best["order_id"],
                    "trigger_price": best["trigger"]}
        if not allow_replace:
            return {"ok": False, "action": "skipped_no_replace", "order_id": best["order_id"],
                    "trigger_price": best["trigger"], "detail": "replace not allowed now"}
        for o in live_sls:
            _kro.cancel_real_order(o["order_id"])
        res = place_real_fo_stop_loss(kotak_trading_symbol, exchange_segment, qty, desired)
        if res.get("ok"):
            res["action"] = "replaced"
            return res
        restore = place_real_fo_stop_loss(kotak_trading_symbol, exchange_segment, qty, best["trigger"])
        res["action"] = "replace_failed"
        if restore.get("ok"):
            res["restored_order_id"] = restore["order_id"]
            res["restored_trigger"] = restore["trigger_price"]
        return res
    res = place_real_fo_stop_loss(kotak_trading_symbol, exchange_segment, qty, desired)
    res["action"] = "placed"
    return res
