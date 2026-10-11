# Strategy learnings (durable, one entry per strategy or idea discussed)

Rule (CLAUDE.md, 2026-10-11): every new strategy or idea we discuss gets an entry here in the same commit as its backlog row,
with the important items: the mechanism, why it should or should not work in THIS system (NSE/MCX, Kotak, costs, FIFO, no
unstopped trades), what the backtest showed (tags, PFnet, n), what broke or surprised us, and what to reuse next time.

## Overnight anomaly (night vs day), video 2026-10-11, B-363/B-364
- Mechanism: buy close, sell next open (night); short open, cover close (day). Edge is real gross: night long about +0.17% per night on NIFTY 200.
- Lesson: a daily flip pays the round-trip cost every session; at 0.8% it erases any sub-0.5% edge. Check gross edge vs cost before building.
- Result: all four legs fail (PFnet 0.07 to 0.36); stopped day variants identical. Night legs cannot carry a firing stop (market closed).
- Reuse: any high-frequency or tiny-edge idea needs gross edge above about 1% per trade at this cost model.

## Microstructure / pro-rata market making, video 2026-10-11, B-365/B-366
- Mechanism: quote both sides, capture spread, pro-rata fills favour size (CME rate futures).
- Lesson: NSE/MCX are price-time (FIFO); no tick/L2/L3 history; unhedged inventory violates no-trade-without-SL.
- Reuse: order-book imbalance from Kotak depth is the one testable piece (B-366): record snapshots first, backtest later.

## MCX daily cells and the stop question, 2026-10-11, B-355/B-362
- Lesson: a backtest without a stop is not evidence for a stopped live trade. Of 27 no-stop PFnet>1 cells only 8 kept PFnet>=1.1 when ATR-stopped (1.5 and 2.5).
- Rule of thumb: wire a cell only if every stopped variant clears the floor, not just the headline one.

## Option strikes: indicator strategies, 2026-10-11, B-356/B-359
- Lesson: equity-daily PFnet does not transfer to option-premium candles; unmeasured means gated closed. Record shadow signals first, backtest on premium history, then wire.

## Viable floor 1.1, 2026-10-11, B-360
- Lesson: raising the floor from 1.0 to 1.1 closed 117 of 218 wired cells automatically; borderline cells (1.0 to 1.1) are noise-level after costs.
