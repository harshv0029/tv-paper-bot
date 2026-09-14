"""
Shared decision/outcome type for the risk engines (Modules 480/481/482...).

DERIVED: every Module 47x-48x service contract in the DPR returns the same
shape of thing - "Output: ... deny/reduce decisions" / "approval score,
rejection reason" - with "every denial includes a stable machine reason
code and human-readable explanation" (repeated verbatim in every module's
15.3/16.3/etc. "Validation and error handling" section). This is one shared
type for that, rather than a bespoke Approve/Deny pair reinvented per
module.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EngineDecision:
    approved: bool
    reason_code: str
    reason: str
    data: dict = field(default_factory=dict)
