"""
Kotak Neo REAL order placement - Stage 3.

Explicit user instruction (2026-09-04): "Ok go ahead" -> "Build stage 3
(real order placement)", after this session's Phase 1/2/2.5 + live-feed
work (docs/TRADING_CONSTRAINTS.md) was verified complete. Real-money
constraints set explicitly by the user, in this exact conversation, not
assumed:
  - Cap: Rs 500 TOTAL REAL BUY NOTIONAL PER IST CALENDAR DAY (not per
    trade, not a lifetime ceiling - the user's own words: "in stage 3 all
    your experiments will use only upto INR 500 real money... per day").
    Now a live-editable runtime setting (real_daily_cap_inr) - see
    main.py's RUNTIME_SETTINGS_META - not a hardcoded Rs 500 any more.
  - Automation: fully automatic once enabled - no manual per-trade
    confirmation (user's explicit choice over the manual-confirm
    alternative).
  - Scope: low-priced NSE cash equities only (user's explicit choice) -
    MCX/options/indices are OUT of stage 3 v1, since a single MCX lot or
    option contract already exceeds Rs 500 (confirmed from real
    search_scrip data earlier this session), and indices aren't directly
    tradeable.

THIS MODULE PLACES REAL ORDERS WITH REAL MONEY. Every function here is
gated by main.py's is_real_trading_enabled() (TWO independent switches -
an env var AND a DB row, both default OFF - see main.py) before ever
being called; this module itself does not re-check that gate, by design -
it trusts main.py's caller to have already verified it, so there is
exactly ONE place in the codebase that decides "is real trading on".

API surface verified against kotakneoapi==3.0.1's OWN installed source
(neo_api_client/neo_api.py's place_order signature and
req_data_validation.py's real allowed values for exchange_segment/
product/order_type/transaction_type/validity) on 2026-09-04 - not
guessed, not assumed from documentation alone. The one thing that could
NOT be verified from a live account (this account had never placed a
real order before this module existed, so trade_report()/order_report()
had no real rows yet to inspect their field names from) was the exact
success/failure response shape of place_order() itself; for that,
Kotak's own published GitHub docs/samples (Kotak-Neo/kotak-neo-api,
corroborated via two independent search results 2026-09-04) show a real
sample success response containing "nOrdNo" (e.g. "220621000000097")
alongside "stat":"Ok"/"stCode":200. This module recognizes order
ACCEPTANCE ONLY by a non-empty "nOrdNo" in the response - the single
most positively-confirmable signal (an order number was actually
assigned) - and treats everything else (no nOrdNo, an "error"/"Error"
key, a non-dict response, a raised exception) as failed/uncertain. It
NEVER assumes acceptance from absence of an error, only from presence of
a real order id. This is a deliberately conservative reading given the
originally-unverifiable failure-shape: erring toward "did not place" is
the safe direction for real money. As of 2026-09-08 this account DOES
have real rows to inspect (see "Real fill confirmation" below), so
acceptance is no longer the end of the story - see that section.

Because of that same discipline, this module does NOT derive the daily
spend cap from Kotak's own trade_report()/order_report() - main.py
tracks that from its OWN real_trades SQLite table instead, populated at
order-attempt time using verified/confirmed data (see "Real fill
confirmation" below), sidestepping any need to trust an unverified
external response shape for risk-cap enforcement.

CNC (cash, no leverage) is used for both entry and exit - never
MIS/NRML/MTF - so the real cash-equity notional actually spent is
exactly quantity * price with no margin multiplier, keeping the daily
cap meaningful in the currency it was set in (real rupees), not a
margin-inflated exposure.

--- Real fill confirmation (2026-09-08) ---------------------------------------
Explicit user findings, both 2026-09-08: (1) real SL orders were coming
back REJECTED with no reason ever surfaced (see the SL section below) -
this module had NEVER once looked past nOrdNo-acceptance to an order's
actual final status; (2) "the exact buy or sell price vary due to gap in
time of execution... resync data ... to match all decision making based
on execution data" - entry_price (and, before the qty fix below, qty
too) had been the CALLER's pre-trade REQUEST (an estimated pre-fill
LTP), never Kotak's own confirmed fill data, even though order_report()
has always had the real fldQty/avgPrc/ordSt fields to read this from.

_confirm_order_status() is now the ONE place that follow-up-checks a
just-placed order's real status (used by place_real_entry, place_real_exit,
AND place_real_stop_loss below) - a single order_report(order_id) call
right after placement. "rejected" always overrides the earlier nOrdNo
acceptance (surfaced with Kotak's own rejRsn/rejShortDesc text). Anything
else (complete, open, or the report call itself failing) is treated as
accepted-and-trust-the-fill-data-if-present - a market CNC cash-equity
order on this account has, in every real fill observed so far, already
shown a populated avgPrc/fldQty by the time this follow-up call runs; a
still-open order (a genuine possibility this module does not poll or
wait for) falls back to the caller's own pre-trade estimate rather than
blocking - never worse than this module's old, permanent behavior.

--- Real order quantity (2026-09-08) -------------------------------------
place_real_entry no longer hardcodes quantity="1" ("fixed in this first
version" - that was Stage 3 v1's original, deliberately-conservative
starting point, now superseded). Explicit user instruction: "Qty should
be same as you pick in render. No hard coding needed" - the caller
(main.py's _maybe_place_real_entry) now passes the SAME qty the paper
engine's own position-sizing computed for this signal (signal_state.qty),
capped by real affordability (available real capital AND the remaining
real_daily_cap_inr budget) before it ever reaches this module - this
module places whatever qty it is given, unconditionally; it does not
re-derive or re-cap it.

--- Real resting stop-loss orders (2026-09-07) -------------------------------
Explicit user instruction, from the original complaint list ("share stop-
loss/trailing-stop to Kotak", "update stop-loss to Kotak on trigger"),
re-confirmed 2026-09-07 ("Yes, build it") after being asked directly:
until now, this bot's own "stop_loss" only ever lived in signal_state and
was enforced by _auto_signal_core polling price once per scheduler tick -
if Render's process was down or slow between ticks, a real position could
blow through its stop with nothing resting at the broker to catch it.

place_real_stop_loss places a REAL resting sell order at Kotak the
moment a real position opens, so the stop fires at the exchange itself,
independent of this app's own uptime. cancel_real_order lets the caller
(main.py) cancel that resting order before either replacing it at a
trailed-up trigger price or closing the position outright via
place_real_exit - a stale resting SL left behind after the position is
already closed would otherwise sit as a dangling sell order with nothing
left to sell.

order_type="SL" (stop-loss LIMIT), NOT "SL-M" (stop-loss market) -
changed 2026-09-08. BUG found live via the new /kotak-neo/order-report
diagnostic endpoint (explicit user finding: real SL sell orders on
AGI/AGL showing REJECTED in the Kotak app, 0/1 shares filled, no reason
ever surfaced by this codebase): EVERY SL-M order this function ever
placed came back nOrdNo-accepted (so place_real_entry logged it as "SL
resting", and real_positions.sl_order_id got set) but was then silently
RMS-REJECTED moments later with rejRsn "Market order with Algo Id not
allowed" - Kotak's algo/API order tag (algId, assigned to every order
this app places) blocks pure MARKET-priced orders, and SL-M is
fundamentally a market order once triggered. Net effect: real positions
had ZERO working resting stop-loss at the broker this whole time, while
the app's own state believed otherwise. "SL" (a LIMIT order that only
activates once trigger_price is touched) is not a bare market order and
is not subject to that same block - order_type "SL" and
req_data_validation.price_required_order_types (both confirmed from the
SDK's own settings.py source, 2026-09-08) show "SL" is one of the two
order types that REQUIRE a positive `price` in addition to trigger_price
(unlike "SL-M", which needs only trigger_price).

price (the limit) is set 1% below trigger_price for this SELL order -
once triggered, the sell only fills at that price or better (higher);
too tight a gap risks a no-fill in a fast-moving/gapping market (the
classic SL-vs-SL-M tradeoff), but a working limit stop that might
occasionally miss a fast gap is a large improvement over the SL-M this
replaces, which was rejected outright, every time, with NO stop resting
at all. Tick-size alignment is NOT verified (this function has no
tick-size input) - a rejection for that specific reason would show up
distinctly in _confirm_order_status's result and is a known, documented
gap, not a silent one.
"""
import kotak_neo


def _confirm_order_status(order_id: str) -> dict:
    """One order_report(order_id) call, right after placement - the only
    way to see whether an accepted order (a valid nOrdNo) was later
    REJECTED, and the only source of the REAL average fill price/filled
    quantity (as opposed to the pre-trade request). See this module's own
    top docstring, "Real fill confirmation", for why this exists.

    Returns {"status": "rejected"|"complete"|<other Kotak ordSt>|"unknown",
    "detail": str|None, "avg_price": float|None, "filled_qty": float|None,
    "row": dict|None}. Never raises - a failure to even reach Kotak here
    returns status "unknown" (not "rejected") so a transient report-API
    hiccup can never be mistaken for an actual rejection."""
    try:
        client = kotak_neo.login()
        report = client.order_report(order_id=str(order_id))
        rows = report.get("data") if isinstance(report, dict) else None
        row = next((r for r in (rows or []) if str(r.get("nOrdNo")) == str(order_id)), None)
    except Exception as e:
        return {"status": "unknown", "detail": f"order_report raised: {e}",
                "avg_price": None, "filled_qty": None, "row": None}

    if not row:
        return {"status": "unknown", "detail": "order id not found in order book",
                "avg_price": None, "filled_qty": None, "row": None}

    ord_st = str(row.get("ordSt", "")).lower()
    avg_price = None
    try:
        avg_price = float(row.get("avgPrc")) if row.get("avgPrc") not in (None, "", "0.00") else None
    except (TypeError, ValueError):
        pass
    filled_qty = None
    try:
        filled_qty = float(row.get("fldQty")) if row.get("fldQty") not in (None, "") else None
    except (TypeError, ValueError):
        pass

    if ord_st == "rejected":
        reason = row.get("rejRsn") or row.get("rejShortDesc") or "rejected (no reason returned)"
        return {"status": "rejected", "detail": reason, "avg_price": avg_price,
                "filled_qty": filled_qty, "row": row}
    return {"status": ord_st or "unknown", "detail": None, "avg_price": avg_price,
            "filled_qty": filled_qty, "row": row}


def place_real_entry(kotak_trading_symbol: str, qty: int, ltp: float) -> dict:
    """Places a REAL market BUY for `qty` shares via Kotak Neo, CNC, on
    nse_cm. Never raises - every failure path (login failure, an
    exception from place_order itself, an unrecognized response) returns
    {"ok": False, "detail": ...} instead, so a Kotak-side hiccup can
    never propagate out of this module and disturb the caller's own
    scheduler tick (paper trading included).

    kotak_trading_symbol must be Kotak's own real trading-symbol string
    (e.g. "RELIANCE-EQ") - sourced from kotak_live_feed's already-
    resolved, already-verified real instrument tokens, never guessed or
    derived from the Yahoo ticker. `qty` is the caller's already-decided,
    already-affordability-capped share count (see this module's top
    docstring, "Real order quantity") - this function does not second-
    guess it.

    On success, makes one follow-up _confirm_order_status call (see "Real
    fill confirmation" above): a confirmed "rejected" overrides the
    earlier acceptance and returns ok=False with Kotak's own reason;
    otherwise returns the REAL avg_price/filled_qty when Kotak has them
    yet (fill_price_confirmed=True), falling back to the caller's `ltp`/
    `qty` estimate when it doesn't (fill_price_confirmed=False) rather
    than blocking on an order that simply hasn't finished reporting."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product="CNC",
            price="0",
            order_type="MKT",
            quantity=str(qty),
            validity="DAY",
            trading_symbol=kotak_trading_symbol,
            transaction_type="B",
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}

    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}

    status = _confirm_order_status(order_id)
    if status["status"] == "rejected":
        return {"ok": False, "detail": f"order {order_id} rejected: {status['detail']}",
                "raw_response": resp, "status_check": status["row"]}

    fill_confirmed = status["avg_price"] is not None and status["filled_qty"] is not None
    return {
        "ok": True, "order_id": str(order_id), "raw_response": resp,
        "qty": status["filled_qty"] if fill_confirmed else qty,
        "fill_price": status["avg_price"] if fill_confirmed else ltp,
        "fill_price_confirmed": fill_confirmed,
        "requested_qty": qty, "est_price": ltp,
    }


def place_real_exit(kotak_trading_symbol: str, qty: int) -> dict:
    """Places a REAL market SELL to close a real position, CNC, on
    nse_cm. Same never-raises / rejection-confirmed discipline as
    place_real_entry - see its docstring, including the follow-up
    _confirm_order_status call and its fill_price/fill_price_confirmed
    fields.

    Deliberately has NO gate of its own (no is_real_trading_enabled
    check) - closing an already-open real position must never be
    blocked by the same switch that gates new entries; leaving a real
    position unmanaged is more dangerous than closing it. The caller
    (main.py's _maybe_place_real_exit) only calls this when a real
    position genuinely exists to close.
    """
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product="CNC",
            price="0",
            order_type="MKT",
            quantity=str(qty),
            validity="DAY",
            trading_symbol=kotak_trading_symbol,
            transaction_type="S",
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}

    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}

    status = _confirm_order_status(order_id)
    if status["status"] == "rejected":
        return {"ok": False, "detail": f"order {order_id} rejected: {status['detail']}",
                "raw_response": resp, "status_check": status["row"]}

    fill_confirmed = status["avg_price"] is not None and status["filled_qty"] is not None
    return {
        "ok": True, "order_id": str(order_id), "raw_response": resp,
        "qty": status["filled_qty"] if fill_confirmed else qty,
        "fill_price": status["avg_price"] if fill_confirmed else None,
        "fill_price_confirmed": fill_confirmed,
        "requested_qty": qty,
    }


def place_real_stop_loss(kotak_trading_symbol: str, qty: int, trigger_price: float) -> dict:
    """Places a REAL resting stop-loss sell order at Kotak for an already-
    open real position, so the stop fires at the exchange even if this app
    or Render's process is down between scheduler ticks. See this
    module's top docstring ("Real resting stop-loss orders" and "Real
    fill confirmation") for the order-type and rejection-confirmation
    reasoning - order_type="SL" (a limit order gated behind trigger_price)
    with `price` set 1% below trigger for this SELL, and a follow-up
    _confirm_order_status call so a rejection is never mistaken for a
    working resting stop."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    limit_price = round(trigger_price * 0.99, 2)
    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product="CNC",
            price=str(limit_price),
            order_type="SL",
            quantity=str(qty),
            validity="DAY",
            trading_symbol=kotak_trading_symbol,
            transaction_type="S",
            trigger_price=str(trigger_price),
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}

    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}

    status = _confirm_order_status(order_id)
    if status["status"] == "rejected":
        return {"ok": False, "detail": f"order {order_id} rejected: {status['detail']}",
                "raw_response": resp, "status_check": status["row"]}

    return {"ok": True, "order_id": str(order_id), "raw_response": resp,
            "trigger_price": trigger_price, "limit_price": limit_price}


def cancel_real_order(order_id: str) -> dict:
    """Cancels a real resting order (e.g. a stop-loss placed by
    place_real_stop_loss) at Kotak. Never raises - a cancel failure (the
    order already filled, already cancelled, or a transient API error) is
    reported back, never thrown; the caller treats a failed cancel as
    best-effort (see main.py's real-SL sync/exit call sites) since the
    exchange itself is always the source of truth on whether a given
    order can still be cancelled."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    try:
        resp = client.cancel_order(order_id=str(order_id))
    except Exception as e:
        return {"ok": False, "detail": f"cancel_order raised: {e}"}

    if isinstance(resp, dict) and resp.get("error"):
        return {"ok": False, "detail": str(resp["error"]), "raw_response": resp}
    return {"ok": True, "raw_response": resp}
