"""
New, additive package for AI Trading Platform Bible V63.0 DPR modules.

NOT wired into main.py's live webhook/order-placement path. Each module
under here is built, unit-tested and (where it touches entry/exit/sizing)
replay-validated on its own before any wiring into the live system is even
proposed - per CLAUDE.md's standing real-money discipline. See
docs/dpr_v63_phase1_notes.md for scope, phasing and the implementation
assumptions made where the DPR conflicts with this codebase's reality
(SQLite instead of PostgreSQL, no message broker, etc.).
"""
