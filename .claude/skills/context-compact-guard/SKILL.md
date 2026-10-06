---
name: context-compact-guard
description: Context-size guard. When this chat's context nears or passes 200k tokens, save state to git and tell the user to run /compact. Use at every long working session.
---

# Context compact guard (user instruction, 2026-10-07)

The user wants `/compact` run whenever this chat's context passes 200k tokens.
Claude cannot run `/compact` (it is a client command, not a tool), so do this instead:

1. Watch context usage. At ~180k tokens, treat compaction as imminent.
2. Before it: make sure every actionable is a row in `docs/ACTIONABLES_BACKLOG.md`,
   all work is committed and pushed to the designated branch, and any pending
   workflow/check-in (run ids, `send_later` triggers, IST times) is written in the backlog.
3. Tell the user once, in one line, that context is near 200k and to type `/compact`.
   Never claim it was run. Claude Code's own auto-compaction also applies.
4. After a compaction, resume from the backlog and the summary; do not re-derive settled facts.
