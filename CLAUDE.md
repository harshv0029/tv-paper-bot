# CLAUDE.md — read this before doing anything else

This is a **live, real-money** trading bot (NSE/MCX via Kotak Neo), developed
entirely through Claude Code sessions. Mistakes here cost the user real
money. Read this file fully before touching branches, git history, or
entry/exit/sizing logic.

## Communication rules (standing, do not relax without explicit user ask)

- Always state times to the user in IST (UTC+5:30), never UTC. This applies
  to timestamps in chat replies, status updates, and check-in schedules —
  convert before speaking. Internal tool calls, git/CI timestamps, and code
  can still use UTC as needed; only user-facing text must be IST.

## Incident: a validated real-money fix was silently lost (2026-09-14)

A prior session implemented and fully validated two exit-logic bug fixes
(RANGE regime's degenerate stop-loss; `trend_weakened` misapplied to RANGE
positions) on branch `claude/determined-meitner-3btijk`, and left them
unmerged pending a user decision — correct discipline. A **later** session,
picking up separate NIFTY200-universe work, reused that same branch name
under this repo's "if the PR for your branch already merged, restart the
branch from main" rule. That rule requires keeping/rebasing any unmerged
commits forward — but the later session force-reset the branch without
first checking for them, silently discarding both validated fixes. The next
session's transfer pack reported them as "done, tested, validated, sitting
on branch X, ready to merge" — which was **no longer true**; the code was
never on `main` and production kept running the buggy versions. The gap was
only caught by chance during unrelated work, by diffing git history instead
of trusting the transfer pack's prose.

**Never let this pattern repeat:**

1. **Before reusing, resetting, or force-pushing to any branch**, run
   `git log --oneline <branch> ^origin/main` (or `git diff main
   origin/<branch> --stat`) and actually look at the output. If it shows
   commits/files beyond what you're about to add, STOP — those are someone
   else's unmerged work. Rebase them forward onto the new base; never
   silently discard them, even if the branch's *named PR* already merged
   (a branch can carry unmerged commits stacked after a merged PR).
2. **A transfer pack, session summary, or your own memory of "what's done"
   is a claim, not a fact.** Before relying on "fix X is validated and
   sitting on branch Y ready to merge" (or similar), verify it against
   actual git state (`git log`, `git diff` against current `main`) —
   especially before making a decision that assumes it's true (shipping,
   skipping re-validation, telling the user it's handled). This cost real
   time and left a known bug live in production for over a day.
3. **After any branch reset/rebase, sanity-check that CLAUDE.md loaded and
   the expected fixes are actually present** in the file (e.g. `grep` for
   the function/constant a prior session said it added) before reporting
   status to the user as unchanged from a prior transfer pack.
4. If you discover a gap like this, **say so plainly and immediately** —
   don't quietly patch around it or bury it in a status update. The user
   needs to know a validated fix regressed out of production.

## Standing real-money discipline (do not relax without explicit user ask)

- Never tune score weights/thresholds/regime boundaries/exit ladder/
  position-sizing based on one replay result, blind. A bad result is a
  trigger to root-cause it, not to nudge a parameter.
- Any change to entry/exit/sizing logic: implement → unit test → full
  pytest suite green → full 52-symbol/60-day validation replay via
  `.github/workflows/universal-score-validation-replay.yml` → report
  results honestly (including when a fix doesn't move the numbers).
- **Before trusting a replay result**, verify the replay driver actually
  calls the changed `main.py` code — it's a semi-independent
  reimplementation, not a call into `main.py`'s live functions for every
  piece of logic, and has drifted before (see git history/commit messages
  around 2026-09-14 sizing/RANGE-stop fixes for a concrete example of this
  exact gotcha).
- Never merge to `main` (via `deploy-gate.yml`) without the user's explicit
  go-ahead.
- Every commit: full test suite green, `ast.parse` sanity check on
  `main.py`, Claude attribution footer.
