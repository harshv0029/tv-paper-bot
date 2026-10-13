# Category naming standard (thumb rule, explicit user instruction 2026-10-13)

Every document, dashboard, backlog row, commit message and discussion uses exactly these six category names:

| Standard name | Internal key (code/registry, unchanged) | Meaning |
|---|---|---|
| Short sell | `short_sell` | intraday short-sell engine |
| Intraday buy | `buy` | intraday long engine |
| Swing | `swing` | multi-day long/short swing engine |
| Futures | `futures` | futures engine |
| Options | `options` | options engine |
| Others | `bidirectional` | natively two-sided strategies (Box Theory, Parabolic SAR, ...) and anything not in the five above |

Rules:
- Internal keys, registry tags and DB values are NOT renamed (immutability rule); only displayed/written names follow this table.
- The trade view maps keys to these labels (Strategy explorer filter and column, Entry funnel).
- Never write "buy", "bidirectional" or "short_sell" as a category name in prose; write the standard name.
