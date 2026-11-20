"""B-1648 (user yes 2026-11-20): one instance at a time may send real orders.

During a Render deploy the old and new instances overlap for minutes and both ran the scheduler, so both could
place real orders (19-Nov 11:16 IST ATGL entry + SL came from the old instance while the new one ran). This keeps
one lease key in Upstash naming the instance allowed to trade:

- At startup the new instance claims the lease unconditionally (newest wins), so the old one stands down at once.
- The holder renews it every RENEW_S (TTL TTL_S). If the holder dies or a failed deploy never renews, the key
  lapses and any live instance claims it again (SET NX).
- On shutdown the holder deletes the key only if it still holds it.
- A standby instance skips its scheduler tick and every real send returns ok=False (`standby_instance`).
- Fail-open: with Upstash unset or unreachable the instance trades as before (no new outage mode); a standby
  verdict needs a positive read naming another holder.
"""
import os
import threading
import time
import uuid

import requests

LEASE_KEY = "tv_paper_bot:instance_lease:v1"
TTL_S = 180
RENEW_S = 60
STANDBY_RECHECK_S = 10  # a standby re-reads the key this often, so it takes over fast when the lease lapses

INSTANCE_ID = f"{os.environ.get('RENDER_INSTANCE_ID', 'local')}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

_creds = lambda: (None, None)  # noqa: E731 - replaced by main.configure()
_lock = threading.Lock()
_state = {"role": "unknown", "holder": None, "checked_at": 0.0, "error": None, "claims": 0}

_RENEW_LUA = ("if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('pexpire',KEYS[1],ARGV[2]) "
              "elseif redis.call('set',KEYS[1],ARGV[1],'NX','PX',ARGV[2]) then return 2 else return 0 end")
_RELEASE_LUA = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


def configure(get_creds) -> None:
    """get_creds() -> (rest_url, token); a callable so an Upstash slot switch in main is picked up."""
    global _creds
    _creds = get_creds


def _cmd(args: list, http_post=None):
    url, tok = _creds()
    if not (url and tok):
        return None, "upstash unset"
    try:
        r = (http_post or requests.post)(url, headers={"Authorization": f"Bearer {tok}"}, json=args, timeout=4)
        body = r.json()
        if "error" in body:
            return None, str(body["error"])[:200]
        return body.get("result"), None
    except Exception as e:  # noqa: BLE001 - never raise into an order path
        return None, f"{type(e).__name__}: {e}"[:200]


def _set(role: str, holder, err=None) -> str:
    _state.update(role=role, holder=holder, checked_at=time.time(), error=err)
    return role


def claim_at_startup(http_post=None) -> str:
    """Newest instance wins: take the lease regardless of the current holder."""
    with _lock:
        res, err = _cmd(["SET", LEASE_KEY, INSTANCE_ID, "PX", str(TTL_S * 1000)], http_post)
        if err:
            return _set("unknown", None, err)
        _state["claims"] += 1
        return _set("leader", INSTANCE_ID)


def refresh(http_post=None) -> str:
    """Renew if held, claim if lapsed, else standby. Returns the role."""
    with _lock:
        res, err = _cmd(["EVAL", _RENEW_LUA, "1", LEASE_KEY, INSTANCE_ID, str(TTL_S * 1000)], http_post)
        if err:
            return _set("unknown", None, err)
        if res in (1, 2):
            if res == 2:
                _state["claims"] += 1
            return _set("leader", INSTANCE_ID)
        holder, err = _cmd(["GET", LEASE_KEY], http_post)
        return _set("standby", holder, err)


def role(now=None, http_post=None, max_age=None) -> str:
    """Cached role; refreshes when due (leader every RENEW_S, standby/unknown every STANDBY_RECHECK_S)."""
    if _state["role"] == "released":
        return "standby"  # shutting down: never reclaim, never send
    now = time.time() if now is None else now
    every = RENEW_S if _state["role"] == "leader" else STANDBY_RECHECK_S
    if max_age is not None:
        every = min(every, max_age)
    if now - _state["checked_at"] >= every:
        return refresh(http_post)
    return _state["role"]


def order_block_reason(http_post=None):
    """None when this instance may send (leader, or lease unknown: fail-open); else the reason text."""
    # sends are rare: re-read at most STANDBY_RECHECK_S old, so a superseded leader stops within seconds
    if role(http_post=http_post, max_age=STANDBY_RECHECK_S) != "standby":
        return None
    return (f"B-1648 standby instance {INSTANCE_ID}: lease held by {_state['holder']}; "
            "this instance does not send real orders")


def release(http_post=None) -> bool:
    with _lock:
        res, err = _cmd(["EVAL", _RELEASE_LUA, "1", LEASE_KEY, INSTANCE_ID], http_post)
        _set("released", None, err)
        return res == 1


def status() -> dict:
    return {"instance_id": INSTANCE_ID, **_state, "ttl_s": TTL_S, "renew_s": RENEW_S}
