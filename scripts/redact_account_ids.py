#!/usr/bin/env python3
"""B-1639: mask account identifiers (Kotak "account-XXXXX" entity codes) in files before they are committed to the
PUBLIC repo. Usage: redact_account_ids.py <file-or-dir> ... ; rewrites matching .json/.md/.txt/.log files in place and
prints how many were changed. Same pattern as main._ACCOUNT_ID_RE."""
import os
import re
import sys

PAT = re.compile(r"\b(account-)[A-Za-z0-9]{3,}\b")
PAT2 = re.compile(r"\b[A-Z0-9]{3,12}-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")  # Kotak GuiOrdId/stat: <account>-<uuid>
EXT = (".json", ".md", ".txt", ".log", ".csv")


def redact_text(s: str) -> str:
    return PAT2.sub(r"***-\1", PAT.sub(r"\1***", s))


def redact_file(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read()
    except (UnicodeDecodeError, OSError):
        return False
    n = redact_text(s)
    if n == s:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(n)
    return True


def main(argv) -> int:
    changed = 0
    for root in argv or ["docs", "state"]:
        if os.path.isfile(root):
            changed += redact_file(root)
            continue
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            changed += sum(redact_file(os.path.join(d, f)) for f in files if f.endswith(EXT))
    print(f"redact_account_ids: {changed} file(s) masked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
