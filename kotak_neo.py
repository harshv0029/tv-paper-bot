"""
Kotak Neo TradeAPI - auth + read-only account/market data.

Explicit user instruction (2026-09-03): connect a real Kotak Neo account.
This module is deliberately isolated from main.py's trading engine for
order placement - nothing here places, modifies, or cancels any order,
and nothing in main.py's scheduler/entry/exit logic imports or calls
anything here for that purpose. get_scheduler_capital_inr() (main.py)
DOES use limits() here for real position sizing (2026-09-04) - see
docs/TRADING_CONSTRAINTS.md "Kotak Neo connection" for the full phased
plan (Phase 1 auth, Phase 2 account data, Phase 2.5 market-data search;
Phase 3 real order placement remains unbuilt, needs its own go-ahead).

Runs on kotakneoapi==3.0.1 (2026-09-04, migrated from the legacy
git-installed neo-api-client==2.0.2 - see requirements.txt comment and
docs/TRADING_CONSTRAINTS.md for what changed). Same Python import name
(neo_api_client), same method signatures and error shapes for every
function this module calls - verified against the new SDK's actual
source before migrating, not assumed from its docs.

Credentials are read from env vars (Render's Environment tab), never
committed to the repo, never logged, never returned by any endpoint:
  KOTAK_NEO_CONSUMER_KEY  - the "default application" token from the
                            Kotak Neo app/web -> Invest tab -> Trade API
                            card (confirmed via Kotak's own actively-
                            maintained SDK - consumer_key is the ONLY
                            credential the login flow needs; an older
                            support article mentions a separate
                            "Consumer Secret" via a WSO2 portal - that's
                            a legacy flow, not what this SDK's real,
                            current __init__ accepts).
  KOTAK_NEO_MOBILE_NUMBER - registered mobile number, with country code.
  KOTAK_NEO_UCC           - Unique Client Code (Neo app -> Profile).
  KOTAK_NEO_MPIN          - the account's MPIN.
  KOTAK_NEO_TOTP_SEED     - the TOTP secret from registration (the same
                            seed value an authenticator app is seeded
                            with) - needed so this runs unattended
                            without a human retyping a 6-digit code
                            every 30 seconds.
"""
import os

import pyotp
from neo_api_client import NeoAPI

REQUIRED_ENV_VARS = [
    "KOTAK_NEO_CONSUMER_KEY",
    "KOTAK_NEO_MOBILE_NUMBER",
    "KOTAK_NEO_UCC",
    "KOTAK_NEO_MPIN",
    "KOTAK_NEO_TOTP_SEED",
]


def missing_credentials() -> list[str]:
    """Which required env vars aren't set yet - never returns their values,
    just which names are absent, so a caller can report what's missing
    without risking a leak."""
    return [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]


def _current_totp_code() -> str:
    seed = os.environ["KOTAK_NEO_TOTP_SEED"]
    return pyotp.TOTP(seed).now()


def login():
    """Logs in to the REAL Kotak Neo account (environment='prod') and
    returns an authenticated NeoAPI client. Raises RuntimeError with a
    caller-safe message (no credential values) if anything's missing or
    the login itself fails - never leaves partial credentials in the
    exception text.

    This function is auth-only - it does not place any order. Nothing
    calls it automatically; it's invoked by /kotak-neo/test-login
    (main.py) as a manual, deliberate smoke test."""
    missing = missing_credentials()
    if missing:
        raise RuntimeError(f"Kotak Neo not configured - missing env var(s): {', '.join(missing)}")

    client = NeoAPI(
        environment="prod",
        access_token=None,
        neo_fin_key=None,
        consumer_key=os.environ["KOTAK_NEO_CONSUMER_KEY"],
    )
    # Both calls return a plain dict either way - success looks like
    # {"data": {...}}, an application-level failure (bad TOTP, wrong MPIN,
    # expired credential) comes back as {"error": [{"message": "..."}]}
    # rather than raising. Surface just the message text (never the full
    # dict - it can echo back the ucc/mobile_number that were sent).
    login_resp = client.totp_login(
        mobile_number=os.environ["KOTAK_NEO_MOBILE_NUMBER"],
        ucc=os.environ["KOTAK_NEO_UCC"],
        totp=_current_totp_code(),
    )
    if isinstance(login_resp, dict) and login_resp.get("error"):
        msg = login_resp["error"][0].get("message", "totp_login failed")
        raise RuntimeError(f"Kotak Neo totp_login failed: {msg}")

    validate_resp = client.totp_validate(mpin=os.environ["KOTAK_NEO_MPIN"])
    if isinstance(validate_resp, dict) and validate_resp.get("error"):
        msg = validate_resp["error"][0].get("message", "totp_validate failed")
        raise RuntimeError(f"Kotak Neo totp_validate failed: {msg}")

    # The SDK's own internal convention (see positions()/holdings()) - a
    # real session only exists once both of these are set.
    if not (client.configuration.edit_token and client.configuration.edit_sid):
        raise RuntimeError("Kotak Neo login did not establish a session (no edit_token/edit_sid)")

    return client


# --- Phase 2: read-only account data (2026-09-03) ---------------------------
# Explicit user instruction: "do phase 2" - read-only market/account data,
# still no order placement. Each function below logs in fresh (no session
# caching yet - these are low-frequency diagnostic calls, not a hot path)
# and returns whatever dict/list the SDK itself returns. Callers in main.py
# are responsible for gating access (see KOTAK_NEO_API_TOKEN) - this module
# stays agnostic of HTTP/auth concerns, same as login().


def holdings():
    """Current portfolio holdings for the real account. Read-only - places
    no order. Returns the SDK's own response shape unmodified."""
    return login().holdings()


def positions():
    """Current open positions for the real account. Read-only - places no
    order. Returns the SDK's own response shape unmodified."""
    return login().positions()


def limits():
    """Available margin/funds across all segments for the real account.
    Read-only - places no order. Returns the SDK's own response shape
    unmodified."""
    return login().limits()


def search_scrip(exchange_segment, symbol="", expiry=None, option_type=None, strike_price=None):
    """Searches Kotak's live scrip master for contracts matching the given
    filters (e.g. exchange_segment="nse_fo", symbol="nifty",
    option_type="ce,pe" for an options chain). Read-only - no order placed.

    Deliberately NOT wrapped into a higher-level "ATM strike chain"
    function yet: the SDK's own source (scrip_search.py) confirms this
    returns whatever columns Kotak's live scrip-master CSV has (including
    'dStrikePrice;' and 'pOptionType', confirmed from the SDK's own filter
    logic) but does not document the column that names the instrument
    token quotes() needs - guessing that column name risks silently
    matching the wrong contract, which matters a lot more for financial
    data than most bugs. Call this directly (via
    GET /kotak-neo/search-scrip) to see the real column names first, then
    build the ATM-chain-with-live-quotes function on confirmed data rather
    than a guess."""
    return login().search_scrip(
        exchange_segment=exchange_segment, symbol=symbol, expiry=expiry,
        option_type=option_type, strike_price=strike_price,
    )


def quotes(instrument_tokens, quote_type="ltp"):
    """Live quote(s) for the given instruments. Read-only - no order
    placed. instrument_tokens: list of {"instrument_token": str,
    "exchange_segment": str} dicts.

    Used 2026-09-04 as the verification tool for index instrument tokens
    (e.g. is "Nifty Bank" a real, resolvable token for nse_cm) - indices
    aren't rows in the scrip master search_scrip() reads, so search_scrip
    can't confirm or deny an index token name; only an actual quotes()
    call against it can. Never guess an index token name into
    kotak_live_feed.py's _INDEX_TOKENS without confirming it here first,
    same discipline as every other Kotak field-name claim this session."""
    return login().quotes(instrument_tokens=instrument_tokens, quote_type=quote_type)
