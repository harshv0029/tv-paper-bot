---
name: trader-pelosi
description: >-
  India Smart-Money Tracker (the Pelosi skill, ported). Watches who is
  buying and selling Indian stocks in public NSE data: bulk deals (one
  client >= 0.5% of a company in a day), block deals (>= Rs 10 crore) and
  SEBI PIT insider disclosures (promoters, directors, KMP). Shows only new
  rows, IST dates, value in Rs crore, and flags rows in stocks you hold or
  watch. Read-only, never trades. Use when the user says "who is buying",
  "bulk deals", "block deals", "insider trades", "promoter buying",
  "smart money", "what is Pelosi buying" (India equivalent), or "run the
  Pelosi skill". The upstream US Congress PTR reader (ptr.py) is kept for
  US stocks only.
argument-hint: "[member name] [--read]"
---

# trader-pelosi

> **India / Kotak adaptation (tv-paper-bot, 2026-10-23).** Adapted for NSE/Kotak from Jakeschincariol/day-trader-skill (MIT, see `../TRADER_SKILLS_LICENSE`).
> Times are IST (UTC+5:30, no DST); session 09:15-15:30 IST (MCX 09:00-23:30); NSE holidays mirror `main.NSE_HOLIDAYS_2026`; amounts are ₹.
> Use Yahoo `.NS` symbols (RELIANCE.NS, TCS.NS; indices ^NSEI, ^NSEBANK). Cost model: ~0.8% round trip (brokerage 0.20%/side + STT, exchange, SEBI, stamp, GST).
> Worked examples below are upstream US runs re-labelled, kept to show the output shape: their numbers are not Indian prices.
> House rules: no trade without SL/SL-M; check long AND short; this skill never places an order - the live bot (`main.py` / `kotak_real_orders.py`) is the only real-order path.
> Ported (B-1345): **use `deals.py`** - `python3 "${CLAUDE_SKILL_DIR}/deals.py" check [--tickers RELIANCE TCS] [--days 7] [--json]` reads NSE bulk/block deals (`api/snapshot-capital-market-largedeal`) and SEBI PIT insider trades (`api/corporates-pit`), dedupes by state file `trader/state/deals.json`, and stars rows in your portfolio/watchlist. `--week` (Monday of the current IST week to today) or `--from YYYY-MM-DD --to YYYY-MM-DD` switches to NSE's historical endpoints (`api/historical/bulk-deals` and `api/historical/block-deals`, offline files `hist_bulk.json` / `hist_block.json`) and lists every deal in the range, newest date first then by value, e.g. "this week's bulk deals". Best effort (NSE cookie handshake; may throttle or block some IPs; unverified live, built offline). A bulk or insider buy is context, never an entry on its own. The sections below describe the original US `ptr.py`.

Members of Congress have to report their trades, their spouse's and their
dependent children's. The House Clerk posts every report as a PDF and lists
them all in one index file per year. This skill reads that index, notices the
moment a new report appears, and reads the report for you.

It is fast. It is not early. A PTR is due within 30 days of the member
learning of the trade and never more than 45 days after it, so by the time
anyone can read it the trade is days or weeks old. There is no inside
information here: only public filings, read quickly. Say that every time.

Tool in this folder (standard library Python; `pdftotext` from poppler is
optional, to read the PDFs locally):

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" --help
```

## What it reads and writes

- Reads `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip`
  (one `<Member>` per filing: name, district, FilingType, FilingDate, DocID)
  and each PTR at `.../public_disc/ptr-pdfs/<YEAR>/<DocID>.pdf`.
- Writes `trader/state/pelosi.json` (the DocIDs already shown, so each PTR
  alerts once) and keeps downloaded PDFs in `trader/state/ptr-pdfs/`.
- Reads `trader/portfolio.json` (if it exists) to flag trades in what you hold.

## The rules

- **Quote the filing, not a tracker.** Every row comes from the PTR PDF on the
  Clerk's site, with its DocID and link. Third-party trackers are fine for
  browsing but can be off (Capitol Trades showed Pelosi's trade dates one day
  earlier than her PTRs). The PTR wins.
- **Amounts are ranges.** "₹1,000,001 - ₹5,000,000", never "₹3 million".
- **Owner matters.** SP is the spouse, JT joint, DC a dependent child, blank
  the member. Pelosi's 2026 trades are all SP: Paul Pelosi.
- **Say the delay.** Each row shows how many days passed between the trade
  and the filing; over 45 is flagged as late.
- **Options are options.** A call bought with a strike and an expiry is not
  a share purchase. The tool reads contracts, strike and expiry from the
  description and marks exercises.

## Step 1: what has been filed

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --member pelosi
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --since 2026-10-01        # every member
python3 "${CLAUDE_SKILL_DIR}/ptr.py" index --member "Josh Gottheimer" --year 2025
```

`--member` takes a last name, "First Last" or "Last, First", and repeats.
`--type ''` lists every filing type (annual reports are type O).

## Step 2: watch for new ones

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" new --member pelosi --read
```

Shows only PTRs not seen at the last check (the first run shows the last 45
days), downloads and reads them with `--read`, and records them in the state
file. Exit code 1 means nothing new. In January it also checks last year's
index. The Clerk rebuilds the index file about once a day (the copy read on
2026-10-13 was stamped 09:00 that morning), so checking every hour on weekdays
is plenty: run it with `/loop 1h` or a scheduled task.

## Step 3: read a report

```bash
python3 "${CLAUDE_SKILL_DIR}/ptr.py" fetch 20035143
python3 "${CLAUDE_SKILL_DIR}/ptr.py" parse ptr.txt --filed 2026-08-21 --json
```

`fetch` saves the PDF and, if `pdftotext` is installed, prints the rows. If it
is not installed, open the saved PDF and read it directly: you can read PDFs.
`parse` turns `pdftotext -layout` text into rows. Check the row count against
the PDF when a report runs over several pages.

## Example: a real alert

```
NEW Periodic Transaction Report: Hon. Nancy Pelosi (CA11) filed 2026-08-21, doc 20035143
  - spouse purchase, Bloom Energy Corporation Class A Common Stock (BE): 100 call
    options, ₹100 strike, expires 2027-06-17, ₹1,000,001 - ₹5,000,000, traded
    2026-07-24, disclosed 28 days later
```

The same PTR also shows 10,000 and 5,000 BE shares, a second block of 100 BE
calls on 07/28, Intel shares and 50 Intel calls (₹50 strike, 6/17/27), and a
private real estate LLC with no ticker. Her other 2026 PTRs: 20033725
(01/23), 20034836 (06/23, Intel and Uber calls) and 20035553 (10/02, a real
estate LLC). Then: "This is a public disclosure filed 28 days after the trade.
It says what Paul Pelosi bought in July, not what anyone will buy next."

If the user wants to act on it, it goes the long way: a disclosure is weeks
old, so it is a reason to look at a chart, not a setup. `/trader-scanner`
and `/trader-entry` decide if there is a trade today; then shares only (the
config has `allow_options: false`), sized by `/trader-budget`, checked by
`/trader-risk`, placed by `/trader-broker` only after their yes.

## The Senate: the manual route

Senate reports live at `https://efdsearch.senate.gov`. Before searching, the
site asks you to tick a box agreeing to the legal limits on how the reports
may be used. That is an agreement for the person to accept, so this skill
does not click it or automate it. The route:

1. The user opens `https://efdsearch.senate.gov/search/` in their browser and
   accepts the agreement themselves.
2. They pick the report type "Periodic Transactions", type the senator's last
   name, set the date range and search.
3. They open the report: electronic filings show a table of transactions,
   paper filings are scanned images.
4. They paste the table (or a screenshot, or the saved page) into the chat,
   and you write it up in the same shape as the House rows, with the report
   link, and the same 45-day caveat.

## What it never does

- Never says or implies a member has inside information, or that copying a
  politician beats the market. No return claims.
- Never presents a range as an exact dollar figure or a tracker's date as the
  trade date.
- Never places an order, and never copies options trades.
- Never automates the Senate agreement or any login.

## Safety

- Education and tooling, not financial advice. Nothing in this pack is a
  recommendation to buy or sell anything.
- Paper trading by default (`"paper": true` in `trader/config.json`).
- Nothing places an order except `/trader-broker`, and only after
  `/trader-risk` passes AND the user types an explicit yes for that order in
  the chat, AND the brokerage tool is set to "Needs approval" in Claude
  (Customize > Connectors > tool permissions) so Claude's own "Allow once /
  Deny" card appears too. Never "Always allow" an order tool.
- No options, margin, shorting or leverage unless the config allows it and
  the user confirms.
- Congressional trades are PUBLIC disclosures filed up to 45 days after the
  trade (STOCK Act). This skill reads them fast; it has no inside
  information, and it says so.
