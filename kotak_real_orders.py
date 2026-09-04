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
NOT be verified from a live account (this account has never placed a
real order before this module existed, so trade_report()/order_report()
have no real rows yet to inspect their field names from) is the exact
success/failure response shape of place_order() itself; for that,
Kotak's own published GitHub docs/samples (Kotak-Neo/kotak-neo-api,
corroborated via two independent search results 2026-09-04) show a real
sample success response containing "nOrdNo" (e.g. "220621000000097")
alongside "stat":"Ok"/"stCode":200. This module recognizes success ONLY
by a non-empty "nOrdNo" in the response - the single most positively-
confirmable signal (an order number was actually assigned) - and treats
everything else (no nOrdNo, an "error"/"Error" key, a non-dict response,
a raised exception) as failed/uncertain. It NEVER assumes success from
absence of an error, only from presence of a real order id. This is a
deliberately conservative reading given the unverifiable failure-shape:
erring toward "did not place" is the safe direction for real money.

Because of that same unverified-failure-shape gap, this module does NOT
attempt to parse Kotak's trade_report()/order_report() for the daily
spend cap either (their per-trade field names are equally unverified
with zero real rows to check against). Instead, main.py tracks the daily
Rs 500 cap from its OWN real_trades SQLite table, populated by the
caller using the qty (always 1, fixed in this first version) and the
live, verified real-time LTP already sourced from kotak_live_feed.py
(itself built and confirmed against real ticks earlier this session) -
data this codebase already fully controls and trusts, sidestepping the
need to trust an unverified external response shape for risk-cap
enforcement.

CNC (cash, no leverage) is used for both entry and exit - never
MIS/NRML/MTF - so the real cash-equity notional actually spent is
exactly quantity * price with no margin multiplier, keeping the Rs 500
cap meaningful in the currency it was set in (real rupees), not a
margin-inflated exposure.
"""
import kotak_neo


def place_real_entry(kotak_trading_symbol: str, ltp: float) -> dict:
    """Places a REAL market BUY for exactly 1 share via Kotak Neo, CNC,
    on nse_cm. Never raises - every failure path (login failure, an
    exception from place_order itself, an unrecognized response) returns
    {"ok": False, "detail": ...} instead, so a Kotak-side hiccup can
    never propagate out of this module and disturb the caller's own
    scheduler tick (paper trading included).

    kotak_trading_symbol must be Kotak's own real trading-symbol string
    (e.g. "RELIANCE-EQ") - sourced from kotak_live_feed's already-
    resolved, already-verified real instrument tokens, never guessed or
    derived from the Yahoo ticker.
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
            quantity="1",
            validity="DAY",
            trading_symbol=kotak_trading_symbol,
            transaction_type="B",
        )
    except Exception as e:
        return {"ok": False, "detail": f"place_order raised: {e}"}

    order_id = resp.get("nOrdNo") if isinstance(resp, dict) else None
    if not order_id:
        return {"ok": False, "detail": f"no order id in response: {resp}", "raw_response": resp}
    return {"ok": True, "order_id": str(order_id), "raw_response": resp, "qty": 1, "est_price": ltp}


def place_real_exit(kotak_trading_symbol: str, qty: int) -> dict:
    """Places a REAL market SELL to close a real position, CNC, on
    nse_cm. Same never-raises / nOrdNo-confirms-success discipline as
    place_real_entry - see its docstring.

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
    return {"ok": True, "order_id": str(order_id), "raw_response": resp, "qty": qty}
