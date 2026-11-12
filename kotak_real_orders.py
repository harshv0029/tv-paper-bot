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

--- Real resting target (profit-booking) orders (2026-09-08) -----------------
Explicit user instruction: "place the target you have planned for each
trade so that it can be booked once reached" - mirrors the resting-SL
reasoning above for the OTHER side of the trade: until now, the paper
engine's own target price only ever lived in signal_state and was
enforced by the same once-per-tick poll (last_close >= row["target"] in
main.py's _auto_signal_core) - a favorable move that happened and
reversed between two ticks (or while Render's process was down/slow)
could be missed entirely, same exposure the resting SL was built to
close on the loss side.

place_real_target places a REAL resting LIMIT sell (order_type "L", no
trigger_price - this is a plain limit order, not a stop) at the paper
engine's target price, the moment a real position opens (see main.py's
_maybe_place_real_entry, right after the SL leg). A bare "L" limit sell
was never implicated in the algo-tag MARKET-order block that broke SL-M
(see place_real_stop_loss's own docstring) - every bot-placed real SELL
observed on this account with order_type "L" has gone through cleanly,
so no analogous rejection is expected here.

Unlike the SL leg, the target price does NOT trail/change over the
trade's life (the paper engine's own "target" is fixed at entry - only
"stop_loss" ratchets), so there is no per-tick replace logic for this
order the way _maybe_sync_real_stop_loss replaces the SL. Whichever leg
fires first (SL or target) closing the real position, the OTHER resting
order must be cancelled so it doesn't sit orphaned - see main.py's
_maybe_place_real_exit, which now cancels both sl_order_id and
target_order_id before selling.

Deliberately NOT retried on a later tick if placement fails (unlike the
SL leg's own per-tick replace in main.py's _maybe_sync_real_stop_loss) -
a failed placement is logged and left for a human/reconcile pass to
notice, same discipline as every other known-and-documented gap in this
module.

cancel_existing_resting_target (2026-09-21, explicit user instruction:
"before placing next order when one entered position there and one same
next order of same asset in order book then first check which order
there... cancel that from order book and then validate and then place
new order") - the target-side mirror of cancel_existing_resting_sl below,
for the exact same lost-tracking gap (a restart landing between "a
target got placed" and the next journal-sync snapshot capturing its
target_order_id restores the position with target_order_id back to NULL
even though a real resting order still exists at Kotak). A blind sweep-
and-cancel of every resting "L" limit sell for a symbol WOULD risk
catching a genuine MANUAL limit order the user placed directly at Kotak
(this account trades manually too) - the exact reason this function
didn't exist for a long time. What makes it safe now: every order this
app itself places carries Kotak's own algo-order tag (ordSrc
"ADMINCPPAPI_NEOTRADEAPI", algId not "NA"/blank - confirmed live,
distinct from a manual/mobile order's ordSrc "ADMINCPPAPI_MOB"/algId
"NA", same tag main.py's own reconcile-adopt logic already trusts), so
this sweep filters on that tag too, not just symbol+side+order-type -
only ever cancels an order THIS app itself placed, never a manual one.
"""
import threading
import time

import kotak_neo

# Shared by cancel_existing_resting_sl/cancel_existing_resting_target - an
# order in any of these statuses is already done (filled/dead), nothing to
# cancel.
_TERMINAL_ORDER_STATUSES = {"complete", "rejected", "cancelled", "cancelled by user", "cancelledbyuser", "expired"}


# B-1448 (2026-11-02): 155 Kotak orders had no app log row, mostly rejected SL retries: the callers log a failed
# SL with order_id=None (a rejected result carries `rejected_order_id`, not `order_id`), so the reconcile's
# order-id match never found them. Every send this module makes (place, cancel) now reports its outcome, with the
# Kotak order id and a reason, to a sink main.py registers (it writes real_order_events). The sink is called, never
# the database directly, so this module stays DB-free. Which orders are sent is unchanged.
_SEND_SINK = None
_REPEAT_WINDOW_S = 300.0
_LAST_REJECTION: dict = {}  # (trdSym, leg, short reject text) -> (first_ts, count)


def set_order_send_sink(fn) -> None:
    global _SEND_SINK
    _SEND_SINK = fn


def _symbol_from_trdsym(trdsym):
    if not trdsym:
        return None
    t = str(trdsym)
    return t.rsplit("-", 1)[0] + ".NS" if t.endswith(("-EQ", "-BE", "-BZ", "-SM", "-ST")) else t


def _report_send(leg: str, purpose: str, trdsym, res, order_id_hint=None) -> None:
    """Hand one send outcome to the sink: placed / rejected (with Kotak's reason) / error. A login failure is
    not a send (nothing reached Kotak), so it is not reported. A rejection repeating for the same symbol, leg and
    reason within _REPEAT_WINDOW_S is still reported (each one is a real Kotak order) with a compact detail."""
    try:
        if not isinstance(res, dict):
            return
        detail = str(res.get("detail") or "")
        rej_oid = res.get("rejected_order_id")
        if not res.get("ok") and (detail.startswith("login failed") or detail.startswith("precheck failed")):
            # B-1322: nothing reached Kotak (no token / a pre-send check refused the order), so there is no Kotak
            # row either; without this the attempt left no trace at all (JIOFIN 21 Oct). One row per symbol, leg
            # and cause per _REPEAT_WINDOW_S, so a token outage does not flood the log.
            not_sent = "login" if detail.startswith("login failed") else "precheck"
            key = (str(trdsym), leg, not_sent + detail[:60])
            now = time.time()
            first, cnt = _LAST_REJECTION.get(key, (0.0, 0))
            if cnt and now - first <= _REPEAT_WINDOW_S:
                _LAST_REJECTION[key] = (first, cnt + 1)
                return
            _LAST_REJECTION[key] = (now, 1)
            sink = _SEND_SINK
            if sink is not None:
                sink({"symbol": _symbol_from_trdsym(trdsym), "kotak_trading_symbol": trdsym, "leg": leg,
                      "event": "kotak_login_failed" if not_sent == "login" else "sl_precheck_failed",
                      "order_id": None, "new_state": "not sent", "detail": detail[:200],
                      "reason": f"{purpose}; NOT sent to Kotak ({'Kotak login failed' if not_sent == 'login' else 'pre-send check refused it'})",
                      "immediate": True, "ts": now})
            return
        if res.get("ok"):
            oid = res.get("order_id") or order_id_hint
            event, state = ("kotak_cancelled", "cancel accepted") if leg == "cancel" else ("kotak_placed", "accepted")
            reason = f"{purpose}; Kotak accepted it"
            extra = [f"{k}={res.get(k)}" for k in ("trigger_price", "target_price", "limit_price", "band_clamped_from")
                     if res.get(k) is not None]
            if res.get("adopted_after_lost_ack"):
                extra.append("ack lost; adopted the live order from Kotak's order book")
            info = " ".join(extra) or None
            immediate = False
        elif rej_oid:
            oid, event, state = str(rej_oid), "kotak_rejected", "rejected"
            rej = detail.split("rejected:", 1)[-1].strip() if "rejected:" in detail else detail
            key = (str(trdsym), leg, rej[:60])
            now = time.time()
            first, cnt = _LAST_REJECTION.get(key, (0.0, 0))
            if cnt and now - first <= _REPEAT_WINDOW_S:
                cnt += 1
                _LAST_REJECTION[key] = (first, cnt)
                info = f"repeat #{cnt} within {int(_REPEAT_WINDOW_S)}s: {rej[:60]}"
            else:
                _LAST_REJECTION[key] = (now, 1)
                info = f"Kotak rejRsn: {rej[:200]}"
            reason = f"{purpose}; Kotak rejected it"
            immediate = True
        else:
            oid = order_id_hint
            if leg == "cancel":
                event, reason = "kotak_cancel_failed", f"{purpose}; Kotak did not accept the cancel"
            else:
                event, reason = "kotak_send_error", f"{purpose}; the send failed before Kotak returned an order id"
            state = "failed"
            info = detail[:200] or None
            immediate = True
        if oid:
            _ORDER_REASONS.setdefault(str(oid), reason)
        sink = _SEND_SINK
        if sink is not None:
            sink({"symbol": _symbol_from_trdsym(trdsym), "kotak_trading_symbol": trdsym, "leg": leg,
                  "event": event, "order_id": str(oid) if oid else None, "new_state": state,
                  "detail": info, "reason": reason, "immediate": immediate, "ts": time.time()})
    except Exception as e:  # noqa: BLE001 - logging must never break an order path
        print(f"[order_log] B-1448 send report failed (non-fatal): {e}")


def _records_send(leg: str, purpose: str):
    """Decorator for every function that sends one order to Kotak (first positional arg = the trading symbol,
    or the order id for a cancel). Reports the returned outcome; never changes the result or what is sent."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            res = fn(*args, **kwargs)
            first = args[0] if args else (kwargs.get("kotak_trading_symbol") or kwargs.get("order_id"))
            if leg == "cancel":
                _report_send(leg, purpose, None, res, order_id_hint=str(first) if first else None)
            else:
                _report_send(leg, purpose, first, res)
            return res
        return wrapper
    return deco


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


@_records_send("entry", "real market BUY entry")
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
        return _rejected_result(order_id, status, resp)

    fill_confirmed = status["avg_price"] is not None and status["filled_qty"] is not None
    return {
        "ok": True, "order_id": str(order_id), "raw_response": resp,
        "qty": status["filled_qty"] if fill_confirmed else qty,
        "fill_price": status["avg_price"] if fill_confirmed else ltp,
        "fill_price_confirmed": fill_confirmed,
        "requested_qty": qty, "est_price": ltp,
    }


@_records_send("short_entry", "real market SELL-to-open short entry")
def place_real_short_entry(kotak_trading_symbol: str, qty: int, ltp: float, product: str = "MIS") -> dict:
    """Places a REAL market SELL-TO-OPEN for `qty` shares via Kotak Neo -
    the short mirror of place_real_entry (2026-09-29, explicit user
    instruction to implement short selling). Same never-raises /
    rejection-confirmed discipline; only two things differ from
    place_real_entry: transaction_type="S" (sell to open, not buy) and
    product="MIS" instead of "CNC" - a naked equity short cannot be held
    overnight (no shares to deliver at T+1 settlement without a
    borrow this codebase has no mechanism for), so MIS's own broker-
    enforced mandatory same-day square-off is the correct, and only
    sound, product type here - it is not an arbitrary choice.

    No short-sell-eligibility pre-check is performed here (explicit user
    decision 2026-09-29, given the tradeoff: NSE Trade-to-Trade series
    stocks cannot legally be sold short intraday and this codebase has no
    T2T membership data source) - an ineligible symbol is expected to be
    rejected by Kotak's own RMS, surfaced via the same _confirm_order_status
    rejection path place_real_entry already uses, not silently placed.
    """
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product=product,
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
        return _rejected_result(order_id, status, resp)

    fill_confirmed = status["avg_price"] is not None and status["filled_qty"] is not None
    return {
        "ok": True, "order_id": str(order_id), "raw_response": resp,
        "qty": status["filled_qty"] if fill_confirmed else qty,
        "fill_price": status["avg_price"] if fill_confirmed else ltp,
        "fill_price_confirmed": fill_confirmed,
        "requested_qty": qty, "est_price": ltp,
    }


@_records_send("short_cover", "real market BUY-to-cover short exit")
def place_real_short_cover(kotak_trading_symbol: str, qty: int, product: str = "MIS") -> dict:
    """Places a REAL market BUY-TO-COVER to close a real short position,
    MIS, on nse_cm - the short mirror of place_real_exit. Same never-
    raises / rejection-confirmed discipline, and deliberately has NO gate
    of its own for the exact same reason place_real_exit doesn't: closing
    an already-open real short must never be blocked by the entry kill
    switch - an unmanaged open short is more dangerous than covering it,
    doubly so given a short's open-ended loss potential."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product=product,
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
        return _rejected_result(order_id, status, resp)

    fill_confirmed = status["avg_price"] is not None and status["filled_qty"] is not None
    return {
        "ok": True, "order_id": str(order_id), "raw_response": resp,
        "qty": status["filled_qty"] if fill_confirmed else qty,
        "fill_price": status["avg_price"] if fill_confirmed else None,
        "fill_price_confirmed": fill_confirmed,
        "requested_qty": qty,
    }


@_records_send("exit", "real market SELL exit")
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
        return _rejected_result(order_id, status, resp)

    fill_confirmed = status["avg_price"] is not None and status["filled_qty"] is not None
    return {
        "ok": True, "order_id": str(order_id), "raw_response": resp,
        "qty": status["filled_qty"] if fill_confirmed else qty,
        "fill_price": status["avg_price"] if fill_confirmed else None,
        "fill_price_confirmed": fill_confirmed,
        "requested_qty": qty,
    }


def cancel_existing_resting_sl(kotak_trading_symbol: str) -> dict:
    """Safety net for a stale/lost sl_order_id in main.py's own
    real_positions tracking - found live 2026-09-08, explicit user
    finding (screenshot): TWO live resting SL sell orders for the same
    1-share AGL position, same trigger/limit price, 11 minutes apart.
    Root cause: real_positions is SQLite, wiped on every Render restart
    like every other table here, and is only as fresh as the last
    journal-sync snapshot (state/real_positions.json) - a restart landing
    between "an SL got placed" and "the next snapshot captured its
    sl_order_id" restores the position with sl_order_id back to NULL even
    though a real resting order still exists at Kotak. The next tick's
    retry-when-no-SL-is-resting path (main.py's _maybe_sync_real_stop_loss)
    then had nothing to cancel (its only cancel trigger is a KNOWN
    sl_order_id) and placed a second one - orphaning the first, live, at
    the broker, with nothing in this app's state pointing at it any more.

    Call this BEFORE placing any "no known SL to replace" resting SL
    (i.e. exactly the case main.py's own known-id cancel-then-replace
    logic can't cover) - queries Kotak's OWN order book (ground truth,
    not this app's possibly-stale DB state) for any non-terminal SELL/SL
    order on this symbol and cancels every one found, so a duplicate can
    never accumulate again regardless of why this app's own tracking went
    stale. Never raises; a failure to even fetch the order book is
    reported but treated as "nothing found to cancel" - fails open, since
    the caller places its own fresh SL regardless of this call's outcome,
    so a real position is never left unprotected over this check
    failing."""
    try:
        client = kotak_neo.login()
        report = client.order_report()
        rows = report.get("data") if isinstance(report, dict) else None
    except Exception as e:
        return {"cancelled": [], "detail": f"could not fetch order book: {e}"}

    cancelled = []
    for row in (rows or []):
        if row.get("trdSym") != kotak_trading_symbol:
            continue
        if row.get("trnsTp") != "S":
            continue
        if str(row.get("prcTp", "")).upper() not in ("SL", "SL-M"):
            continue
        if str(row.get("ordSt", "")).lower() in _TERMINAL_ORDER_STATUSES:
            continue
        order_id = row.get("nOrdNo")
        if not order_id:
            continue
        cancel_real_order(str(order_id))
        cancelled.append(str(order_id))
    return {"cancelled": cancelled, "detail": None}


def cancel_all_open_sells(kotak_trading_symbol: str) -> dict:
    """B-1369 (2026-10-26, owner: "read whole book which is active on Kotak, then cancel current SL for that symbol,
    then place market order to close"): step 1 + 2 of a stop-breach close. Reads Kotak's live order book, cancels
    EVERY non-terminal SELL on the symbol (SL, SL-M and plain limit: a converted stop or target also reserves the
    shares, so a market sell would be rejected or double-sell), then re-reads the book to confirm none is still live.
    ok=True only when the book was read and nothing open remains; the caller sends the market sell only then.
    Never raises."""
    def _open_sells():
        report = kotak_neo.login().order_report()
        rows = order_rows_from_report(report)
        if rows is None:
            raise ValueError(f"order_report returned no data list: {str(report)[:160]}")
        return [r for r in rows if r.get("trdSym") == kotak_trading_symbol and r.get("trnsTp") == "S"
                and str(r.get("ordSt", "")).strip().lower() not in _TERMINAL_ORDER_STATUSES and r.get("nOrdNo")]
    try:
        found = _open_sells()
    except Exception as e:
        return {"ok": False, "cancelled": [], "remaining": None, "detail": f"could not read order book: {e}"}
    cancelled, failed = [], []
    for r in found:
        res = cancel_real_order(str(r["nOrdNo"]))
        (cancelled if res.get("ok") else failed).append(str(r["nOrdNo"]))
    try:
        remaining = [str(r["nOrdNo"]) for r in _open_sells()] if found else []
    except Exception as e:
        return {"ok": False, "cancelled": cancelled, "remaining": None, "detail": f"could not re-read order book: {e}"}
    return {"ok": not remaining, "cancelled": cancelled, "failed": failed, "remaining": remaining,
            "detail": None if not remaining else "open sell order(s) still live after cancel"}


def cancel_existing_resting_sl_short(kotak_trading_symbol: str) -> dict:
    """Short mirror of cancel_existing_resting_sl (2026-09-30, explicit
    user instruction to bring short positions' per-tick SL sync to full
    parity with the long side) - a short's OWN protective stop is a
    resting BUY (transaction_type "B"), the opposite side from a long's
    resting SELL, so the long version's `trnsTp != "S"` filter would never
    match a short's real SL order at all. Same restart-race this app's
    real_positions_short tracking is equally exposed to (SQLite, wiped on
    every restart) - queries Kotak's OWN order book for any non-terminal
    BUY/SL order on this symbol and cancels every one found before a
    fresh one is placed. Same fail-open contract as the long version: a
    failure to even fetch the order book is treated as "nothing found to
    cancel," never as a reason to skip placing the caller's own fresh
    SL."""
    try:
        client = kotak_neo.login()
        report = client.order_report()
        rows = report.get("data") if isinstance(report, dict) else None
    except Exception as e:
        return {"cancelled": [], "detail": f"could not fetch order book: {e}"}

    cancelled = []
    for row in (rows or []):
        if row.get("trdSym") != kotak_trading_symbol:
            continue
        if row.get("trnsTp") != "B":
            continue
        if str(row.get("prcTp", "")).upper() not in ("SL", "SL-M"):
            continue
        if str(row.get("ordSt", "")).lower() in _TERMINAL_ORDER_STATUSES:
            continue
        order_id = row.get("nOrdNo")
        if not order_id:
            continue
        cancel_real_order(str(order_id))
        cancelled.append(str(order_id))
    return {"cancelled": cancelled, "detail": None}


def cancel_existing_resting_target(kotak_trading_symbol: str) -> dict:
    """Target-side mirror of cancel_existing_resting_sl above - see this
    module's own top docstring ("Real resting target" section,
    cancel_existing_resting_target paragraph) for the full reasoning,
    including why the bot-order-tag filter below is what makes this safe
    to sweep-and-cancel (unlike a bare symbol+side+order-type match, which
    would risk catching a genuine manual limit order on this same
    account).

    Call this BEFORE placing a fresh target when target_order_id is
    unknown (main.py's own known-id cancel-then-replace logic already
    covers the case where it IS known) - queries Kotak's OWN order book
    (ground truth, not this app's possibly-stale DB state) for any non-
    terminal, THIS-APP-PLACED limit SELL on this symbol and cancels every
    one found. Never raises; a failure to even fetch the order book is
    reported but treated as "nothing found to cancel" - fails open, since
    the caller places its own fresh target regardless of this call's
    outcome, same fail-open contract as cancel_existing_resting_sl."""
    try:
        client = kotak_neo.login()
        report = client.order_report()
        rows = report.get("data") if isinstance(report, dict) else None
    except Exception as e:
        return {"cancelled": [], "detail": f"could not fetch order book: {e}"}

    cancelled = []
    for row in (rows or []):
        if row.get("trdSym") != kotak_trading_symbol:
            continue
        if row.get("trnsTp") != "S":
            continue
        if str(row.get("prcTp", "")).upper() != "L":
            continue
        if str(row.get("ordSt", "")).lower() in _TERMINAL_ORDER_STATUSES:
            continue
        # The bot-order tag (confirmed live, see main.py's own reconcile-
        # adopt logic for the same check) - this is what makes it safe to
        # cancel a plain limit sell without risking a manual one.
        if row.get("ordSrc") != "ADMINCPPAPI_NEOTRADEAPI" or row.get("algId") in (None, "NA", ""):
            continue
        order_id = row.get("nOrdNo")
        if not order_id:
            continue
        cancel_real_order(str(order_id))
        cancelled.append(str(order_id))
    return {"cancelled": cancelled, "detail": None}


def is_cas_transition_rejection(detail: str) -> bool:
    """True if a rejection's detail text names NSE's Closing-Auction-
    Session (CAS) transition - confirmed live 2026-09-22 (WAAREEENER.NS/
    NATIONALUM.NS): a narrow order-freeze window in the last few minutes
    before market close, distinct from the T1-holdings rule and the tick-
    size rejection this module already handles separately. Rejection text
    seen live: "OMS: Trading session is in Transition to CAS session".

    Explicit user instruction: on this specific rejection, stop retrying
    the resting LIMIT/SL-LIMIT order and place a market order instead.
    The freeze itself briefly rejects EVERY order type, market included
    (a manual MARKET sell placed mid-transition got the identical
    rejection live, seconds before a repeat of the same manual MARKET
    order succeeded once the freeze cleared) - so a single market retry
    is not guaranteed to land on the first try, but it is the right thing
    to keep retrying: unlike a resting LIMIT, a MARKET order doesn't go
    stale against a price that moved while it waited, and the existing
    tick-by-tick retry loop already re-attempts it every cycle until the
    freeze clears. See main.py's _maybe_sync_real_stop_loss for the
    caller that escalates straight to a market exit on this."""
    return "transition to cas session" in (detail or "").lower()


def _round_to_tick(price: float, tick: float = 0.05) -> float:
    """Rounds `price` to the nearest multiple of `tick`. Default 0.05 is
    NSE's standard cash-equity tick size (scrips priced under ~Rs 15 use
    0.01, but every multiple of 0.05 is ALSO a valid multiple of 0.01, so
    0.05 is a safe fallback covering both). NOT correct for every symbol
    though - some (surveillance/ASM-linked ones confirmed live, see
    _tick_size_for's own docstring for the ENRIN.NS incident this closes)
    trade with a wider mandated tick. Both real callers below pass
    _tick_size_for(kotak_trading_symbol) explicitly rather than relying on
    this default - the default here only matters for a caller that can't
    look one up.

    BUG found live 2026-09-08: place_real_stop_loss's own prior fix set
    price = trigger_price with no rounding at all, reasoning that
    trigger_price came from the paper engine's own real-candle-derived
    stop level and was therefore already tick-aligned - true for the
    ATR/swing-based stops that reasoning was written for, but NOT true
    for main.py's reconcile-endpoint governance-backfill path, which
    computes stop_loss/target synthetically as
    round(entry_price * pct_math, 2) - plain 2-decimal rounding, with no
    guarantee of tick alignment. AARTIIND-EQ's backfilled stop of 497.28
    was rejected outright ("Order price is not a multiple of tick size"),
    leaving a real position with NO resting stop. Rounding to the nearest
    tick at the Kotak-order boundary (here, not at every computation
    site) fixes every caller uniformly."""
    return round(round(price / tick) * tick, 2)


_TICK_SIZE_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h - a scrip's tick size only
# ever changes on a rare NSE/SEBI surveillance reclassification, never
# intraday, so this doesn't need a short TTL like the live-price caches.
_tick_size_cache: dict = {}


def _tick_size_for(kotak_trading_symbol: str) -> float:
    """Live per-symbol tick size from Kotak's own scrip master, falling
    back to the previous blanket 0.05 default (still correct for most NSE
    cash equities) on any lookup failure or miss - never blocks an SL/
    target placement just because this lookup itself failed.

    Root cause found live 2026-09-22 (ENRIN.NS/ENRIN-EQ, "SIEMENS ENERGY
    INDIA LTD"): _round_to_tick's own 0.05-covers-everything assumption
    (see its docstring) is FALSE for this symbol - a real GET
    /kotak-neo/search-scrip?symbol=ENRIN&exchange_segment=nse_cm call
    returned dTickSize=10 with lPrecision=2, i.e. a REAL tick of Rs 0.10,
    not 0.05 (confirmed against this same payload's dHighPriceRange/
    dLowPriceRange fields, which are 100x-scaled and match the human-
    readable pCreditRating "2571.80-3857.60" range exactly - same
    lPrecision=2 scaling convention). Every SL placement attempt for this
    symbol was rejected ("16283: Order price is not a multiple of tick
    size"), leaving the position naked until the 60s protection-degraded
    timeout force-closed it (see main.py's _maybe_sync_real_stop_loss).
    ENRIN's own surveillanceMessage ("PE greater than 50 for previous 4
    trailing quarters") suggests this is an ASM/surveillance-linked wider
    tick, not a one-off data error - i.e. other watchlist symbols could
    hit the exact same rejection.

    Cached _TICK_SIZE_CACHE_TTL_SECONDS per kotak_trading_symbol - this is
    called on every real SL/target placement, so an uncached lookup on
    every one of those would mean an extra live Kotak call in a path that
    already needs to move fast to avoid a naked window."""
    cached = _tick_size_cache.get(kotak_trading_symbol)
    if cached is not None and time.time() - cached["fetched_at"] < _TICK_SIZE_CACHE_TTL_SECONDS:
        return cached["value"]
    try:
        bare_symbol = kotak_trading_symbol.split("-")[0]
        matches = kotak_neo.search_scrip(exchange_segment="nse_cm", symbol=bare_symbol)
        if not isinstance(matches, list):
            return 0.05
        row = next((r for r in matches if r.get("pTrdSymbol") == kotak_trading_symbol), None)
        if row is None:
            return 0.05
        precision = int(row.get("lPrecision") or 2)
        tick = float(row["dTickSize"]) / (10 ** precision)
        if tick <= 0:
            return 0.05
    except Exception:
        return 0.05
    _tick_size_cache[kotak_trading_symbol] = {"value": tick, "fetched_at": time.time()}
    return tick


@_records_send("sl", "resting SELL stop-loss to protect an open long/swing position")
def _place_real_stop_loss_once(kotak_trading_symbol: str, qty: int, trigger_price: float) -> dict:
    """Places a REAL resting stop-loss sell order at Kotak for an already-
    open real position, so the stop fires at the exchange even if this app
    or Render's process is down between scheduler ticks. See this
    module's top docstring ("Real resting stop-loss orders" and "Real
    fill confirmation") for the order-type and rejection-confirmation
    reasoning - order_type="SL" (a limit order gated behind trigger_price),
    and a follow-up _confirm_order_status call so a rejection is never
    mistaken for a working resting stop.

    BUG found live 2026-09-08, within 30 minutes of the SL-M->SL fix
    shipping: `price` (the limit) was originally set 1% below
    trigger_price, rounded to 2 decimals - fine for AGL (tick size 0.01,
    where any 2-decimal value is automatically tick-aligned) but AGI
    (tick size 0.05) then had EVERY SL attempt rejected with "Order price
    is not a multiple of tick size" (e.g. round(753.80*0.99, 2) = 746.26,
    not a multiple of 0.05) - 14+ rejections over 25 minutes, zero real
    stop-loss protection the whole time. This function has no tick-size
    input to round against correctly. Fixed the only way that's safe
    without one: `price = trigger_price` exactly, no discount - every
    trigger_price value tried on this account so far (both AGI and AGL,
    20+ attempts) has passed Kotak's tick validation without ever being
    rejected for it, since it's the SAME price the paper engine's own
    stop_loss level already computed from real candle closes. The
    tradeoff: a limit order with zero buffer below trigger can miss a
    fast/gapping decline (the classic SL-vs-SL-M risk) - but that risk is
    strictly better than this account's ONLY compliant order type
    (SL-M is blocked outright by the algo-tag rule - see the module's own
    top docstring) being rejected on tick-size and leaving the position
    with NO resting stop at all, which is what every AGI attempt has
    actually been doing since the 1%-discount version shipped."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    trigger_price = _round_to_tick(trigger_price, _tick_size_for(kotak_trading_symbol))
    limit_price = trigger_price
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
        found = _adopt_sl_after_lost_ack(kotak_trading_symbol, trigger_price)
        if found:
            found["detail"] = f"place_order raised: {e}; adopted the SL Kotak placed anyway"
            return found
        return {"ok": False, "detail": f"place_order raised: {e}"}

    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        found = _adopt_sl_after_lost_ack(kotak_trading_symbol, trigger_price)
        if found:
            found["raw_response"] = resp
            return found
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}

    status = _confirm_order_status(order_id)
    # B-302 (2026-10-07): Kotak's RMS can reject an acked SL a moment AFTER the
    # first order_report (live: RVNL/DRREDDY at 4:30 AM IST were logged "sl placed"
    # while Kotak showed them rejected). Re-read until the order is in a known
    # resting/final state; an unknown/transient state is never treated as resting.
    for _ in range(3):
        if status["status"] in ("rejected", "trigger pending", "open", "complete"):
            break
        time.sleep(1.5)
        status = _confirm_order_status(order_id)
    if status["status"] == "rejected":
        return _rejected_result(order_id, status, resp)

    return {"ok": True, "order_id": str(order_id), "raw_response": resp,
            "trigger_price": trigger_price, "limit_price": limit_price,
            "status_confirmed": status["status"] in ("trigger pending", "open", "complete")}



_LOST_ACK_RECHECKS = (2.0, 5.0, 10.0)


def _adopt_sl_after_lost_ack(kotak_trading_symbol: str, trigger_price: float):
    """B-1338 (WIPRO 2026-10-22 09:16 IST, live): place_order timed out after 30 s, the
    app logged "sl failed", yet Kotak had placed the SL (trigger pending). A lost ack is
    not a failed order. Re-read the order book a few times and, if a live SELL SL rests
    on this symbol at this trigger, return it as placed, so no caller re-sends a
    duplicate stop. Returns None when no such order shows up."""
    for wait in _LOST_ACK_RECHECKS:
        time.sleep(wait)
        try:
            rows = kotak_neo.login().order_report().get("data") or []
        except Exception:
            continue
        for row in rows:
            if row.get("trdSym") != kotak_trading_symbol or row.get("trnsTp") != "S":
                continue
            if str(row.get("prcTp", "")).upper() not in ("SL", "SL-M"):
                continue
            if str(row.get("ordSt", "")).lower() in _TERMINAL_ORDER_STATUSES:
                continue
            try:
                trg = float(row.get("trgPrc") or 0)
            except (TypeError, ValueError):
                continue
            if row.get("nOrdNo") and abs(trg - float(trigger_price)) <= 0.05:
                return {"ok": True, "order_id": str(row["nOrdNo"]), "raw_response": None,
                        "trigger_price": trg, "limit_price": trg, "status_confirmed": True,
                        "adopted_after_lost_ack": True}
    return None

_PRICE_BAND_PCTS = (0.10, 0.05, 0.02)


def _rejected_result(order_id, status, resp) -> dict:
    """B-1305: every Kotak-rejected order comes back with its reason classified, and an
    unrecognised reason is alarmed in the log rather than passing silently."""
    detail = f"order {order_id} rejected: {status['detail']}"
    kind = classify_rejection(detail)
    if kind == "unknown":
        print(f"[ALARM] Kotak rejected order {order_id} for an unrecognised reason: {status['detail']}")
    return {"ok": False, "detail": detail, "rejection_kind": kind, "rejected_order_id": str(order_id),
            "raw_response": resp, "status_check": status["row"]}


def classify_rejection(detail) -> str:
    """B-1305 (read the rejection reason, then change the next order): map a failed
    order's detail to what the next request may do. "transient" = Kotak never rejected
    it (login, network, no order id), so an identical resend is fine; "price_band" = move
    the price inside the band; "t1" / "cas" = the existing T1 and CAS paths; "margin" =
    do not resend, protect another way; "unknown" = alarm, never resend unchanged."""
    d = str(detail or "")
    low = d.lower()
    if " rejected" not in low:
        return "transient"
    if _is_price_range_rejection(d):
        return "price_band"
    if "T1 holdings" in d or "Trade-to-Trade" in d:
        return "t1"
    if is_cas_transition_rejection(d):
        return "cas"
    if "margin" in low or "insufficient" in low or "fund" in low:
        return "margin"
    return "unknown"


# B-1411: why a Kotak order this module sent ended up rejected/replaced, keyed by order id, so the reconcile's
# "order not in app log" pass logs the real reason instead of UNLOGGED. In-process only (a restart loses it,
# and the reconcile then falls back to the plain UNLOGGED row, which still carries Kotak's own rejRsn).
_ORDER_REASONS: dict = {}
_ORDER_REASONS_MAX = 2000  # B-1447: insertion-ordered cap (oldest dropped); the reconcile reads today's book only


def order_reason(order_id) -> "str | None":
    return _ORDER_REASONS.get(str(order_id)) if order_id else None


def _note_rejected(res: dict, reason: str) -> None:
    oid = res.get("rejected_order_id")
    if oid:
        _ORDER_REASONS[str(oid)] = reason
        while len(_ORDER_REASONS) > _ORDER_REASONS_MAX:
            _ORDER_REASONS.pop(next(iter(_ORDER_REASONS)), None)


_BAND_REF_CACHE: dict = {}  # trdSym -> (ts, prev_close, last)
_BAND_REF_TTL_S = 60.0


def _band_reference(kotak_trading_symbol: str):
    """(prev close, last) for the pre-send band check, cached 60 s per symbol so a burst of SL placements (09:15
    open) costs one lookup each. (None, None) when unknown: the stop is then sent unchanged, as before."""
    hit = _BAND_REF_CACHE.get(kotak_trading_symbol)
    if hit and time.time() - hit[0] < _BAND_REF_TTL_S:
        return hit[1], hit[2]
    prev, last = _reference_prices(kotak_trading_symbol)
    if prev and last:
        _BAND_REF_CACHE[kotak_trading_symbol] = (time.time(), prev, last)
    return prev, last


# B-1554 (live 2026-11-10 IST, UNIONBANK/BANKINDIA/BIOCON: ~800 identical SL sends each, all rejected "Circuit breach,
# Order Price :168.80, Low Price Range:177.30 High Price Range:216.70"): the B-1304/B-1411 band floor needs yfinance's
# prev close, and when that lookup failed on Render the same doomed price was resent every tick all day. Kotak's own
# rejection names the band, so (Kotak-first rule) parse it, cache it for the IST day, and rest the stop just inside it.
# Same "only ever tighten toward the market, stay 0.5% clear of LTP" rule as B-1304; unknown LTP -> unchanged.
import re as _re
_KOTAK_BAND_RE = _re.compile(r"Low Price Range\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*,?\s*High Price Range\s*:\s*([0-9]+(?:\.[0-9]+)?)", _re.I)
_KOTAK_BAND_CACHE: dict = {}  # trdSym -> (ist_date, low, high)


def _ist_date_str() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")


def _kotak_band(kotak_trading_symbol: str, detail=None):
    """(low, high) of today's price band from Kotak's own rejection text (cached for the IST day), or None."""
    m = _KOTAK_BAND_RE.search(str(detail or ""))
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if 0 < lo < hi:
            _KOTAK_BAND_CACHE[kotak_trading_symbol] = (_ist_date_str(), lo, hi)
            return lo, hi
    hit = _KOTAK_BAND_CACHE.get(kotak_trading_symbol)
    if hit and hit[0] == _ist_date_str():
        return hit[1], hit[2]
    return None


def _kotak_band_stop(kotak_trading_symbol: str, trigger_price: float, side: str, detail=None):
    """A stop inside Kotak's band that is still clear of the market, or None. Long: ceil-tick(low x 1.003), only if
    above the requested trigger and below 0.995 x LTP. Short: floor-tick(high x 0.997), only if below the requested
    trigger and above 1.005 x LTP."""
    import math
    band = _kotak_band(kotak_trading_symbol, detail)
    if not band:
        return None
    ltp = _fresh_ltp(kotak_trading_symbol)
    if ltp is None:
        return None
    lo, hi = band
    tick = _tick_size_for(kotak_trading_symbol) or 0.05
    req = float(trigger_price)
    if side == "long":
        cand = round(math.ceil(lo * 1.003 / tick - 1e-6) * tick, 2)
        return cand if req < cand < ltp * 0.995 else None
    cand = round(math.floor(hi * 0.997 / tick + 1e-6) * tick, 2)
    return cand if ltp * 1.005 < cand < req else None


def _preclamp_long_stop(kotak_trading_symbol: str, trigger_price: float):
    """B-1411 (live 2026-10-29 09:15 IST: BANKINDIA 115.72 and SUZLON 28.91 were sent, rejected as 'Circuit
    breach', and only then retried at the band floor): a SELL stop below the widest (10%) band floor is raised to
    that floor BEFORE the first send, so no doomed order reaches Kotak. Same floor and same 'stay under the market'
    rule as the B-1304 retry, which still handles the narrower 5%/2% bands. Returns (trigger, clamped_from|None)."""
    kb = _kotak_band_stop(kotak_trading_symbol, trigger_price, "long")  # B-1554: Kotak's band from an earlier rejection today
    if kb is not None:
        return kb, float(trigger_price)
    prev, last = _band_reference(kotak_trading_symbol)
    if not prev or not last:
        return trigger_price, None
    cand = _round_to_tick(prev * (1 - _PRICE_BAND_PCTS[0]) * 1.003, _tick_size_for(kotak_trading_symbol))
    if float(trigger_price) < cand < last * 0.995:
        return cand, float(trigger_price)
    return trigger_price, None


def _preclamp_short_stop(kotak_trading_symbol: str, trigger_price: float):
    """B-1411 short mirror: a BUY stop above the 10% upper band ceiling is lowered to it before the first send."""
    kb = _kotak_band_stop(kotak_trading_symbol, trigger_price, "short")  # B-1554
    if kb is not None:
        return kb, float(trigger_price)
    prev, last = _band_reference(kotak_trading_symbol)
    if not prev or not last:
        return trigger_price, None
    cand = _round_to_tick(prev * (1 + _PRICE_BAND_PCTS[0]) * 0.997, _tick_size_for(kotak_trading_symbol))
    if float(trigger_price) > cand > last * 1.005:
        return cand, float(trigger_price)
    return trigger_price, None


def _is_price_range_rejection(detail) -> bool:
    d = str(detail or "").lower()
    return "valid price range" in d or "circuit breach" in d


def _reference_prices(kotak_trading_symbol: str):
    """(previous close, last price) from yfinance, or (None, None). Only used after a
    price-band rejection, never on the normal path."""
    try:
        import yfinance as yf
        sym = kotak_trading_symbol.rsplit("-", 1)[0] + ".NS"
        fi = yf.Ticker(sym).fast_info
        return float(fi["previous_close"]), float(fi["last_price"])
    except Exception:
        return None, None


def stop_placeable_for_entry(kotak_trading_symbol: str, stop: float, ltp: float):
    """B-1308 (no trade without SL): before a real buy, confirm a stop can rest inside the
    day's price band. The stop rests as-is when it is within 10% of the previous close;
    otherwise place_real_stop_loss's B-1304 retry raises it to a band floor, which only
    works if that floor is still under the market (< 0.995 x ltp). When neither holds,
    (False, why) and the caller skips the entry. Unknown reference close -> (True, ...):
    the B-1304 retry and the 5-min backcheck still apply, and a yfinance hiccup must not
    block every entry."""
    prev, last = _reference_prices(kotak_trading_symbol)
    px = float(ltp or last or 0)
    if not prev or px <= 0:
        return True, "no reference close; band retry applies"
    stop = float(stop)
    if stop >= prev * (1 - _PRICE_BAND_PCTS[0]) * 1.003:
        return True, "stop inside the price band"
    tick = _tick_size_for(kotak_trading_symbol)
    for band in _PRICE_BAND_PCTS:
        cand = _round_to_tick(prev * (1 - band) * 1.003, tick)
        if stop < cand < px * 0.995:
            return True, f"stop {stop:.2f} will be raised to band floor {cand:.2f}"
    return False, (f"stop {stop:.2f} is below the price band (prev close {prev:.2f}) and no band "
                   f"floor fits under ltp {px:.2f}; Kotak would reject every SL")


# B-1440 (WIPRO 2026-11-02 09:15 IST: the 09:15 re-place after the exchange's 15:15 cancel rested at Rs179.01 - the
# stale stored stop Rs175.12 raised to the band floor - although View 4's entry-day SL was Rs185.35). Every real stop
# that leaves this module is floored here, at the last chokepoint, so no caller can rest a long stop below (or a short
# stop above) the position's entry-day stop. main.py registers the provider; fn(kotak_trading_symbol, side) -> float or
# None. Never loosens a stop: it only raises a long trigger / lowers a short one.
_STOP_FLOOR_PROVIDER = None
_FLOOR_BYPASS = threading.local()  # B-1367: set only around ensure_resting_sl's restore of a just-cancelled stop


def set_stop_floor_provider(fn) -> None:
    global _STOP_FLOOR_PROVIDER
    _STOP_FLOOR_PROVIDER = fn


def _entry_day_floor(kotak_trading_symbol: str, side: str):
    fn = _STOP_FLOOR_PROVIDER
    if fn is None:
        return None
    try:
        v = fn(kotak_trading_symbol, side)
        return float(v) if v and float(v) > 0 else None
    except Exception as e:  # noqa: BLE001 - a floor lookup must never block a protective order
        print(f"[REAL SL FLOOR] lookup failed for {kotak_trading_symbol} ({side}), stop sent as requested: {e}")
        return None


def apply_entry_day_floor(kotak_trading_symbol: str, trigger_price: float, side: str = "long"):
    """(trigger, info). Long: max(trigger, entry-day stop); short: min(trigger, entry-day stop). If the floor is
    already through the market (long floor >= 0.995 x last, short ceiling <= 1.005 x last) a resting stop there
    would fire or be refused, so protection is kept at the tightest still-placeable level between the requested
    trigger and the floor, and info['entry_floor_breached'] says so (the owner rule then closes the position:
    _swing_stop_breached_exit). info keys: entry_floor, entry_floor_raised_from, entry_floor_breached."""
    info: dict = {}
    floor = _entry_day_floor(kotak_trading_symbol, side)
    if floor is None:
        return trigger_price, info
    tick = _tick_size_for(kotak_trading_symbol)
    import math
    steps = floor / tick
    # tick-align TOWARD protection (long up, short down) so rounding never puts the stop under the floor
    floor = round((math.ceil(steps - 1e-6) if side == "long" else math.floor(steps + 1e-6)) * tick, 2)
    req = float(trigger_price)
    if (side == "long" and floor <= req + 1e-9) or (side == "short" and floor >= req - 1e-9):
        return trigger_price, info
    info["entry_floor"] = floor
    _prev, last = _band_reference(kotak_trading_symbol)
    if last and side == "long" and floor >= last * 0.995:
        best = max(req, _round_to_tick(last * 0.995, tick))
        best = best if best < last else req
        info["entry_floor_breached"] = floor
        print(f"[REAL SL FLOOR] LOUD: {kotak_trading_symbol} entry-day stop Rs{floor:.2f} is at/above the market "
              f"Rs{float(last):.2f}; resting at Rs{best:.2f} to keep protection (requested Rs{req:.2f})")
        if best > req:
            info["entry_floor_raised_from"] = req
        return best, info
    if last and side == "short" and floor <= last * 1.005:
        best = min(req, _round_to_tick(last * 1.005, tick))
        best = best if best > last else req
        info["entry_floor_breached"] = floor
        print(f"[REAL SL FLOOR] LOUD: {kotak_trading_symbol} entry-day buy-stop Rs{floor:.2f} is at/below the market "
              f"Rs{float(last):.2f}; resting at Rs{best:.2f} to keep protection (requested Rs{req:.2f})")
        if best < req:
            info["entry_floor_raised_from"] = req
        return best, info
    info["entry_floor_raised_from"] = req
    print(f"[REAL SL FLOOR] {kotak_trading_symbol} ({side}) stop Rs{req:.2f} is "
          f"{'below' if side == 'long' else 'above'} the entry-day stop; sent at Rs{floor:.2f}")
    return floor, info


# B-1520 (IOC 2026-11-09: no resting SL from the 09:15 IST open until 09:26:19 IST): a SELL stop must sit below the
# market (a BUY stop above it) or Kotak refuses it, often with no order id, so a trailed stop the open had already gone
# through was re-sent and refused for 11 minutes while nothing rested. Every stop is therefore checked against a FRESH
# live price (main.py registers the provider: today's tick, seconds old; None = unknown -> previous behaviour). A stop
# at/through the market rests at the tightest placeable level (long 0.995 x LTP, short 1.005 x LTP, the same margin
# apply_entry_day_floor uses) so the holding is never naked, and result['stop_through_market'] tells the caller the
# strategy stop is already hit (the swing callers then exit at market, as the replay fills at the open).
_LTP_PROVIDER = None


def set_ltp_provider(fn) -> None:
    global _LTP_PROVIDER
    _LTP_PROVIDER = fn


def _fresh_ltp(kotak_trading_symbol: str):
    fn = _LTP_PROVIDER
    if fn is None:
        return None
    try:
        v = fn(kotak_trading_symbol)
        return float(v) if v and float(v) > 0 else None
    except Exception:  # noqa: BLE001 - a price lookup must never block a protective order
        return None


def clamp_stop_to_market(kotak_trading_symbol: str, trigger_price: float, side: str = "long"):
    """(trigger, info). Long: a trigger at/above LTP - 1 tick rests at the tick below 0.995 x LTP; short: a trigger
    at/below LTP + 1 tick rests at the tick above 1.005 x LTP. info: stop_through_market (the requested trigger),
    ltp. Unknown LTP -> unchanged. Never moves a stop that is already placeable."""
    info: dict = {}
    ltp = _fresh_ltp(kotak_trading_symbol)
    if ltp is None:
        return trigger_price, info
    tick = _tick_size_for(kotak_trading_symbol) or 0.05
    import math
    req = float(trigger_price)
    if side == "long":
        if req < ltp - tick + 1e-9:
            return trigger_price, info
        best = round(math.floor(min(ltp * 0.995, ltp - tick) / tick + 1e-6) * tick, 2)
        if best <= 0:
            return trigger_price, info
    else:
        if req > ltp + tick - 1e-9:
            return trigger_price, info
        best = round(math.ceil(max(ltp * 1.005, ltp + tick) / tick - 1e-6) * tick, 2)
    info.update(stop_through_market=req, ltp=ltp)
    print(f"[REAL SL MARKET] LOUD: {kotak_trading_symbol} ({side}) stop Rs{req:.2f} is through the market "
          f"(LTP Rs{ltp:.2f}); resting at Rs{best:.2f} so the position is protected - caller exits at market")
    return best, info


_SL_SYMBOL_LOCKS: dict = {}
_SL_SYMBOL_LOCKS_GUARD = threading.Lock()
_RECENT_SL_PLACED: dict = {}  # trdSym -> {"order_id", "trigger", "qty", "ts"}
_RECENT_SL_WINDOW_S = 20.0


def _sl_symbol_lock(kotak_trading_symbol: str) -> "threading.RLock":
    """B-1379 (live 2026-10-27 09:15 IST): two protect paths placed a SELL SL for the same holding within 1 s (WIPRO
    14237/14353, COALINDIA, GSEC5IETF), each having scanned an order book that did not yet show the other's order, so
    Kotak RMS rejected the extras ("T1 holdings ... Used:4, Available:2"). One lock per symbol makes scan-then-act
    atomic inside this process."""
    with _SL_SYMBOL_LOCKS_GUARD:
        return _SL_SYMBOL_LOCKS.setdefault(kotak_trading_symbol, threading.RLock())


def _before_equity_open() -> bool:
    """B-1380: before 09:15 IST NSE cash takes no SL order (pre-open is limit-only), so Kotak rejects every one with
    '16387: Security is not allowed to trade in this market' (17 rejects 07:37-08:55 IST on 2026-10-27)."""
    import datetime as _dt
    n = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    return n.hour * 60 + n.minute < 9 * 60 + 15


def place_real_stop_loss(kotak_trading_symbol: str, qty: int, trigger_price: float) -> dict:
    if _before_equity_open():
        # Same failure shape as a Kotak reject, so callers behave exactly as before, minus the doomed order.
        return {"ok": False, "order_id": None, "trigger_price": trigger_price, "action": "skipped_pre_open",
                "detail": "B-1380: no SL before 09:15 IST (exchange rejects it)", "raw_response": None}
    with _sl_symbol_lock(kotak_trading_symbol):
        res = _place_real_stop_loss_unlocked(kotak_trading_symbol, qty, trigger_price)
        if res.get("ok") and res.get("order_id"):
            _RECENT_SL_PLACED[kotak_trading_symbol] = {"order_id": str(res["order_id"]), "qty": int(qty),
                                                       "trigger": float(res.get("trigger_price") or trigger_price),
                                                       "ts": time.time()}
        return res


def _place_real_stop_loss_unlocked(kotak_trading_symbol: str, qty: int, trigger_price: float) -> dict:
    """B-1304 (UNIONBANK 2026-10-21 09:16 IST, live): an SL whose trigger sat below the
    day's lower price band (159.67 vs a ~162.6 floor after a gap up) was rejected with
    "Order price is outside the valid price range" and the position stayed naked. On that
    rejection only, retry at the tightest-band floor that is still below the market
    (prev close x (1 - band) x 1.003, bands 10/5/2%), so a stop rests instead of nothing.
    The stop is only ever raised toward the market, never above 0.5% under last price."""
    if getattr(_FLOOR_BYPASS, "on", False):  # B-1367: ensure_resting_sl's restore of the just-cancelled stop only
        floor_info = {}
    else:
        trigger_price, floor_info = apply_entry_day_floor(kotak_trading_symbol, trigger_price, "long")  # B-1440
    trigger_price, clamped_from = _preclamp_long_stop(kotak_trading_symbol, trigger_price)  # only ever raises
    trigger_price, market_info = clamp_stop_to_market(kotak_trading_symbol, trigger_price, "long")  # B-1520
    floor_info = {**floor_info, **market_info}
    res = _place_real_stop_loss_once(kotak_trading_symbol, qty, trigger_price)
    res.update(floor_info)
    if clamped_from is not None:
        res["band_clamped_from"] = clamped_from
    if res.get("ok") or not _is_price_range_rejection(res.get("detail")):
        return res
    _note_rejected(res, f"stop Rs{float(trigger_price):.2f} was outside the day's price band; retried at the next band floor (B-1304)")
    kb = _kotak_band_stop(kotak_trading_symbol, trigger_price, "long", res.get("detail"))  # B-1554
    if kb is not None:
        r2 = _place_real_stop_loss_once(kotak_trading_symbol, qty, kb)
        if r2.get("ok"):
            r2["band_clamped_from"] = clamped_from if clamped_from is not None else trigger_price
            r2["band_source"] = "kotak_rejection"
            return r2
        _note_rejected(r2, f"stop Rs{kb:.2f} inside Kotak's stated band was still rejected (B-1554)")
        res = r2
        if not _is_price_range_rejection(r2.get("detail")):
            return res
    prev, last = _reference_prices(kotak_trading_symbol)
    if not prev or not last:
        return res
    tick = _tick_size_for(kotak_trading_symbol)
    tried = {round(float(trigger_price), 2)}
    for band in _PRICE_BAND_PCTS:
        cand = _round_to_tick(prev * (1 - band) * 1.003, tick)
        if cand <= trigger_price or cand in tried or cand >= last * 0.995:
            continue
        tried.add(cand)
        r2 = _place_real_stop_loss_once(kotak_trading_symbol, qty, cand)
        if r2.get("ok"):
            r2["band_clamped_from"] = clamped_from if clamped_from is not None else trigger_price
            return r2
        _note_rejected(r2, f"band-floor stop Rs{cand:.2f} was still outside the day's price band; tried the next band")
        res = r2
        if not _is_price_range_rejection(r2.get("detail")):
            break
    return res


def _in_closing_session() -> bool:
    import datetime as _dt
    n = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    return n.hour * 60 + n.minute >= 15 * 60 + 15


def cancel_converted_stop_orders(kotak_trading_symbol: str, stale_trigger: float) -> list:
    """DABUR 2026-10-08: an SL whose trigger sits at/above the market is converted by
    Kotak into a plain resting LIMIT SELL (order book prcTp "L"), which then looks like
    a target and, because it reserves the shares, makes RMS reject the real SL. Cancel
    only live SELL orders on this symbol that are NOT SL/SL-M and are priced at the stale
    stop level (+-0.05), so a manual order at any other price is never touched. Fresh
    order_report each call; returns the cancelled order ids."""
    done = []
    try:
        rows = kotak_neo.login().order_report().get("data") or []
    except Exception:
        return done
    for row in rows:
        if row.get("trdSym") != kotak_trading_symbol or row.get("trnsTp") != "S":
            continue
        if str(row.get("prcTp", "")).upper() in ("SL", "SL-M"):
            continue
        if str(row.get("ordSt", "")).lower() in _TERMINAL_ORDER_STATUSES:
            continue
        try:
            if abs(float(row.get("prc") or 0) - float(stale_trigger)) > 0.05:
                continue
        except (TypeError, ValueError):
            continue
        oid = row.get("nOrdNo")
        if oid and cancel_real_order(str(oid)).get("ok"):
            done.append(str(oid))
    return done


def ensure_resting_sl(kotak_trading_symbol: str, qty: int, trigger_price: float, allow_unchecked: bool = True) -> dict:
    with _sl_symbol_lock(kotak_trading_symbol):
        return _ensure_resting_sl_unlocked(kotak_trading_symbol, qty, trigger_price, allow_unchecked)


ORDER_BOOK_READ_RETRY_DELAYS_S = (0.5, 1.5)  # B-1462: a failed order-book read is retried before any fallback


_EMPTY_BOOK_MARKERS = ("no data", "no order", "no record", "not found", "no trade")


def order_rows_from_report(report):
    """B-1481 (live 2026-11-05 09:15-09:17 IST: every overnight holding stayed without an SL for ~2 min because the
    first read of the day returned no `data` list - Kotak's reply for a day with no orders yet - and B-1462 treated
    that as 'unreadable, place nothing'). Returns the row list, [] for Kotak's empty-book reply (no `data` key plus
    a 'no data'-style message or stCode 5203), or None when the reply is genuinely unreadable."""
    if not isinstance(report, dict):
        return None
    rows = report.get("data")
    if isinstance(rows, list):
        return rows
    if rows is None:
        msg = " ".join(str(report.get(k) or "") for k in ("errMsg", "emsg", "message", "msg", "stat", "error")).lower()
        if str(report.get("stCode")) == "5203" or any(m in msg for m in _EMPTY_BOOK_MARKERS):
            return []
    return None


def _read_order_rows_with_retry(sleep=None):
    import time as _t
    sleep = sleep or _t.sleep
    last = None
    for delay in (0.0,) + ORDER_BOOK_READ_RETRY_DELAYS_S:
        if delay:
            sleep(delay)
        try:
            report = kotak_neo.login().order_report()
            rows = order_rows_from_report(report)
            if isinstance(rows, list):
                return rows, None
            last = ValueError(f"order_report returned no data list: {str(report)[:160]}")
        except Exception as e:  # noqa: BLE001
            last = e
    return None, last


def _ensure_resting_sl_unlocked(kotak_trading_symbol: str, qty: int, trigger_price: float,
                                allow_unchecked: bool = True) -> dict:
    """Scan-then-act SL placement for LONG (swing) positions (2026-10-07, explicit
    user instruction after live rejects: "before placing any new order request you
    need to scan existing order list, then either place new, or cancel current plus
    place new"). Kotak's RMS rejects a second SELL SL for shares already reserved by
    a resting SL ("T1 holdings ... Used:2, Available:1" on a 1-share position), so a
    blind place-new-then-cancel-old can never ratchet, and a blind retry duplicates.
    Fresh Kotak order_report every call (never a cached local id):
      * a live SELL SL covering `qty` at a trigger >= the requested one -> ADOPT it,
        place nothing (a stop is never lowered here);
      * a live SL below the requested trigger (ratchet up) or covering too few shares ->
        cancel every live SL on the symbol, then place the new one; if that placement
        fails, immediately re-place the old trigger so the position is not left naked;
      * none live -> place fresh.
    If the order book itself cannot be read, falls back to a plain place (the old
    behaviour; a duplicate is rejected harmlessly by RMS). Returns place_real_stop_loss's
    shape plus `action` in {adopted_existing, replaced, placed, placed_unchecked,
    replace_failed}; on replace_failed `restored_order_id`/`restored_trigger` describe
    the re-placed old stop when that worked."""
    rows, e = _read_order_rows_with_retry()
    if rows is None:
        if not allow_unchecked:  # B-1462: a periodic re-check never places blind over a possibly-live SL
            return {"ok": False, "order_id": None, "action": "skipped_unreadable_book",
                    "detail": f"Kotak order book unreadable after retries ({e}); nothing placed, next pass retries",
                    "raw_response": None}
        if _in_closing_session():  # B-1444: Kotak rejects SL/SL-M in the CAS session
            return {"ok": False, "order_id": None, "action": "skipped_closing_session",
                    "detail": "no SL placement after 15:15 IST", "raw_response": None}
        res = place_real_stop_loss(kotak_trading_symbol, qty, trigger_price)
        res["action"] = "placed_unchecked"
        res["scan_error"] = str(e)
        return res

    live = []
    for row in rows:
        if row.get("trdSym") != kotak_trading_symbol or row.get("trnsTp") != "S":
            continue
        if str(row.get("prcTp", "")).upper() not in ("SL", "SL-M"):
            continue
        if str(row.get("ordSt", "")).lower() in _TERMINAL_ORDER_STATUSES:
            continue
        oid = row.get("nOrdNo")
        if not oid:
            continue
        try:
            trg = float(row.get("trgPrc") or 0)
            q = int(float(row.get("qty") or 0))
        except (TypeError, ValueError):
            continue
        live.append({"order_id": str(oid), "trigger": trg, "qty": q})

    # B-1379: an SL this process placed seconds ago may not be in the order book yet; count it as live so a second
    # caller adopts or replaces it instead of placing a duplicate that RMS rejects.
    recent = _RECENT_SL_PLACED.get(kotak_trading_symbol)
    if (recent and time.time() - recent["ts"] < _RECENT_SL_WINDOW_S
            and not any(str(r.get("nOrdNo")) == recent["order_id"] for r in rows)):
        live.append({"order_id": recent["order_id"], "trigger": recent["trigger"], "qty": recent["qty"]})

    # B-1440: compare live SLs against the FLOORED stop, so a live SL under the entry-day stop is ratcheted up, never
    # adopted as-is.
    trigger_price, _floor_info = apply_entry_day_floor(kotak_trading_symbol, trigger_price, "long")
    # B-1520: compare against the level that can actually rest (a stop through the market rests just under it), so a
    # live SL already at that level is adopted instead of being cancelled and re-placed every pass.
    trigger_price, _mk_info = clamp_stop_to_market(kotak_trading_symbol, trigger_price, "long")
    desired = _round_to_tick(trigger_price, _tick_size_for(kotak_trading_symbol))
    res = _ensure_resting_sl_decide(kotak_trading_symbol, qty, trigger_price, desired, live)
    if _mk_info:
        res.update(_mk_info)
    return res


def _ensure_resting_sl_decide(kotak_trading_symbol: str, qty: int, trigger_price: float, desired: float,
                              live: list) -> dict:
    if live:
        best = max(live, key=lambda o: o["trigger"])
        if best["trigger"] >= desired - 0.005 and sum(o["qty"] for o in live) >= qty:
            return {"ok": True, "order_id": best["order_id"], "trigger_price": best["trigger"],
                    "action": "adopted_existing", "raw_response": None}
        if _in_closing_session():
            # 15:15 IST+: Kotak/NSE reject new cash SLs, so cancelling the live one here
            # would leave the position naked (B-308). Keep what rests; retry next session.
            return {"ok": False, "order_id": best["order_id"], "trigger_price": best["trigger"],
                    "action": "skipped_closing_session", "detail": "no SL replace after 15:15 IST",
                    "raw_response": None}
        for o in live:
            cancel_real_order(o["order_id"])
        res = place_real_stop_loss(kotak_trading_symbol, qty, desired)
        if res.get("ok"):
            res["action"] = "replaced"
            res["cancelled"] = [o["order_id"] for o in live]
            return res
        # B-1367: the restore re-places the EXACT stop that was just cancelled (a lower stop beats no stop). Flooring
        # it to the very level Kotak just refused would leave the position naked, so the floor is bypassed here only.
        _FLOOR_BYPASS.on = True
        try:
            restore = place_real_stop_loss(kotak_trading_symbol, qty, best["trigger"])
        finally:
            _FLOOR_BYPASS.on = False
        res["action"] = "replace_failed"
        if restore.get("ok"):
            res["restored_order_id"] = restore["order_id"]
            res["restored_trigger"] = restore["trigger_price"]
        return res

    if _in_closing_session():
        # B-1444 (IOC 2 Nov 2026, 6 rejects 15:22-15:31 IST "SL AND SL-M ORDERS NOT ALLOWED IN CAS SESSION"): after the
        # exchange's 15:15 cancel a fresh SL is rejected too; the 09:15 IST protect pass re-places it.
        return {"ok": False, "order_id": None, "action": "skipped_closing_session",
                "detail": "no SL placement after 15:15 IST", "raw_response": None}
    res = place_real_stop_loss(kotak_trading_symbol, qty, trigger_price)
    res["action"] = "placed"
    return res


def place_real_short_stop_loss(kotak_trading_symbol: str, qty: int, trigger_price: float, product: str = "MIS") -> dict:
    """B-1305: short mirror of B-1304's band retry. A buy-stop above the day's upper
    price band is rejected ("outside the valid price range" / "circuit breach") and the
    short stays naked. On that rejection only, retry at the tightest upper-band ceiling
    still above the market (prev close x (1 + band) x 0.997, bands 10/5/2%). The stop is
    only ever lowered toward the market, never below 0.5% over last price."""
    trigger_price, floor_info = apply_entry_day_floor(kotak_trading_symbol, trigger_price, "short")  # B-1440
    trigger_price, clamped_from = _preclamp_short_stop(kotak_trading_symbol, trigger_price)  # only ever lowers
    trigger_price, market_info = clamp_stop_to_market(kotak_trading_symbol, trigger_price, "short")  # B-1520
    floor_info = {**floor_info, **market_info}
    res = _place_real_short_stop_loss_once(kotak_trading_symbol, qty, trigger_price, product)
    res.update(floor_info)
    if clamped_from is not None:
        res["band_clamped_from"] = clamped_from
    if res.get("ok") or not _is_price_range_rejection(res.get("detail")):
        return res
    _note_rejected(res, f"buy-stop Rs{float(trigger_price):.2f} was outside the day's price band; retried at the next band ceiling (B-1305)")
    kb = _kotak_band_stop(kotak_trading_symbol, trigger_price, "short", res.get("detail"))  # B-1554
    if kb is not None:
        r2 = _place_real_short_stop_loss_once(kotak_trading_symbol, qty, kb, product)
        if r2.get("ok"):
            r2["band_clamped_from"] = clamped_from if clamped_from is not None else trigger_price
            r2["band_source"] = "kotak_rejection"
            return r2
        _note_rejected(r2, f"buy-stop Rs{kb:.2f} inside Kotak's stated band was still rejected (B-1554)")
        res = r2
        if not _is_price_range_rejection(r2.get("detail")):
            return res
    prev, last = _reference_prices(kotak_trading_symbol)
    if not prev or not last:
        return res
    tick = _tick_size_for(kotak_trading_symbol)
    tried = {round(float(trigger_price), 2)}
    for band in _PRICE_BAND_PCTS:
        cand = _round_to_tick(prev * (1 + band) * 0.997, tick)
        if cand >= trigger_price or cand in tried or cand <= last * 1.005:
            continue
        tried.add(cand)
        r2 = _place_real_short_stop_loss_once(kotak_trading_symbol, qty, cand, product)
        if r2.get("ok"):
            r2["band_clamped_from"] = clamped_from if clamped_from is not None else trigger_price
            return r2
        _note_rejected(r2, f"band-ceiling buy-stop Rs{cand:.2f} was still outside the day's price band; tried the next band")
        res = r2
        if not _is_price_range_rejection(r2.get("detail")):
            break
    return res


@_records_send("short_sl", "resting BUY stop-loss to protect an open short position")
def _place_real_short_stop_loss_once(kotak_trading_symbol: str, qty: int, trigger_price: float, product: str = "MIS") -> dict:
    """Short mirror of place_real_stop_loss (2026-09-29) - a resting
    BUY-stop (transaction_type="B") that triggers ABOVE the short's entry
    price, to cover the position if it moves against it. Same order_type
    "SL" (limit gated behind trigger_price), same zero-buffer
    price=trigger_price choice as the long side (see place_real_stop_loss's
    own docstring for why: no tick-size input to discount against safely,
    and this exact price already passed the paper engine's own tick-
    aligned stop-loss computation)."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    trigger_price = _round_to_tick(trigger_price, _tick_size_for(kotak_trading_symbol))
    limit_price = trigger_price
    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product=product,
            price=str(limit_price),
            order_type="SL",
            quantity=str(qty),
            validity="DAY",
            trading_symbol=kotak_trading_symbol,
            transaction_type="B",
            trigger_price=str(trigger_price),
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}

    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}

    status = _confirm_order_status(order_id)
    if status["status"] == "rejected":
        return _rejected_result(order_id, status, resp)

    return {"ok": True, "order_id": str(order_id), "raw_response": resp,
            "trigger_price": trigger_price, "limit_price": limit_price}


@_records_send("target", "resting LIMIT SELL profit target")
def place_real_target(kotak_trading_symbol: str, qty: int, target_price: float) -> dict:
    """Places a REAL resting LIMIT sell order at Kotak for an already-open
    real position, at the paper engine's own profit target, so a
    favorable price move gets sold and booked at the exchange itself even
    if this app's process is down or hasn't yet reached the tick that
    would notice. See this module's top docstring ("Real resting target
    (profit-booking) orders") for the full reasoning.

    order_type="L" (a plain limit sell, no trigger_price) - not a stop
    order, so none of place_real_stop_loss's algo-tag MARKET-order
    concerns apply here. Same never-raises / rejection-confirmed
    discipline as every other function in this module."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    target_price = _round_to_tick(target_price, _tick_size_for(kotak_trading_symbol))
    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product="CNC",
            price=str(target_price),
            order_type="L",
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
        return _rejected_result(order_id, status, resp)

    return {"ok": True, "order_id": str(order_id), "raw_response": resp, "target_price": target_price}


@_records_send("short_target", "resting LIMIT BUY profit target for a short")
def place_real_short_target(kotak_trading_symbol: str, qty: int, target_price: float) -> dict:
    """Short mirror of place_real_target (2026-09-29) - a resting LIMIT
    BUY order at the short's profit target (BELOW entry price), to cover
    and book the gain at the exchange itself. order_type="L", no
    trigger_price, same as the long side - a plain limit order, not a
    stop, so none of the SL algo-tag concerns apply here either."""
    try:
        client = kotak_neo.login()
    except Exception as e:
        return {"ok": False, "detail": f"login failed: {e}"}

    target_price = _round_to_tick(target_price, _tick_size_for(kotak_trading_symbol))
    try:
        resp = client.place_order(
            exchange_segment="nse_cm",
            product="MIS",
            price=str(target_price),
            order_type="L",
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
        return _rejected_result(order_id, status, resp)

    return {"ok": True, "order_id": str(order_id), "raw_response": resp, "target_price": target_price}


@_records_send("cancel", "cancel of a resting order")
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
