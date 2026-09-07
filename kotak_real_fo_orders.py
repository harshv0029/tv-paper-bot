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
"""
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
