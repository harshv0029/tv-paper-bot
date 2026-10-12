"""B-541 (Mark Douglas, Trading in the Zone): rolling last-N live-trade expectancy monitor.

ALERT-ONLY. Pure functions over a list of net P&L values (INR, after costs, oldest first). Auto-pausing
a strategy through the existing viability gate needs explicit user sign-off and is NOT wired here."""

WINDOW = 20


def rolling_stats(pnls, window: int = WINDOW) -> dict:
    block = [float(x) for x in (pnls or [])][-window:]
    n = len(block)
    wins = sum(x for x in block if x > 0)
    losses = -sum(x for x in block if x < 0)
    pf = (wins / losses) if losses > 0 else (float("inf") if wins > 0 else 0.0)
    return {"n": n, "expectancy": (sum(block) / n) if n else 0.0, "pfnet": pf}


def should_alert(pnls, window: int = WINDOW) -> tuple:
    """(alert, reason). Needs a full window; fewer trades never alert (no evidence either way)."""
    st = rolling_stats(pnls, window)
    if st["n"] < window:
        return False, f"only {st['n']}/{window} trades"
    if st["expectancy"] < 0:
        return True, f"last-{window} expectancy {st['expectancy']:.2f} < 0"
    if st["pfnet"] < 1.0:
        return True, f"last-{window} PFnet {st['pfnet']:.2f} < 1.0"
    return False, "ok"
